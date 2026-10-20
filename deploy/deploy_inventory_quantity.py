"""Deploy the scoped reusable-inventory update with a database rollback gate.

Only the inventory migration, seed, and resource-page assets are copied.  The
active release symlink, Nginx, certificates, MQ credentials, and unrelated
services are left untouched.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("stage2_db.py", "data/stage2_seed.json", "web/app.js", "web/styles.css")
SSH = [
    "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "IdentitiesOnly=yes",
    "-i", str(ROOT.parent / "gongwei.pem"),
]


REMOTE = r'''
import hashlib, json, os, shutil, sqlite3, subprocess, tarfile, time, urllib.request
from pathlib import Path

FILES = FILES_VALUE
SERVICES = ['web', 'resource', 'workorder', 'audio', 'resource-inbox', 'workorder-inbox', 'leader']
PORTS = [18110, 18112, 18113, 18114]
release = Path('/opt/gongwei/current').resolve(strict=True)
assert release.parent == Path('/opt/gongwei/releases')
archive = Path(ARCHIVE_VALUE)
assert hashlib.sha256(archive.read_bytes()).hexdigest() == DIGEST_VALUE
backup = Path('/opt/gongwei/backups') / STAMP_VALUE
backup.mkdir(mode=0o700, parents=False)

def status():
    rows = {}
    for role in SERVICES:
        raw = subprocess.check_output(
            ['systemctl', 'show', 'gongwei-' + role, '-p', 'ActiveState', '-p', 'MainPID', '-p', 'WorkingDirectory'],
            text=True,
        )
        rows[role] = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    return rows

def copy_database(destination):
    with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro', uri=True) as source:
        with sqlite3.connect(destination) as target:
            source.backup(target)
    os.chmod(destination, 0o600)

before = status()
assert all(row.get('ActiveState') == 'active' for row in before.values())
for name in FILES:
    source = release / name
    assert source.is_file() and not source.is_symlink()
    target = backup / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
copy_database(backup / 'stage2.db')
(backup / 'before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2))

members = {}
with tarfile.open(archive) as bundle:
    for member in bundle.getmembers():
        assert member.isfile() and member.name in FILES
        data = bundle.extractfile(member).read()
        members[member.name] = data
assert {name: hashlib.sha256(data).hexdigest() for name, data in members.items()} == HASHES_VALUE

result = {'backup': str(backup), 'release': str(release), 'services': SERVICES,
          'platform_verified': False, 'status': 'PENDING'}
try:
    for role in reversed(SERVICES):
        subprocess.run(['systemctl', 'stop', 'gongwei-' + role], check=True, timeout=60)
    for name, data in members.items():
        target = release / name
        temporary = target.with_name(target.name + '.inventory-new')
        temporary.write_bytes(data)
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    for role in SERVICES:
        subprocess.run(['systemctl', 'start', 'gongwei-' + role], check=True, timeout=60)
    health = {}
    for attempt in range(30):
        try:
            health = {}
            for port in PORTS:
                with urllib.request.urlopen('http://127.0.0.1:' + str(port) + '/health', timeout=3) as response:
                    health[str(port)] = json.load(response)
            current = status()
            assert all(row.get('ActiveState') == 'active' and int(row.get('MainPID', '0')) > 0 for row in current.values())
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(2)
    with sqlite3.connect('/opt/gongwei/shared/data/stage2.db') as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        inventory = db.execute("SELECT id,total_qty,available_qty FROM inventory_items WHERE category='tool' ORDER BY id").fetchall()
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    assert version == 5 and integrity == 'ok'
    result.update(status='PASS', health=health, services=current, inventory=inventory, db_version=version)
except Exception as error:
    result.update(status='ROLLED_BACK', error=type(error).__name__ + ': ' + str(error))
    for role in reversed(SERVICES):
        subprocess.run(['systemctl', 'stop', 'gongwei-' + role], check=False)
    for name in FILES:
        source = backup / name
        target = release / name
        temporary = target.with_name(target.name + '.inventory-rollback')
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    with sqlite3.connect('/opt/gongwei/shared/data/stage2.db') as destination, sqlite3.connect(backup / 'stage2.db') as source:
        source.backup(destination)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    for role in SERVICES:
        subprocess.run(['systemctl', 'start', 'gongwei-' + role], check=False)
    result['services_after_rollback'] = status()
archive.unlink(missing_ok=True)
(backup / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
if result['status'] != 'PASS':
    raise SystemExit(1)
'''


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-inventory-quantity"
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}
    with tempfile.TemporaryDirectory(prefix="gongwei-inventory-") as directory:
        archive = Path(directory) / "inventory.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name in FILES:
                data = (ROOT / name).read_bytes()
                info = tarfile.TarInfo(name)
                info.mode, info.size = 0o644, len(data)
                bundle.addfile(info, io.BytesIO(data))
        remote_archive = "/tmp/" + stamp + ".tar.gz"
        subprocess.run(["scp", *SSH, str(archive), "ubuntu@43.156.60.222:" + remote_archive], check=True)
        code = REMOTE.replace("FILES_VALUE", repr(FILES)).replace("ARCHIVE_VALUE", repr(remote_archive)).replace(
            "DIGEST_VALUE", repr(hashlib.sha256(archive.read_bytes()).hexdigest())
        ).replace("STAMP_VALUE", repr(stamp)).replace("HASHES_VALUE", repr(hashes))
        completed = subprocess.run(
            ["ssh", *SSH, "ubuntu@43.156.60.222", "sudo python3 -"],
            input=code.encode(), capture_output=True, timeout=420,
        )
        if completed.stdout:
            print(completed.stdout.decode(errors="replace"))
        if completed.returncode:
            raise RuntimeError(completed.stderr.decode(errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

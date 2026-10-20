"""Stage reviewed hybrid code and an inactive Leader unit; no live cutover."""
import io
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = '/opt/gongwei/releases/20261006-hybrid'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
       '-i', str(ROOT.parent / 'gongwei.pem'), 'ubuntu@43.156.60.222']


def main():
    members = [p.relative_to(ROOT).as_posix() for p in ROOT.glob('*.py')]
    members += [p.relative_to(ROOT).as_posix() for p in (ROOT/'reports/platform_mq_acs').glob('*.json')]
    members += ['deploy/systemd/gongwei-leader.service', 'deploy/leader.env.example',
                'deploy/requirements-platform.txt', 'platform/approved_acs/leader.json']
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for relative in members:
            data = (ROOT / relative).read_bytes()
            info = tarfile.TarInfo(relative)
            info.size, info.mode = len(data), 0o644
            archive.addfile(info, io.BytesIO(data))
    subprocess.run(SSH + [f'test -d {RELEASE} && sudo tar --no-same-owner -xpf - -C {RELEASE}'], input=buffer.getvalue(), check=True)
    command = f'''set -eu
sudo groupadd --system -f gongwei-data
sudo install -d -m 700 /opt/gongwei/platform
sudo install -m 600 {RELEASE}/deploy/leader.env.example /opt/gongwei/platform/leader.env
sudo chgrp gongwei-data /opt/gongwei/shared/data
sudo chmod 2770 /opt/gongwei/shared/data
sudo find /opt/gongwei/shared/data -maxdepth 1 -type f -name 'stage2.db*' -exec chgrp gongwei-data {{}} + -exec chmod 660 {{}} +
sudo install -m 644 {RELEASE}/deploy/systemd/gongwei-leader.service /etc/systemd/system/gongwei-leader.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/gongwei-leader.service
readlink -f /opt/gongwei/current
sudo systemctl show gongwei-leader -p LoadState -p ActiveState -p UnitFileState
'''
    result = subprocess.run(SSH + [command], capture_output=True)
    (ROOT/'reports/hybrid-platform-20261006/server-staged-release.log').write_bytes(result.stdout+result.stderr)
    print(result.stdout.decode('utf-8', errors='replace'))
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))


if __name__ == '__main__':
    main()

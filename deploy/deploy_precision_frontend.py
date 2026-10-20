"""Publish only the three existing web assets, with backup and automatic rollback."""
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/frontend-precision-acceptance-20261008'
FILES = ('web/app.js', 'web/styles.css', 'web/index.html')
SSH = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
       '-i', str(ROOT.parent / 'gongwei.pem')]

REMOTE = r'''
import hashlib,json,os,re,shutil,sqlite3,subprocess,tarfile,urllib.request
from pathlib import Path
files=('web/app.js','web/styles.css','web/index.html')
release=Path('/opt/gongwei/current').resolve(strict=True)
assert release.parent==Path('/opt/gongwei/releases')
assert all((release/name).is_file() and not (release/name).is_symlink() for name in files)
roles=['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox','amp-heartbeat']
def snapshot():
 services={role:dict(line.split('=',1) for line in subprocess.run(['systemctl','show','gongwei-'+role,
  '-p','MainPID','-p','ActiveState','-p','UnitFileState'],capture_output=True,text=True,check=True).stdout.splitlines() if '=' in line) for role in roles}
 nginx={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/etc/nginx').rglob('*') if p.is_file()}
 with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
  data={'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],
   'orders':db.execute('select count(*) from work_orders').fetchone()[0],
   'reservations':db.execute("select count(*) from reservations where status='active'").fetchone()[0]}
 return {'services':services,'nginx':nginx,'database':data}
archive=Path(ARCHIVE)
assert hashlib.sha256(archive.read_bytes()).hexdigest()==DIGEST
backup=Path('/opt/gongwei/backups')/STAMP
assert backup.parent==Path('/opt/gongwei/backups') and not backup.exists()
backup.mkdir(mode=0o700,parents=True)
before=snapshot()
assert before['database']['integrity']=='ok'
assert all(s['ActiveState']=='active' for s in before['services'].values())
for name in files:
 (backup/name).parent.mkdir(parents=True,exist_ok=True)
 shutil.copy2(release/name,backup/name)
with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as source:
 with sqlite3.connect(backup/'stage2.db') as destination: source.backup(destination)
os.chmod(backup/'stage2.db',0o600)
data={}
with tarfile.open(archive) as bundle:
 assert {m.name for m in bundle.getmembers()}==set(files)
 for member in bundle.getmembers():
  assert member.isfile() and member.name in files
  data[member.name]=bundle.extractfile(member).read()
assert {n:hashlib.sha256(b).hexdigest() for n,b in data.items()}==HASHES
result={'backup':str(backup),'release':str(release),'before':before,'files':HASHES,'service_restart':False}
try:
 for name in files:
  target=release/name
  temp=target.with_name(target.name+'.precision-new')
  assert not temp.exists()
  temp.write_bytes(data[name]);os.chmod(temp,0o644)
  os.replace(temp,target)
 after=snapshot()
 assert after==before,'Service/configuration/database changed during frontend deployment'
 for name in files: assert hashlib.sha256((release/name).read_bytes()).hexdigest()==HASHES[name]
 upstream=re.findall(r'proxy_pass\s+(http://127\.0\.0\.1:\d+);',Path('/etc/nginx/sites-available/gongwei.yanyi.online').read_text())
 assert len(set(upstream))==1,'Ambiguous existing web upstream'
 for endpoint in [upstream[0]+'/health','https://gongwei.yanyi.online/health']:
  with urllib.request.urlopen(endpoint,timeout=20) as response:
   assert response.status==200 and json.load(response)['status']=='ok'
 for name in files:
  path='/' if name=='web/index.html' else '/static/'+name.removeprefix('web/')
  with urllib.request.urlopen('https://gongwei.yanyi.online'+path,timeout=20) as response:
   assert hashlib.sha256(response.read()).hexdigest()==HASHES[name]
 result.update(status='PASS',after=after,public_asset_hashes='PASS')
except Exception as error:
 for name in files:
  temp=(release/name).with_name(Path(name).name+'.precision-rollback')
  shutil.copy2(backup/name,temp);os.replace(temp,release/name)
 result.update(status='ROLLED_BACK',error=str(error),after=snapshot())
(backup/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
archive.unlink()
print(json.dumps(result,ensure_ascii=False))
if result['status']!='PASS': raise SystemExit(1)
'''


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-precision-frontend'
    hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}
    with tempfile.TemporaryDirectory(prefix='gongwei-frontend-') as folder:
        package = Path(folder)/'frontend.tar.gz'
        with tarfile.open(package, 'w:gz') as bundle:
            for name in FILES:
                data = (ROOT/name).read_bytes()
                info = tarfile.TarInfo(name)
                info.mode, info.size = 0o644, len(data)
                bundle.addfile(info, io.BytesIO(data))
        archive = '/tmp/'+stamp+'.tar.gz'
        subprocess.run(['scp', *SSH, str(package), 'ubuntu@43.156.60.222:'+archive], check=True)
        parameters = {'ARCHIVE': archive, 'DIGEST': hashlib.sha256(package.read_bytes()).hexdigest(),
                      'STAMP': stamp, 'HASHES': hashes}
        program = '\n'.join(f'{key}={value!r}' for key,value in parameters.items())+'\n'+REMOTE
        completed = subprocess.run(['ssh', *SSH, 'ubuntu@43.156.60.222', 'sudo python3 -'],
                                   input=program.encode(), capture_output=True)
        if completed.stdout:
            result = json.loads(completed.stdout)
            REPORT.mkdir(parents=True, exist_ok=True)
            (REPORT/'deployment.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            print(json.dumps({key: result.get(key) for key in ['status','release','backup','service_restart','public_asset_hashes']}))
        if completed.returncode:
            raise RuntimeError(completed.stderr.decode(errors='replace'))


if __name__ == '__main__':
    main()

"""Activate a verified release for the Leader only; keep other services intact."""
import json
from pathlib import Path
from deploy_experience_refresh import remote

REPORT = Path(__file__).resolve().parents[1] / 'reports/dingdang-continuation-20261007/deployment'


def main():
    cfg = json.loads((REPORT / 'backup.json').read_text())
    assert all(value['exit_code'] == 0 for value in json.loads((REPORT / 'server-tests.json').read_text()).values())
    result = remote(r'''
import hashlib,json,subprocess,time,sqlite3
from pathlib import Path
cfg=CONFIG
release=Path(cfg['new_release']);backup=Path(cfg['backup'])
assert release.parent==Path('/opt/gongwei/releases') and backup.parent==Path('/opt/gongwei/backups')
for entry in json.loads((release/'deployment-manifest.json').read_text()):
 assert hashlib.sha256((release/entry['path']).read_bytes()).hexdigest()==entry['sha256']
override=Path('/etc/systemd/system/gongwei-leader.service.d/90-maintenance-release.conf')
prior=override.read_text();(backup/'leader-override-before.conf').write_text(prior)
roles=['leader','resource-inbox','workorder-inbox','web','resource','workorder','audio','amp-heartbeat']
def status():
 return {r:dict(x.split('=',1) for x in subprocess.check_output(['systemctl','show','gongwei-'+r,'-p','ActiveState','-p','MainPID','-p','WorkingDirectory'],text=True).splitlines()) for r in roles}
before=status();report={'before':before,'release':str(release),'platform_verified':False}
try:
 subprocess.run(['systemctl','stop','gongwei-leader'],check=True,timeout=100)
 for name,source in [('business','/opt/gongwei/shared/data/stage2.db'),('rpc','/var/lib/gongwei-leader/rpc.sqlite3')]:
  with sqlite3.connect('file:'+source+'?mode=ro',uri=True) as src,sqlite3.connect(backup/(name+'-leader-cutover.sqlite3')) as dst:src.backup(dst)
 override.write_text('[Service]\nWorkingDirectory='+str(release)+'\n')
 subprocess.run(['systemctl','daemon-reload'],check=True)
 subprocess.run(['systemctl','start','gongwei-leader'],check=True)
 for _ in range(20):
  after=status()
  if after['leader']['ActiveState']=='active' and subprocess.run(['ss','-ltnH','sport = :18443'],capture_output=True,text=True).stdout.strip():break
  time.sleep(1)
 else:raise RuntimeError('Leader TLS listener not ready')
 assert all(after[r]['ActiveState']=='active' for r in roles)
 assert all(after[r]['MainPID']==before[r]['MainPID'] for r in roles if r!='leader')
 assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in cfg['nginx'].items())
 report.update(pass_result=True,after=after,nginx_unchanged=True,other_processes_unchanged=True)
except Exception as exc:
 override.write_text(prior);subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','gongwei-leader'],check=True)
 report.update(pass_result=False,rolled_back=True,error=type(exc).__name__+': '+str(exc),after=status())
(backup/'leader-activation.json').write_text(json.dumps(report));print(json.dumps(report))
'''.replace('CONFIG', repr(cfg)), timeout=180)
    (REPORT / 'activation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('before', 'after')}))
    assert result['pass_result']


if __name__ == '__main__':
    main()

"""Activate the verified Partner recovery fix without restarting other services."""
import json
from pathlib import Path
from deploy_experience_refresh import remote

REPORT = Path(__file__).resolve().parents[1] / 'reports/online-continuation-investigation-20261007/partner-deployment'


def main():
    cfg = json.loads((REPORT / 'backup.json').read_text())
    assert all(v['exit_code'] == 0 for v in json.loads((REPORT / 'server-tests.json').read_text()).values())
    result = remote(r'''
import json,hashlib,subprocess,time,os,tarfile
from pathlib import Path
from datetime import datetime,timezone
cfg=CONFIG;release=Path(cfg['new_release']);backup=Path(cfg['backup'])
assert release.parent==Path('/opt/gongwei/releases') and backup.parent==Path('/opt/gongwei/backups')
for entry in json.loads((release/'deployment-manifest.json').read_text()):
 assert hashlib.sha256((release/entry['path']).read_bytes()).hexdigest()==entry['sha256']
targets=['resource-inbox','workorder-inbox']
roles=['leader',*targets,'web','resource','workorder','audio','amp-heartbeat']
def status():
 return {r:dict(x.split('=',1) for x in subprocess.check_output(['systemctl','show','gongwei-'+r,'-p','ActiveState','-p','MainPID','-p','WorkingDirectory'],text=True).splitlines()) for r in roles}
before=status();prior={}
for role in targets:
 p=Path('/etc/systemd/system/gongwei-'+role+'.service.d/90-maintenance-release.conf')
 prior[str(p)]=p.read_text()
 (backup/(role+'-override-before.conf')).write_text(prior[str(p)])
 old=Path(before[role]['WorkingDirectory']).resolve();assert old.parent==Path('/opt/gongwei/releases')
 with tarfile.open(backup/(role+'-code-before.tar.gz'),'w:gz') as tar:tar.add(old,arcname=old.name)
 os.chmod(backup/(role+'-code-before.tar.gz'),0o600)
report={'started_at':datetime.now(timezone.utc).isoformat(),'before':before,'release':str(release),'platform_verified':False}
try:
 for role in targets:subprocess.run(['systemctl','stop','gongwei-'+role],check=True,timeout=100)
 for p in prior:Path(p).write_text('[Service]\nWorkingDirectory='+str(release)+'\n')
 subprocess.run(['systemctl','daemon-reload'],check=True)
 for role in targets:subprocess.run(['systemctl','start','gongwei-'+role],check=True)
 for attempt in range(30):
  after=status()
  listening=all('event=partner_inbox_listening' in subprocess.check_output(['journalctl','-u','gongwei-'+r,'--since',report['started_at'],'--no-pager'],text=True) for r in targets)
  if listening and all(x['ActiveState']=='active' for x in after.values()):break
  time.sleep(1)
 else:raise RuntimeError('Partner Inbox startup did not complete')
 assert all(after[r]['MainPID']==before[r]['MainPID'] for r in roles if r not in targets)
 assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in cfg['nginx'].items())
 report.update(pass_result=True,after=after,nginx_unchanged=True,other_processes_unchanged=True)
except Exception as e:
 for p,content in prior.items():Path(p).write_text(content)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 for role in targets:subprocess.run(['systemctl','restart','gongwei-'+role],check=True)
 report.update(pass_result=False,error=type(e).__name__+': '+str(e),rolled_back=True,after=status())
(backup/'partner-activation.json').write_text(json.dumps(report));print(json.dumps(report))
'''.replace('CONFIG', repr(cfg)), timeout=300)
    (REPORT / 'activation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('before', 'after')}))
    assert result['pass_result']


if __name__ == '__main__':
    main()

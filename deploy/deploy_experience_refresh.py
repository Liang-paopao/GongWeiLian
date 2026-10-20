"""Back up, stage, test and activate the scoped October 7 UI/ADP update."""
import argparse
import json
import subprocess
from pathlib import Path

import stage_maintenance_release as stage

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/experience-refresh-20261007'


def remote(code, timeout=300):
    p = subprocess.run(['ssh', *stage.SSH_OPTIONS, 'ubuntu@43.156.60.222', 'sudo python3 -'],
                       input=code.encode(), capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors='replace'))
    return json.loads(p.stdout)


def prepare():
    assert not (REPORT / 'backup.json').exists(), 'Reuse the existing staged backup, do not duplicate it.'
    result = remote('''
import json,hashlib,subprocess,sqlite3,tarfile,os
from pathlib import Path
from datetime import datetime,timezone
stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
old=Path('/opt/gongwei/current').resolve();backup=Path('/opt/gongwei/backups')/(stamp+'-experience')
assert old.parent==Path('/opt/gongwei/releases')
backup.mkdir(mode=0o700)
with tarfile.open(backup/'code.tar.gz','w:gz') as tar:tar.add(old,arcname=old.name)
with tarfile.open(backup/'config.tar.gz','w:gz') as tar:
 for path in [Path('/etc/nginx'),Path('/opt/gongwei/gongwei.env'),Path('/opt/gongwei/platform'),*Path('/etc/systemd/system').glob('gongwei*')]:
  tar.add(path,arcname=str(path).lstrip('/'))
for p in backup.glob('*.tar.gz'):os.chmod(p,0o600)
for name,source in [('business','/opt/gongwei/shared/data/stage2.db'),('rpc','/var/lib/gongwei-leader/rpc.sqlite3')]:
 with sqlite3.connect('file:'+source+'?mode=ro',uri=True) as src,sqlite3.connect(backup/(name+'.sqlite3')) as dst:src.backup(dst)
 os.chmod(backup/(name+'.sqlite3'),0o600)
nginx={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/etc/nginx').rglob('*') if p.is_file()}
cfg={'old_web':str(old),'backup':str(backup),'new_release':'/opt/gongwei/releases/'+stamp+'-maintenance','nginx':nginx,'platform_verified':False}
(backup/'metadata.json').write_text(json.dumps(cfg));print(json.dumps(cfg))
''')
    (REPORT / 'backup.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    stage.REPORT = REPORT
    stage.main()


def test_release():
    cfg = json.loads((REPORT / 'backup.json').read_text())
    code = '''
import subprocess,json,os
from pathlib import Path
release=Path(RELEASE);results={}
env=os.environ.copy();env.update(PYTHONUTF8='1',GONGWEI_PARTNER_DISCOVERY_POLICY='default_online')
for name,args in [('unittest',['-m','unittest','discover','-p','test_*.py']),('stage2',['run_stage2_tests.py']),('stage5',['run_stage5_tests.py'])]:
 p=subprocess.run(['/opt/gongwei/.venv/bin/python',*args],cwd=release,env=env,capture_output=True,timeout=150)
 results[name]={'exit_code':p.returncode,'output':(p.stdout+p.stderr).decode(errors='replace')}
print(json.dumps(results))
'''.replace('RELEASE', repr(cfg['new_release']))
    result = remote(code, timeout=500)
    (REPORT / 'server-tests.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for name, value in result.items():
        (REPORT / f'server-{name}.log').write_text(value['output'], encoding='utf-8')
        print(name, value['exit_code'])
    assert all(x['exit_code'] == 0 for x in result.values()), 'Release tests failed'


def activate():
    assert all(x['exit_code'] == 0 for x in json.loads((REPORT / 'server-tests.json').read_text()).values())
    cfg = json.loads((REPORT / 'backup.json').read_text())
    result = remote('''
import json,hashlib,subprocess,os,time,urllib.request,sqlite3
from pathlib import Path
from datetime import datetime,timezone
cfg=CONFIG;backup=Path(cfg['backup']);release=Path(cfg['new_release']);current=Path('/opt/gongwei/current')
assert str(current.resolve())==cfg['old_web']
for entry in json.loads((release/'deployment-manifest.json').read_text()):assert hashlib.sha256((release/entry['path']).read_bytes()).hexdigest()==entry['sha256']
roles=['resource','workorder','audio','web','resource-inbox','workorder-inbox','leader']
overrides=[Path('/etc/systemd/system/gongwei-'+r+'.service.d/90-maintenance-release.conf') for r in ['resource-inbox','workorder-inbox','leader']]
prior={str(p):p.read_text() for p in overrides};envfile=Path('/opt/gongwei/platform/leader.env');oldenv=envfile.read_text()
for name,source in [('business','/opt/gongwei/shared/data/stage2.db'),('rpc','/var/lib/gongwei-leader/rpc.sqlite3')]:
 with sqlite3.connect('file:'+source+'?mode=ro',uri=True) as src,sqlite3.connect(backup/(name+'-cutover.sqlite3')) as dst:src.backup(dst)
 os.chmod(backup/(name+'-cutover.sqlite3'),0o600)
def switch(target):
 tmp=Path('/opt/gongwei/current.experience-next');assert not tmp.exists();tmp.symlink_to(target);os.replace(tmp,current)
def service_status():
 result={}
 for role in roles+['amp-heartbeat']:
  text=subprocess.check_output(['systemctl','show','gongwei-'+role,'-p','ActiveState','-p','MainPID','-p','NRestarts','-p','WorkingDirectory'],text=True)
  result[role]=dict(line.split('=',1) for line in text.splitlines() if '=' in line)
 return result
report={'started_at':datetime.now(timezone.utc).isoformat(),'release':str(release),'platform_verified':False}
try:
 for role in reversed(roles):subprocess.run(['systemctl','stop','gongwei-'+role],check=True)
 for p in overrides:p.write_text('[Service]\\nWorkingDirectory='+str(release)+'\\n')
 lines=[line for line in oldenv.splitlines() if not line.startswith('GONGWEI_PARTNER_DISCOVERY_POLICY=')]
 envfile.write_text('\\n'.join(lines)+'\\nGONGWEI_PARTNER_DISCOVERY_POLICY=platform_catalog\\n')
 switch(release);subprocess.run(['systemctl','daemon-reload'],check=True)
 for role in roles:subprocess.run(['systemctl','start','gongwei-'+role],check=True)
 for attempt in range(40):
  try:
   health={}
   for port in [18110,18112,18113,18114]:
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/health',timeout=3) as r:health[str(port)]=json.load(r)
   status=service_status();assert all(v['ActiveState']=='active' and int(v['MainPID'])>0 for v in status.values())
   for role in ['resource-inbox','workorder-inbox']:
    journal=subprocess.check_output(['journalctl','-u','gongwei-'+role,'--since',report['started_at'],'--no-pager'],text=True)
    assert 'event=partner_inbox_listening' in journal
   break
  except Exception:
   if attempt==39:raise
   time.sleep(2)
 assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in cfg['nginx'].items())
 report.update(pass_result=True,services=status,health=health,nginx_unchanged=True,partner_discovery_policy='platform_catalog')
except Exception as e:
 report.update(pass_result=False,error=type(e).__name__+': '+str(e))
 for role in reversed(roles):subprocess.run(['systemctl','stop','gongwei-'+role],check=False)
 switch(cfg['old_web']);envfile.write_text(oldenv)
 for p,content in prior.items():Path(p).write_text(content)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 for role in roles:subprocess.run(['systemctl','start','gongwei-'+role],check=True)
 report.update(rolled_back=True,services=service_status())
(backup/'activation-result.json').write_text(json.dumps(report));print(json.dumps(report))
'''.replace('CONFIG', repr(cfg)), timeout=300)
    (REPORT / 'activation-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    assert result['pass_result']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'test', 'activate'])
    action = parser.parse_args().action
    REPORT.mkdir(parents=True, exist_ok=True)
    {'prepare': prepare, 'test': test_release, 'activate': activate}[action]()

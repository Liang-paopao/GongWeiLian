"""Activate an already-tested release; restore code paths on a failed health gate."""
import json
import subprocess
from pathlib import Path

from stage_maintenance_release import REPORT, SSH_OPTIONS


def main():
    settings = json.loads((REPORT / 'backup.json').read_text())
    assert json.loads((REPORT / 'server-unittest-final.json').read_text())['exit_code'] == 0
    assert all(v['exit_code'] == 0 for k, v in json.loads((REPORT / 'server-tests.json').read_text()).items()
               if k != 'unittest')
    assert json.loads((REPORT / 'formal-mq-test.json').read_text())['report']['pass_result'] is True
    remote = '''
import hashlib,json,os,sqlite3,subprocess,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone
cfg=SETTINGS
release=Path(cfg['new_release']);backup=Path(cfg['backup'])
formal=['resource-inbox','workorder-inbox','leader']
roles=['resource','workorder','audio','web',*formal]
current=Path('/opt/gongwei/current')
assert str(current.resolve())==cfg['old_web']
for required in ['reports/platform_mq_acs/resource_partner.json', 'reports/platform_mq_acs/work_order_partner.json']:
 assert (release/required).is_file(), 'release missing runtime Partner ACS: '+required
for entry in json.loads((release/'deployment-manifest.json').read_text()):
 assert hashlib.sha256((release/entry['path']).read_bytes()).hexdigest()==entry['sha256']
overrides=[Path('/etc/systemd/system/gongwei-'+r+'.service.d/90-maintenance-release.conf') for r in formal]
assert all(not p.exists() for p in overrides)
assert not Path('/opt/gongwei/current.maintenance-next').exists()
result={'release':str(release),'started_at':datetime.now(timezone.utc).isoformat(),'platform_verified':False}
def switch(target):
 next_link=Path('/opt/gongwei/current.maintenance-next')
 next_link.symlink_to(target);os.replace(next_link,current)
def check():
 status={}
 for role in roles+['amp-heartbeat']:
  p=subprocess.run(['systemctl','show','gongwei-'+role,'-p','ActiveState','-p','MainPID','-p','NRestarts','-p','WorkingDirectory'],capture_output=True,text=True,check=True)
  status[role]=dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)
 return status
try:
 # Save another consistent backup immediately before the live switch.
 for name,source in [('business','/opt/gongwei/shared/data/stage2.db'),('rpc','/var/lib/gongwei-leader/rpc.sqlite3')]:
  with sqlite3.connect('file:'+source+'?mode=ro',uri=True) as src,sqlite3.connect(backup/(name+'-cutover.sqlite3')) as dst:src.backup(dst)
 for role in ['leader','web','resource-inbox','workorder-inbox','resource','workorder','audio']:
  subprocess.run(['systemctl','stop','gongwei-'+role],check=True)
 for p in overrides:
  p.parent.mkdir(exist_ok=True)
  p.write_text('[Service]\\nWorkingDirectory='+str(release)+'\\n')
 switch(release)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 for role in roles:subprocess.run(['systemctl','start','gongwei-'+role],check=True)
 health={}
 for attempt in range(45):
  try:
   for port in [18110,18112,18113,18114]:
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/health',timeout=3) as response:health[str(port)]=json.load(response)
   status=check()
   assert all(v['ActiveState']=='active' and int(v['MainPID'])>0 for v in status.values())
   for role in ['resource-inbox','workorder-inbox']:
    journal=subprocess.check_output(['journalctl','-u','gongwei-'+role,'--since',result['started_at'],'--no-pager'],text=True)
    assert 'event=partner_inbox_listening' in journal
   with urllib.request.urlopen('https://gongwei.yanyi.online/health',timeout=6) as response:health['public_web']=json.load(response)
   break
  except Exception:
   if attempt==44:raise
   time.sleep(2)
 result.update(pass_result=True,services=status,health=health)
except Exception as e:
 result.update(pass_result=False,error=type(e).__name__+': '+str(e))
 for role in ['leader','web','resource-inbox','workorder-inbox','resource','workorder','audio']:
  subprocess.run(['systemctl','stop','gongwei-'+role],check=False)
 switch(cfg['old_web'])
 for p in overrides:
  if p.exists():p.unlink()
 subprocess.run(['systemctl','daemon-reload'],check=True)
 for role in roles:subprocess.run(['systemctl','start','gongwei-'+role],check=True)
 result.update(rolled_back=True,services=check())
result['finished_at']=datetime.now(timezone.utc).isoformat()
(backup/'activation-result.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,ensure_ascii=False))
'''.replace('SETTINGS', repr(settings))
    process = subprocess.run(['ssh', *SSH_OPTIONS, 'ubuntu@43.156.60.222', 'sudo python3 -'],
                             input=remote.encode(), capture_output=True, timeout=300)
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors='replace'))
    result = json.loads(process.stdout)
    (REPORT / 'activation-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['pass_result'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

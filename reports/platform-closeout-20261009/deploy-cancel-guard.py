"""Deploy one reviewed Leader file with private backup and bounded rollback."""
import base64
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMOTE = r'''
import ast,base64,datetime,hashlib,json,os,shutil,sqlite3,subprocess,time
from pathlib import Path
target=Path('/opt/gongwei/releases/20261007-120338-maintenance/leader_external_flow.py')
raw=base64.b64decode(payload);ast.parse(raw)
roles=['web','resource','workorder','audio','resource-inbox','workorder-inbox','amp-heartbeat','amp-metadata']
def pids():return {x:subprocess.check_output(['systemctl','show','gongwei-'+x,'-p','MainPID','--value'],text=True).strip() for x in roles}
backup=Path('/opt/gongwei/backups')/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-cancel-guard');backup.mkdir(mode=0o700)
shutil.copy2(target,backup/target.name)
for name,path in [('business','/opt/gongwei/shared/data/stage2.db'),('rpc','/var/lib/gongwei-leader/rpc.sqlite3')]:
 with sqlite3.connect('file:'+path+'?mode=ro',uri=True) as source,sqlite3.connect(backup/(name+'.sqlite3')) as destination:source.backup(destination)
 os.chmod(backup/(name+'.sqlite3'),0o600)
r={'backup':str(backup),'before_pids':pids(),'changed_file':str(target),'sha256':hashlib.sha256(raw).hexdigest(),'platform_verified':False}
try:
 target.write_bytes(raw);os.chmod(target,0o644)
 subprocess.run(['systemctl','restart','gongwei-leader'],check=True,timeout=60)
 for _ in range(30):
  if subprocess.run(['systemctl','is-active','--quiet','gongwei-leader']).returncode==0:break
  time.sleep(1)
 assert subprocess.run(['systemctl','is-active','--quiet','gongwei-leader']).returncode==0
 r['after_pids']=pids();assert r['before_pids']==r['after_pids']
 r['pass_result']=True
except BaseException as e:
 shutil.copy2(backup/target.name,target);subprocess.run(['systemctl','restart','gongwei-leader'],timeout=60)
 r.update(pass_result=False,error_type=type(e).__name__,rollback='original Leader file restored')
print(json.dumps(r))
'''
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222','sudo /opt/gongwei/.venv/bin/python -']
done=subprocess.run(ssh,input=('payload='+repr(base64.b64encode((ROOT/'leader_external_flow.py').read_bytes()).decode())+'\n'+REMOTE).encode(),capture_output=True,timeout=200)
done.check_returncode();result=json.loads(done.stdout)
Path(__file__).with_name('cancel-guard-deployment.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result));assert result['pass_result']

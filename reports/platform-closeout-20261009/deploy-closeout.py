"""Deploy reviewed own-project files; preserve all identities and shared sites."""
import base64,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
FOLDER=Path(__file__).parent
scope={
 '20261007-120338-maintenance':['stage2_domain.py','leader_external_flow.py','leader_rpc_runtime.py','plan_continuation.py','amp_telemetry.py','mq_group_transport.py','mq_partner_runtime.py'],
 '20261007-095036-maintenance':['stage2_domain.py','amp_telemetry.py','mq_partner_runtime.py'],
 '20261006-211426-maintenance':['stage2_domain.py','web/app.js','web/index.html'],
}
payload={name:base64.b64encode((ROOT/name).read_bytes()).decode() for names in scope.values() for name in names}
REMOTE=r'''
import base64,datetime,hashlib,json,os,shutil,sqlite3,subprocess,time
from pathlib import Path
roles=['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox','amp-heartbeat']
changed_roles=['resource','workorder','web','resource-inbox','workorder-inbox','leader']
def services():return {r:dict(x.split('=',1) for x in subprocess.check_output(['systemctl','show','gongwei-'+r,'-p','ActiveState','-p','MainPID','-p','UnitFileState'],text=True).splitlines()) for r in roles}
base=Path('/opt/gongwei/releases')
assert Path('/opt/gongwei/current').resolve()==base/'20261006-211426-maintenance'
for role,release in [('leader','20261007-120338-maintenance'),('resource-inbox','20261007-095036-maintenance'),('workorder-inbox','20261007-095036-maintenance')]:
 assert Path(subprocess.check_output(['systemctl','show','gongwei-'+role,'-p','WorkingDirectory','--value'],text=True).strip()).resolve()==base/release
with sqlite3.connect('file:/var/lib/gongwei-leader/rpc.sqlite3?mode=ro',uri=True) as db:
 assert not db.execute('SELECT 1 FROM rpc_tasks WHERE pending_json IS NOT NULL OR cancel_json IS NOT NULL').fetchone(),'Leader has pending work'
backup=Path('/opt/gongwei/backups')/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-closeout');backup.mkdir(mode=0o700)
result={'backup':str(backup),'before':services(),'platform_verified':False,'changed_files':[]}
for name,path in [('business','/opt/gongwei/shared/data/stage2.db'),('rpc','/var/lib/gongwei-leader/rpc.sqlite3')]:
 with sqlite3.connect('file:'+path+'?mode=ro',uri=True) as source,sqlite3.connect(backup/(name+'.sqlite3')) as destination:source.backup(destination)
 os.chmod(backup/(name+'.sqlite3'),0o600)
config=Path('/opt/gongwei/platform/leader.env');shutil.copy2(config,backup/'leader.env');os.chmod(backup/'leader.env',0o600)
for role in roles:
 unit=Path('/etc/systemd/system/gongwei-'+role+'.service')
 if unit.exists():shutil.copy2(unit,backup/unit.name)
changes=[]
try:
 for release,names in scope.items():
  for name in names:
   target=base/release/name
   assert target.resolve().is_relative_to(base/release)
   saved=backup/'before'/release/name;saved.parent.mkdir(parents=True,exist_ok=True)
   existed=target.exists()
   if existed:shutil.copy2(target,saved)
   stat=target.stat() if existed else target.parent.stat()
   temporary=target.with_name(target.name+'.closeout-tmp');temporary.write_bytes(base64.b64decode(payload[name]));os.chmod(temporary,0o644);os.chown(temporary,stat.st_uid,stat.st_gid);temporary.replace(target)
   changes.append((target,saved,existed));result['changed_files'].append({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
 original=config.read_text();lines=[l for l in original.splitlines() if not l.startswith('GONGWEI_AMP_METADATA_ENABLED=')];config.write_text('\n'.join(lines)+'\nGONGWEI_AMP_METADATA_ENABLED=1\n');os.chmod(config,0o600)
 subprocess.run(['systemctl','restart',*['gongwei-'+r for r in changed_roles]],check=True,timeout=70)
 for _ in range(80):
  if all(v['ActiveState']=='active' for v in services().values()) and subprocess.run(['ss','-ltnH','sport = :18443'],capture_output=True,text=True).stdout.strip():break
  time.sleep(.5)
 else:raise RuntimeError('Services not ready')
 result['after']=services();assert all(result['before'][r]['MainPID']==result['after'][r]['MainPID'] for r in ['audio','amp-heartbeat'])
 result['pass_result']=True
except BaseException as error:
 for target,saved,existed in changes:
  if existed:shutil.copy2(saved,target)
  else:target.unlink(missing_ok=True)
 shutil.copy2(backup/'leader.env',config)
 subprocess.run(['systemctl','restart',*['gongwei-'+r for r in changed_roles]],check=True,timeout=70)
 result.update(pass_result=False,rolled_back=True,error=type(error).__name__)
print(json.dumps(result,ensure_ascii=False,indent=2))
'''
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-o','ServerAliveInterval=10','-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222']
r=subprocess.run(ssh+['sudo /opt/gongwei/.venv/bin/python -'],input=('payload='+repr(payload)+'\nscope='+repr(scope)+'\n'+REMOTE).encode(),capture_output=True,timeout=300)
if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace'))
result=json.loads(r.stdout);(FOLDER/'deployment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False));assert result['pass_result']

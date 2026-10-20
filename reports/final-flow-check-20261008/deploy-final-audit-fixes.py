"""Deploy only four reviewed files in existing own releases, with rollback."""
import base64,json,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
files={name:base64.b64encode((ROOT/name).read_bytes()).decode() for name in ['plan_continuation.py','leader_external_flow.py','test_homepage_continuation.py','web/app.js','web/index.html']}
REMOTE=r'''
import base64,datetime,hashlib,importlib.util,io,json,os,shutil,sqlite3,subprocess,sys,time,unittest
from pathlib import Path
leader=Path('/opt/gongwei/releases/20261007-120338-maintenance')
web=Path('/opt/gongwei/releases/20261006-211426-maintenance')
assert Path(subprocess.check_output(['systemctl','show','gongwei-leader','-p','WorkingDirectory','--value'],text=True).strip()).resolve()==leader
assert Path(subprocess.check_output(['systemctl','show','gongwei-web','-p','WorkingDirectory','--value'],text=True).strip()).resolve()==web
backup=Path('/opt/gongwei/backups')/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-final-audit');backup.mkdir(mode=0o700)
roles=['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox','amp-heartbeat']
def services():return {r:dict(x.split('=',1) for x in subprocess.check_output(['systemctl','show','gongwei-'+r,'-p','ActiveState','-p','MainPID','-p','UnitFileState'],text=True).splitlines()) for r in roles}
r={'backup':str(backup),'before':services(),'platform_verified':False,'changed_files':[]}
for name,data in payload.items():
 dest=backup/'next'/name;dest.parent.mkdir(exist_ok=True,parents=True);dest.write_bytes(base64.b64decode(data))
os.chdir(leader);sys.path.insert(0,str(leader))
for name in ['plan_continuation','leader_external_flow']:
 spec=importlib.util.spec_from_file_location(name,backup/'next'/(name+'.py'));module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
spec=importlib.util.spec_from_file_location('final_audit_tests',backup/'next/test_homepage_continuation.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
stream=io.StringIO();tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
r['tests']={'count':tests.testsRun,'pass':tests.wasSuccessful(),'output':stream.getvalue()}
if not tests.wasSuccessful():r['pass_result']=False;print(json.dumps(r));sys.exit(0)
with sqlite3.connect('file:/var/lib/gongwei-leader/rpc.sqlite3?mode=ro',uri=True) as db:assert not db.execute('SELECT 1 FROM rpc_tasks WHERE pending_json IS NOT NULL OR cancel_json IS NOT NULL').fetchone(),'Leader has pending work'
for name,path in [('business','/opt/gongwei/shared/data/stage2.db'),('rpc','/var/lib/gongwei-leader/rpc.sqlite3')]:
 with sqlite3.connect('file:'+path+'?mode=ro',uri=True) as source,sqlite3.connect(backup/(name+'.sqlite3')) as destination:source.backup(destination)
 os.chmod(backup/(name+'.sqlite3'),0o600)
changes=[]
try:
 for name in ['plan_continuation.py','leader_external_flow.py','web/app.js','web/index.html']:
  target=(web if name.startswith('web/') else leader)/name
  saved=backup/'before'/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
  stat=target.stat();temporary=target.with_name(target.name+'.audit-tmp');temporary.write_bytes((backup/'next'/name).read_bytes());os.chmod(temporary,stat.st_mode&0o777);os.chown(temporary,stat.st_uid,stat.st_gid);temporary.replace(target)
  changes.append((target,saved));r['changed_files'].append({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
 subprocess.run(['systemctl','restart','gongwei-leader'],check=True,timeout=50)
 for _ in range(40):
  if subprocess.check_output(['systemctl','is-active','gongwei-leader'],text=True).strip()=='active' and subprocess.run(['ss','-ltnH','sport = :18443'],capture_output=True,text=True).stdout.strip():break
  time.sleep(.25)
 else:raise RuntimeError('Leader listener not ready')
 r['after']=services();assert all(v['ActiveState']=='active' for v in r['after'].values());assert all(r['before'][role]['MainPID']==r['after'][role]['MainPID'] for role in roles if role!='leader')
 r['pass_result']=True
except BaseException as error:
 for target,saved in changes:shutil.copy2(saved,target)
 subprocess.run(['systemctl','restart','gongwei-leader'],check=True,timeout=50)
 r.update(pass_result=False,rolled_back=True,error=type(error).__name__+': '+str(error))
print(json.dumps(r,ensure_ascii=False,indent=2))
'''
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-o','ServerAliveInterval=10','-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222']
run=subprocess.run(ssh+['sudo /opt/gongwei/.venv/bin/python -'],input=('payload='+repr(files)+'\n'+REMOTE).encode(),capture_output=True,timeout=110)
if run.returncode:raise RuntimeError(run.stderr.decode(errors='replace'))
result=json.loads(run.stdout)
folder=Path(__file__).parent
(folder/'server-final-audit-tests.log').write_text(result['tests'].pop('output'),encoding='utf-8')
(folder/'final-audit-deployment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
assert result['pass_result']

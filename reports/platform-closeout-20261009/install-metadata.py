import base64,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];FOLDER=Path(__file__).parent
names=['amp_metadata_forwarder.py','amp_heartbeat_forwarder.py','test_amp_metadata_forwarder.py']
payload={name:base64.b64encode((ROOT/name).read_bytes()).decode() for name in names}
payload['unit']=base64.b64encode((ROOT/'deploy/systemd/gongwei-amp-metadata.service.example').read_bytes()).decode()
config={'broker':'wt.ioa.pub:19092','sources':[{'role':role,'aic':aic} for role,aic in [('leader','1.2.156.3088.1.BUPT.JSQB3Y.RN5ERG.1KIZGN.0M45'),('resource-inbox','1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA'),('workorder-inbox','1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF')]]}
REMOTE=r'''
import base64,datetime,io,json,os,shutil,subprocess,sys,time,unittest
from pathlib import Path
folder=Path('/opt/gongwei/tools/amp-metadata');folder.mkdir(parents=True,exist_ok=True)
backup=Path('/opt/gongwei/backups')/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-amp-metadata');backup.mkdir(mode=0o700)
roles=['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox','amp-heartbeat']
def pids():return {r:subprocess.check_output(['systemctl','show','gongwei-'+r,'-p','MainPID','--value'],text=True).strip() for r in roles}
result={'backup':str(backup),'before_pids':pids(),'platform_verified':False}
unit=Path('/etc/systemd/system/gongwei-amp-metadata.service');assert not unit.exists(),'New service already exists; inspect rather than overwrite'
for name in names:
 target=folder/name;target.write_bytes(base64.b64decode(payload[name]));os.chmod(target,0o644)
os.chdir(folder);sys.path.insert(0,str(folder))
import amp_metadata_forwarder as m,aiokafka
assert aiokafka.__version__=='0.12.0'
m.validate_config(config);stream=io.StringIO();tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('test_amp_metadata_forwarder'))
result['tests']={'count':tests.testsRun,'passed':tests.wasSuccessful(),'log':stream.getvalue()}
assert tests.wasSuccessful()
configuration=Path('/etc/gongwei/amp-metadata.json');configuration.parent.mkdir(exist_ok=True)
configuration.write_text(json.dumps(config,indent=2)+'\n');os.chmod(configuration,0o644)
unit.write_bytes(base64.b64decode(payload['unit']));os.chmod(unit,0o644)
try:
 subprocess.run(['systemd-analyze','verify',str(unit)],check=True,capture_output=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 subprocess.run(['systemctl','enable','--now',unit.name],check=True,capture_output=True)
 time.sleep(2)
 result['service']=dict(x.split('=',1) for x in subprocess.check_output(['systemctl','show','gongwei-amp-metadata','-p','ActiveState','-p','SubState','-p','MainPID','-p','UnitFileState'],text=True).splitlines())
 assert result['service']['ActiveState']=='active' and result['service']['SubState']=='running'
 result['after_pids']=pids();assert result['before_pids']==result['after_pids']
 result['pass_result']=True
except BaseException as error:
 subprocess.run(['systemctl','disable','--now',unit.name],capture_output=True)
 result.update(pass_result=False,error_type=type(error).__name__,rollback='Only the new metadata service stopped and disabled; no business service restarted')
print(json.dumps(result,ensure_ascii=False))
'''
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222']
r=subprocess.run(ssh+['sudo /opt/gongwei/.venv/bin/python -'],input=('names='+repr(names)+'\npayload='+repr(payload)+'\nconfig='+repr(config)+'\n'+REMOTE).encode(),capture_output=True,timeout=120)
if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace'))
result=json.loads(r.stdout);(FOLDER/'metadata-server-tests.log').write_text(result['tests'].pop('log'),encoding='utf-8');(FOLDER/'metadata-install.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));assert result['pass_result']

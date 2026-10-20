import subprocess,json,os,stat,datetime,shutil,urllib.request
from pathlib import Path
base=Path('/opt/gongwei');env=base/'gongwei.env';folder=base/'shared/logs/aip'
backup=base/'backups'/('20261008-final-flow-logs-'+datetime.datetime.now().strftime('%H%M%S'));backup.mkdir(mode=0o700)
shutil.copy2(env,backup/'gongwei.env');os.chmod(backup/'gongwei.env',0o600)
original=env.read_text();before={role:subprocess.check_output(['systemctl','show','gongwei-'+role,'-p','MainPID','--value'],text=True).strip() for role in ['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox','amp-heartbeat']}
folder.mkdir(parents=True,exist_ok=True);shutil.chown(folder,'ubuntu','ubuntu');os.chmod(folder,0o750)
lines=[line for line in original.splitlines() if not line.startswith('GONGWEI_LOG_DIR=')];lines.append('GONGWEI_LOG_DIR='+str(folder))
temporary=env.with_name('gongwei.env.final-flow-tmp');temporary.write_text('\n'.join(lines)+'\n');shutil.copystat(env,temporary);st=env.stat();os.chown(temporary,st.st_uid,st.st_gid);temporary.replace(env)
r={'backup':str(backup),'log_directory':str(folder),'before_pids':before,'health':{},'changes':['GONGWEI_LOG_DIR only'],'platform_verified':False}
try:
 for role,port in [('resource',18112),('workorder',18113),('audio',18114),('web',18110)]:
  subprocess.run(['systemctl','restart','gongwei-'+role],check=True)
  import time
  for _ in range(40):
   try:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as res:r['health'][role]=json.loads(res.read());break
   except Exception:time.sleep(.25)
  else:raise RuntimeError('health failed '+role)
 r['success']=True
except Exception as exc:
 shutil.copy2(backup/'gongwei.env',env)
 for role in ['resource','workorder','audio','web']:subprocess.run(['systemctl','restart','gongwei-'+role],check=False)
 r['success']=False;r['error']=type(exc).__name__+': '+str(exc);r['rolled_back']=True
r['after_pids']={role:subprocess.check_output(['systemctl','show','gongwei-'+role,'-p','MainPID','--value'],text=True).strip() for role in before}
print(json.dumps(r,ensure_ascii=False,indent=2))

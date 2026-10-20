"""Hide only the known sensitive backup path; restart only metadata service."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSH = ['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes',
       '-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222']
REMOTE = r'''
import datetime,json,os,shutil,subprocess,time
from pathlib import Path
roles=['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox','amp-heartbeat']
def pid(role):return subprocess.check_output(['systemctl','show','gongwei-'+role,'-p','MainPID','--value'],text=True).strip()
before={r:pid(r) for r in roles}
unit=Path('/etc/systemd/system/gongwei-amp-metadata.service')
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup=Path('/opt/gongwei/backups')/(stamp+'-metadata-hardening')
backup.mkdir(mode=0o700);shutil.copy2(unit,backup/unit.name)
old=unit.read_text();new=old.replace('InaccessiblePaths=-/opt/gongwei/secrets ', 'InaccessiblePaths=-/opt/gongwei/secrets -/opt/gongwei/backups ')
assert new!=old and new.count('-/opt/gongwei/backups')==1
temp=unit.with_suffix('.service.tmp');temp.write_text(new);temp.chmod(0o644);os.replace(temp,unit)
try:
 subprocess.run(['systemd-analyze','verify',str(unit)],capture_output=True,check=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 subprocess.run(['systemctl','restart',unit.name],check=True)
 time.sleep(2)
 assert subprocess.check_output(['systemctl','is-active',unit.name],text=True).strip()=='active'
 after={r:pid(r) for r in roles};assert before==after
 metadata_pid=subprocess.check_output(['systemctl','show',unit.name,'-p','MainPID','--value'],text=True).strip()
 # Inspection checks mount-path visibility, never opens credential contents.
 probe="import json,os;print(json.dumps({'backup_root_visible':os.access('/opt/gongwei/backups',os.R_OK),'credential_backup_visible':os.path.exists('/opt/gongwei/backups/20261009-011144-closeout/leader.env'),'amp_root_visible':os.path.isdir('/var/log/gongwei-leader/amp')}))"
 sandbox=json.loads(subprocess.check_output(['nsenter','-t',metadata_pid,'-m','--','python3','-c',probe],text=True))
 assert not sandbox['credential_backup_visible'] and sandbox['amp_root_visible']
 print(json.dumps({'backup':str(backup),'service':'active','unchanged_other_own_pids':before==after,'sandbox_visibility':sandbox,'inaccessible_paths':subprocess.check_output(['systemctl','show',unit.name,'-p','InaccessiblePaths','--value'],text=True).strip()},ensure_ascii=False))
except Exception:
 shutil.copy2(backup/unit.name,unit);subprocess.run(['systemctl','daemon-reload']);subprocess.run(['systemctl','restart',unit.name]);raise
'''
result=subprocess.run(SSH+['sudo python3 -'],input=REMOTE.encode(),capture_output=True,timeout=45)
result.check_returncode()
data=json.loads(result.stdout)
(Path(__file__).parent/'metadata-hardening.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(data,ensure_ascii=False))

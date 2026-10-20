"""Change only the existing gongwei HTTPS server's upload limit, with rollback."""
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
REMOTE=r'''
import datetime,hashlib,json,shutil,subprocess,urllib.request
from pathlib import Path
target=Path('/etc/nginx/sites-available/gongwei.yanyi.online').resolve()
assert str(target)=='/etc/nginx/sites-available/gongwei.yanyi.online'
def hashes():
 return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/etc/nginx').rglob('*') if p.is_file()}
before=hashes();text=target.read_text();needle='    server_name gongwei.yanyi.online;'
assert text.count(needle)==2 and 'client_max_body_size' not in text
backup=Path('/opt/gongwei/backups')/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-upload-limit');backup.mkdir(mode=0o700)
shutil.copy2(target,backup/'gongwei.yanyi.online.conf')
head,tail=text.rsplit(needle,1)
# JSON encodes the 10 MiB WAV as base64; 15 MiB permits that existing API envelope.
target.write_text(head+needle+'\n    client_max_body_size 15M;'+tail)
try:
 check=subprocess.run(['nginx','-t'],capture_output=True,text=True,check=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)
 after=hashes();changed=[p for p in before if before[p]!=after[p]]
 assert all(Path(p).resolve()==target for p in changed),changed
 with urllib.request.urlopen('https://gongwei.yanyi.online/health',timeout=10) as response:health=json.load(response)
 result={'backup':str(backup),'changed_config_files':changed,'nginx_test':check.stderr,'health':health,'pass_result':health.get('status')=='ok'}
 assert result['pass_result']
except BaseException:
 shutil.copy2(backup/'gongwei.yanyi.online.conf',target)
 subprocess.run(['nginx','-t'],check=True);subprocess.run(['systemctl','reload','nginx'],check=True)
 raise
print(json.dumps(result,ensure_ascii=False,indent=2))
'''
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222']
run=subprocess.run(ssh+['sudo python3 -'],input=REMOTE.encode(),capture_output=True,timeout=40)
if run.returncode:raise RuntimeError(run.stderr.decode(errors='replace'))
result=json.loads(run.stdout)
Path(__file__).with_name('upload-limit-fix.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))

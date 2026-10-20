"""Read metadata and logs only. Private keys and environment secrets are not exported."""
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
REMOTE=r'''
import datetime,json,subprocess,re
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes
result={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'certificates':{},'configuration':{},'logs':{}}
base=Path('/opt/gongwei/secrets/generations/20261007')
for role,stem in [('resource','resource_partner'),('workorder','workorder'),('leader','leader'),('leader-server','leader-server')]:
 folder=base/('leader' if role=='leader-server' else role)
 cert_path=folder/'certs'/(stem+'.crt')
 cert=x509.load_pem_x509_certificate(cert_path.read_bytes())
 result['certificates'][role]={'subject':cert.subject.rfc4514_string(),'issuer':cert.issuer.rfc4514_string(),'sha256':cert.fingerprint(hashes.SHA256()).hex(),'not_before':cert.not_valid_before_utc.isoformat(),'not_after':cert.not_valid_after_utc.isoformat(),'san':[str(x.value) for x in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value],'eku':[x.dotted_string for x in cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value],'permissions':oct(cert_path.stat().st_mode&0o777)}
allowed={'GONGWEI_TRANSPORT_MODE','GONGWEI_PARTNER_RESOLUTION_POLICY','MQ_BROKER_URL','MQ_AUTH_SERVICE_URL','MQ_VHOST','GONGWEI_DISCOVERY_URL','GONGWEI_LOG_DIR','LEADER_IDENTITY_BINDING_ENABLED','GONGWEI_RPC_IDENTITY_BINDING_ENABLED'}
for file in ['/opt/gongwei/gongwei.env','/opt/gongwei/platform/leader.env']:
 result['configuration'][file]={}
 for line in Path(file).read_text().splitlines():
  if '=' in line:
   key,value=line.split('=',1)
   if key in allowed:result['configuration'][file][key]=value
for role in ['leader','resource-inbox','workorder-inbox']:
 text=subprocess.check_output(['journalctl','-u','gongwei-'+role,'--since','2026-10-08 22:00:00','--no-pager'],text=True)
 result['logs'][role]='\n'.join('[credential-bearing diagnostic omitted]' if any(k in line.lower() for k in ['authorization:','password','refresh_token','access_token','-----begin']) else line for line in text.splitlines())
 files=list(Path('/var/log/gongwei-'+role+'/amp').glob('*.jsonl'))
 result[role+'_heartbeat_metadata']=[json.loads(p.read_text().splitlines()[-1]) for p in files if p.stat().st_size]
result['private_file_permissions']=[{'role':role,'path':str(p.relative_to(base)),'mode':oct(p.stat().st_mode&0o777),'uid':p.stat().st_uid,'gid':p.stat().st_gid} for role in ['leader','resource','workorder'] for p in (base/role/'certs/private').glob('*') if p.is_file()]
print(json.dumps(result,ensure_ascii=False,indent=2))
'''
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-o','ServerAliveInterval=10','-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222']
run=subprocess.run(ssh+['sudo /opt/gongwei/.venv/bin/python -'],input=REMOTE.encode(),capture_output=True,timeout=55)
if run.returncode:raise RuntimeError(run.stderr.decode(errors='replace'))
result=json.loads(run.stdout)
folder=Path(__file__).parent
for role,log in result.pop('logs').items():
    (folder/('server-'+role+'.log')).write_text(log,encoding='utf-8')
(folder/'runtime-final.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'roles':list(result['certificates']),'configuration':result['configuration']},ensure_ascii=False))

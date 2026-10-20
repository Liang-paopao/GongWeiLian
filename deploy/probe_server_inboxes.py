"""Start/stop two isolated service processes with real MQ identities, no orders."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import subprocess,json,time,uuid
from pathlib import Path
from datetime import datetime,timezone
base='/opt/gongwei/secrets/generations/20261007'
report={'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'bounded server Inbox processes and official local heartbeat, not AMP network delivery','roles':{}}
run=uuid.uuid4().hex[:6]
try:
 for role,stem in [('resource','resource_partner'),('workorder','workorder')]:
  unit='gongwei-'+role+'-inbox-check-'+run
  credential='/run/credentials/'+unit+'.service/identity_'
  properties={'DynamicUser':'yes','SupplementaryGroups':'gongwei-data','WorkingDirectory':'/opt/gongwei/releases/20261007-platform','LoadCredential':'identity:'+base+'/'+role,'LogsDirectory':unit,'ProtectSystem':'strict','ReadWritePaths':'/opt/gongwei/shared/data','UMask':'0007'}
  # systemd-run --setenv values are literal, unlike Environment= in a unit file.
  env={'GONGWEI_TRANSPORT_MODE':'platform_mq_inbox','GONGWEI_AICS_FILE':credential+'aics.json','MQ_CERT_FILE':credential+'certs_'+stem+'.crt','MQ_KEY_FILE':credential+'certs_private_'+stem+'.key','MQ_CA_FILE':credential+'certs_trust-bundle.pem','MQ_BROKER_URL':'amqps://wt.ioa.pub:5671','MQ_AUTH_SERVICE_URL':'https://wt.ioa.pub:9007','MQ_VHOST':'/acps','GONGWEI_STAGE2_DB':'/opt/gongwei/shared/data/stage2.db','GONGWEI_LOG_DIR':'/var/log/'+unit,'PYTHONUNBUFFERED':'1'}
  args=['systemd-run','--quiet','--collect','--unit='+unit,'--service-type=exec']+['--property='+k+'='+v for k,v in properties.items()]+['--setenv='+k+'='+v for k,v in env.items()]+['/opt/gongwei/.venv/bin/python','run_partner_inbox.py','--role',role]
  subprocess.run(args,text=True,capture_output=True,check=True)
  report['roles'][role]={'unit':unit}
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  ready=True
  for role,row in report['roles'].items():
   logs=Path('/var/log')/row['unit'];log=logs/(role+'_partner_inbox.log')
   text=log.read_text() if log.exists() else ''
   row['inbox_listening']='event=partner_inbox_listening' in text
   row['heartbeats']=[{'file':p.name,'last_record':json.loads(p.read_text().splitlines()[-1])} for p in (logs/'amp').glob('*.jsonl') if p.stat().st_size]
   ready=ready and row['inbox_listening'] and bool(row['heartbeats'])
  if ready:break
  time.sleep(.5)
 for role,row in report['roles'].items():
  p=subprocess.run(['systemctl','show',row['unit'],'-p','MainPID','-p','ActiveState','-p','SubState'],text=True,capture_output=True)
  row['state_before_stop']=p.stdout.splitlines()
 report['pass_result']=all(row['inbox_listening'] and row['heartbeats'] and 'ActiveState=active' in row['state_before_stop'] for row in report['roles'].values())
finally:
 for role,row in report['roles'].items():
  row['stop_exit']=subprocess.run(['systemctl','stop',row['unit']],text=True,capture_output=True).returncode
  row['journal']=subprocess.run(['journalctl','-u',row['unit'],'-n','100','--no-pager'],text=True,capture_output=True).stdout
print(json.dumps(report,ensure_ascii=False,indent=2))
'''


def main():
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
           '-i', str(ROOT.parent / 'gongwei.pem'), 'ubuntu@43.156.60.222']
    result = subprocess.run(ssh + ['sudo python3 -'], input=REMOTE.encode(), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    report = json.loads(result.stdout)
    (ROOT / 'reports/platform-fixes-20261007/server-partner-inbox-final.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'pass': report['pass_result'], 'roles': {k: {
        'listening': v['inbox_listening'], 'heartbeat': bool(v['heartbeats']), 'stop_exit': v['stop_exit']}
        for k, v in report['roles'].items()}}, ensure_ascii=False))
    return 0 if report['pass_result'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

"""Restart only the two project's MQ partners; save public connection evidence."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMOTE = r'''
import datetime,json,sqlite3,subprocess,time
roles=['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox','amp-heartbeat']
def state():
 return {r:dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show','gongwei-'+r,'-p','ActiveState','-p','MainPID','-p','UnitFileState'],text=True).splitlines() if '=' in line) for r in roles}
def database():
 with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
  return {'integrity':db.execute('PRAGMA integrity_check').fetchone()[0], 'orders':db.execute('select count(*) from work_orders').fetchone()[0], 'reservations':[list(x) for x in db.execute('select id,status from reservations order by id')], 'inventory':[list(x) for x in db.execute('select id,available_qty from inventory_items order by id')]}
with sqlite3.connect('file:/var/lib/gongwei-leader/rpc.sqlite3?mode=ro',uri=True) as db:
 assert not db.execute('select 1 from rpc_tasks where pending_json is not null or cancel_json is not null').fetchone(),'Pending Leader work: do not restart partners'
result={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'own two MQ Partner process restart, not shared machine reboot','before':state(),'database_before':database()}
stamp=datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')
for role in ['resource-inbox','workorder-inbox']:
 subprocess.run(['systemctl','restart','gongwei-'+role],check=True)
deadline=time.monotonic()+35
while time.monotonic()<deadline:
 current=state()
 connections=subprocess.check_output(['ss','-ntp'],text=True)
 ready=all(current[r]['ActiveState']=='active' and 'pid='+current[r]['MainPID']+',' in connections and any(':5671' in x and 'pid='+current[r]['MainPID']+',' in x for x in connections.splitlines()) for r in ['resource-inbox','workorder-inbox'])
 if ready:break
 time.sleep(1)
result['after']=state();result['database_after']=database();result['amqps_connections']=[x for x in connections.splitlines() if ':5671' in x and any('pid='+result['after'][r]['MainPID']+',' in x for r in ['leader','resource-inbox','workorder-inbox'])]
result['journals']={r:subprocess.check_output(['journalctl','-u','gongwei-'+r,'--since',stamp,'--no-pager'],text=True) for r in ['resource-inbox','workorder-inbox']}
result['pass_result']=ready and result['database_before']==result['database_after'] and all(result['before'][r]['MainPID']==result['after'][r]['MainPID'] for r in roles if r not in ['resource-inbox','workorder-inbox'])
print(json.dumps(result,ensure_ascii=False,indent=2))
'''

ssh = ['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-o','ServerAliveInterval=10','-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222']
run = subprocess.run(ssh+['sudo python3 -'], input=REMOTE.encode(), capture_output=True, timeout=65)
if run.returncode:
    raise RuntimeError(run.stderr.decode(errors='replace'))
result = json.loads(run.stdout)
Path(__file__).with_name('mq-partner-restart.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pass_result':result['pass_result'],'services':result['after'],'connections':len(result['amqps_connections'])},ensure_ascii=False))
assert result['pass_result']

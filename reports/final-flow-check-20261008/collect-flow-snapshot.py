import subprocess,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
REMOTE=r"""
import sqlite3,json,subprocess,datetime
r={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'services':{}}
for role in ['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox','amp-heartbeat']:
 r['services'][role]=dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show','gongwei-'+role,'-p','ActiveState','-p','MainPID','-p','UnitFileState'],text=True).splitlines() if '=' in line)
with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
 db.row_factory=sqlite3.Row
 r['business']={t:[dict(x) for x in db.execute('SELECT * FROM '+t)] for t in ['work_orders','reservations','inventory_items','agent_tasks','task_subtasks','user_confirmations','task_events']}
 r['integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
 r['counts']={'work_orders':len(r['business']['work_orders']),'active_reservations':sum(x['status']=='active' for x in r['business']['reservations'])}
with sqlite3.connect('file:/var/lib/gongwei-leader/rpc.sqlite3?mode=ro',uri=True) as db:
 db.row_factory=sqlite3.Row
 r['rpc']=[dict(row) for row in db.execute('SELECT task_id,session_id,owner,snapshot_json,pending_json,cancel_json FROM rpc_tasks')]
 r['receipts']=[dict(row) for row in db.execute('SELECT owner,message_id,task_id FROM rpc_receipts')]
print(json.dumps(r,ensure_ascii=False,indent=2))
"""
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222']
r=subprocess.run(ssh+['sudo python3 -'],input=REMOTE.encode(),capture_output=True,timeout=45)
if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace'))
v=json.loads(r.stdout);output=Path(__file__).parent/(sys.argv[1]+'.json');output.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'file':output.name,'counts':v['counts'],'integrity':v['integrity']},ensure_ascii=False))

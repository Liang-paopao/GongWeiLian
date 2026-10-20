"""One authenticated read-only get; prove fresh Kafka ACK after sandbox change."""
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from deploy.probe_public_leader_continue import REMOTE

remote=REMOTE[:REMOTE.index("r['before']=counts()")]+r'''
import subprocess
session='public-continue-28776fa98d93-session'
task='public-continue-28776fa98d93-cancel-operation'
before=counts();result=request(command('get'));after=counts()
log_path=next(Path('/var/log/gongwei-leader/amp').glob('amp_access_*.jsonl'))
record=json.loads(log_path.read_text().splitlines()[-1])
assert record['correlation_id']==task and record['body']['request']['method']=='get'
ack=None
for _ in range(20):
 lines=subprocess.check_output(['journalctl','-u','gongwei-amp-metadata','--since','2026-10-09 04:09:00','--no-pager','-o','cat'],text=True).splitlines()
 for line in lines:
  try:
   item=json.loads(line)
   if item.get('log_id')==record['log_id']:ack=item
  except ValueError:pass
 if ack:break
 time.sleep(.4)
assert ack is not None and before==after and result['status']['state']=='completed'
print(json.dumps({'scope':'read-only GET diagnostic; Resource identity, NOT DingDang',
 'sessionId':session,'taskId':task,'state':result['status']['state'],'business_unchanged':before==after,
 'log_id':record['log_id'],'kafka_ack':ack,'metadata_service':subprocess.check_output(['systemctl','is-active','gongwei-amp-metadata'],text=True).strip()}))
'''
cmd=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes',
     '-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222','sudo /opt/gongwei/.venv/bin/python -']
done=subprocess.run(cmd,input=remote.encode(),capture_output=True,timeout=30)
done.check_returncode()
data=json.loads(done.stdout)
(Path(__file__).parent/'metadata-after-hardening.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
print(json.dumps(data))

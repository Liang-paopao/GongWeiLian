
import asyncio,os,json,sys,sqlite3,uuid,time,logging
from pathlib import Path
release='/opt/gongwei/releases/20261007-095036-maintenance'
sys.path.insert(0,release);sys.path.insert(0,release+'/scripts')
from probe_group_resource import SafeDiagnosticLog
handler=logging.StreamHandler();handler.addFilter(SafeDiagnosticLog());logging.basicConfig(level=logging.INFO,handlers=[handler])
for path in ['/opt/gongwei/gongwei.env','/opt/gongwei/platform/leader.env']:
 for raw in Path(path).read_text().splitlines():
  line=raw.strip()
  if line and not line.startswith('#') and '=' in line:
   key,value=line.split('=',1);os.environ[key]=value.strip().strip('"')
base=Path('/opt/gongwei/secrets/generations/20261007/leader')
os.environ.update(GONGWEI_SECRETS_DIR=str(base),GONGWEI_AICS_FILE=str(base/'aics.json'),GONGWEI_MQ_CA_FILE=str(base/'certs/trust-bundle.pem'),GONGWEI_MQ_CERT_FILE=str(base/'certs/leader.crt'),GONGWEI_MQ_KEY_FILE=str(base/'certs/private/leader.key'))
from platform_runtime_config import configure_platform_environment
configure_platform_environment('leader')
from mq_group_transport import MqBusinessCoordinator
session='mq-rejoin-'+uuid.uuid4().hex
report={'scope':'official MQ diagnostic against running Partners; not DingDang','sessionId':session,'rounds':[],'platform_verified':False}
def counts():
 with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
  return {'orders':db.execute('select count(*) from work_orders').fetchone()[0],'active_reservations':db.execute("select count(*) from reservations where status='active'").fetchone()[0]}
with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
 request_id=db.execute('select request_id from agent_tasks where task_id=?',('4f099dd8-9909-4e70-a078-814a4a4e5548',)).fetchone()[0]
assert request_id
async def main():
 report['before']=counts()
 for index in range(2):
  coordinator=MqBusinessCoordinator();started=time.perf_counter()
  try:
   result=await asyncio.wait_for(coordinator.call('resource','query_resources',{'request_id':request_id,'parent_task_id':session},session_id=session,task_id=session+':resource:'+str(index)),55)
   report['rounds'].append({'round':index+1,'duration_ms':round((time.perf_counter()-started)*1000,2),'result':result})
  finally:
   await asyncio.wait_for(coordinator.close(),20)
 report['after']=counts();report['pass_result']=all(x['result'].get('ok') for x in report['rounds']) and report['before']==report['after']
try:asyncio.run(main())
except Exception as exc:report.update(pass_result=False,error_type=type(exc).__name__,error=str(exc))
print(json.dumps(report,ensure_ascii=False))

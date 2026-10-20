"""Verify real public mTLS start/continue/cancel without requesting a work order.

The caller is the resource test identity, NOT DingDang. Intentionally withhold
duration so the real business flow stays at awaiting-input with no reservation.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import json,ssl,socket,http.client,uuid,time,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from acps_sdk.aip import TaskCommand,TaskCommandType,TextDataItem
from acps_sdk.aip.aip_rpc_model import RpcRequest,RpcRequestParams
base=Path('/opt/gongwei/secrets/generations/20261007/resource')
ids=json.loads((base/'aics.json').read_text())
caller=ids['工维联资源协调 Partner']['aic']
ctx=ssl.create_default_context(cafile=str(base/'certs/trust-bundle.pem'))
ctx.load_cert_chain(str(base/'certs/resource_partner.crt'),str(base/'certs/private/resource_partner.key'))
prefix='public-continue-'+uuid.uuid4().hex[:12]
session=prefix+'-session';task=prefix+'-task'
r={'checked_at':datetime.now(timezone.utc).isoformat(),'endpoint':'https://leader.yanyi.online/rpc','caller':caller,'scope':'official SDK commands to public mTLS endpoint; not DingDang','sessionId':session,'taskId':task,'platform_verified':False,'requests':[]}
def command(kind,text=''):
 return TaskCommand(id=prefix+'-'+uuid.uuid4().hex[:8],sentAt=datetime.now(timezone.utc).isoformat(),senderRole='leader',senderId=caller,sessionId=session,taskId=task,command=TaskCommandType(kind),dataItems=[TextDataItem(text=text)] if text else [])
def request(cmd):
 body=RpcRequest(id=cmd.id,params=RpcRequestParams(command=cmd)).model_dump_json().encode()
 started=time.perf_counter()
 with socket.create_connection(('leader.yanyi.online',443),timeout=10) as raw:
  with ctx.wrap_socket(raw,server_hostname='leader.yanyi.online') as sock:
   sock.sendall(b'POST /rpc HTTP/1.1\r\nHost: leader.yanyi.online\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
   response=http.client.HTTPResponse(sock);response.begin();data=json.loads(response.read())
   r['requests'].append({'command':cmd.command.value,'messageId':cmd.id,'http_status':response.status,'elapsed_ms':round((time.perf_counter()-started)*1000,3),'response':data})
   if response.status!=200 or data.get('error'):raise RuntimeError('RPC rejected '+cmd.command.value)
   return data['result']
def settled(cmd):
 result=request(cmd)
 for _ in range(30):
  if result['status']['state'] not in ['accepted','working']:return result
  time.sleep(.1);result=request(command('get'))
 raise TimeoutError('RPC state did not settle')
def counts():
 with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
  return {'orders':db.execute('SELECT count(*) FROM work_orders').fetchone()[0],'active_reservations':db.execute("SELECT count(*) FROM reservations WHERE status='active'").fetchone()[0],'integrity':db.execute('PRAGMA integrity_check').fetchone()[0]}
r['before']=counts()
started=False
try:
 started=True
 r['first']=settled(command('start','水泵001运行异常，帮我安排明天下午检查。'))
 if r['first']['status']['state']!='awaiting-input':raise RuntimeError('First round did not request missing input')
 r['second']=settled(command('continue','下午两点开始。'))
 r['same_session_and_task']=all(x['sessionId']==session and x['taskId']==task for x in [r['first'],r['second']])
 r['commands']=[x['command'] for x in r['second']['commandHistory']]
 r['question_before']=[x.get('text','') for x in r['first']['status']['dataItems']]
 r['question_after']=[x.get('text','') for x in r['second']['status']['dataItems']]
except Exception as exc:r['error']={'type':type(exc).__name__,'message':str(exc)}
finally:
 if started:
  try:r['cancel']=settled(command('cancel'))
  except Exception as exc:r['cleanup_error']={'type':type(exc).__name__,'message':str(exc)}
r['after']=counts()
r['pass_result']=(not r.get('error') and not r.get('cleanup_error') and r.get('same_session_and_task') is True and r.get('commands')==['start','continue'] and r['second']['status']['state']=='awaiting-input' and r['question_before']!=r['question_after'] and r['cancel']['status']['state']=='canceled' and r['before']==r['after'])
print(json.dumps(r,ensure_ascii=False,indent=2))
'''


def main():
    command = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "IdentitiesOnly=yes",
               "-i", str(ROOT.parent / "gongwei.pem"), "ubuntu@43.156.60.222",
               "sudo /opt/gongwei/.venv/bin/python -"]
    completed = subprocess.run(command, input=REMOTE.encode(), capture_output=True, timeout=55)
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode(errors="replace"))
    report = json.loads(completed.stdout)
    output = ROOT / "reports/platform-card-recheck-20261007"
    output.mkdir(parents=True, exist_ok=True)
    (output / "public-leader-continue.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["pass_result", "sessionId", "taskId", "before", "after"]} |
                     {k: report[k] for k in ["commands", "question_before", "question_after", "error", "cleanup_error"] if k in report}, ensure_ascii=False))
    return 0 if report["pass_result"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

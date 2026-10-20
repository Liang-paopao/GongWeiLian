"""Actual server-local mTLS RPC checks; never labelled as DingDang calls."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import sys,ssl,socket,json,http.client,time,uuid,sqlite3,subprocess
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,'/opt/gongwei/releases/20261007-platform')
from acps_sdk.aip import TaskCommand,TaskCommandType,TextDataItem
from acps_sdk.aip.aip_rpc_model import RpcRequest,RpcRequestParams
base=Path('/opt/gongwei/secrets/generations/20261007')
ids=json.loads((base/'leader/aics.json').read_text())
leader=ids['工维联核心业务 Leader']['aic']; resource=ids['工维联资源协调 Partner']['aic']
report={'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'server loopback real mTLS; not public DingDang','platform_verified':False}
def context(role='resource',cert=True):
 p=base/role; c=ssl.create_default_context(cafile=str(p/'certs/trust-bundle.pem'))
 if cert:
  stem={'resource':'resource_partner','leader':'leader-server'}[role]
  c.load_cert_chain(str(p/f'certs/{stem}.crt'),str(p/f'certs/private/{stem}.key'))
 return c
def request(command,ctx=None):
 body=RpcRequest(id=command.id,params=RpcRequestParams(command=command)).model_dump_json().encode()
 with socket.create_connection(('127.0.0.1',18443),timeout=10) as raw:
  with (ctx or context()).wrap_socket(raw,server_hostname='leader.yanyi.online') as sock:
   sock.sendall(b'POST /rpc HTTP/1.1\r\nHost: leader.yanyi.online\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
   response=http.client.HTTPResponse(sock); response.begin()
   return {'http_status':response.status,'body':json.loads(response.read())}
prefix='server-mtls-'+uuid.uuid4().hex[:10]; task=prefix+'-task'; session=prefix+'-session'
def command(kind,text='',sender=resource):
 return TaskCommand(id=prefix+'-'+uuid.uuid4().hex[:6],sentAt=datetime.now(timezone.utc).isoformat(),senderRole='leader',senderId=sender,sessionId=session,taskId=task,command=TaskCommandType(kind),dataItems=[TextDataItem(text=text)] if text else [])
def counts():
 with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
  return {'orders':db.execute('select count(*) from work_orders').fetchone()[0],'active_reservations':db.execute("select count(*) from reservations where status='active'").fetchone()[0],'integrity':db.execute('pragma integrity_check').fetchone()[0]}
report['before']=counts()
try:
 report['valid_start']=request(command('start','水泵001运行异常，帮我安排明天下午检查。'))
 for _ in range(10):
  report['valid_get']=request(command('get'))
  if report['valid_get']['body'].get('result',{}).get('status',{}).get('state') not in ['accepted','working']:break
  time.sleep(.2)
 report['wrong_sender']=request(command('get',sender=leader))
 for name,ctx in [('no_certificate',context(cert=False)),('wrong_eku',context('leader'))]:
  try:report[name]={'unexpected_response':request(command('get'),ctx)}
  except Exception as exc:report[name]={'rejected':True,'error_type':type(exc).__name__,'error':str(exc)}
finally:
 report['cancel']=request(command('cancel'))
report['after']=counts()
try:
 ctx=ssl.create_default_context(); ctx.load_verify_locations(cafile=str(base/'resource/certs/trust-bundle.pem')); ctx.load_cert_chain(str(base/'resource/certs/resource_partner.crt'),str(base/'resource/certs/private/resource_partner.key'))
 with socket.create_connection(('wt.ioa.pub',19092),timeout=12) as raw:
  with ctx.wrap_socket(raw,server_hostname='wt.ioa.pub') as sock:report['amp_external_tls']={'pass':True,'version':sock.version()}
except Exception as exc:report['amp_external_tls']={'pass':False,'client_certificate':'resource clientAuth','error_type':type(exc).__name__,'error':str(exc)}
report['services']={}
for role in ['web','resource','workorder','audio','leader']:
 p=subprocess.run(['systemctl','show','gongwei-'+role,'-p','ActiveState','-p','SubState','-p','MainPID','-p','UnitFileState'],text=True,capture_output=True)
 report['services'][role]=dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)
report['heartbeat_files']=[{'name':p.name,'last_record':json.loads(p.read_text().splitlines()[-1])} for p in Path('/var/log/gongwei-leader/amp').glob('*.jsonl') if p.stat().st_size]
report['pass_result']=(report['valid_get']['body'].get('result',{}).get('status',{}).get('state')=='awaiting-input'
 and report['wrong_sender']['body'].get('error') is not None
 and report['no_certificate'].get('rejected',False) and report['wrong_eku'].get('rejected',False)
 and report['before']==report['after'])
print(json.dumps(report,ensure_ascii=False,indent=2))
'''


def main():
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
           '-i', str(ROOT.parent / 'gongwei.pem'), 'ubuntu@43.156.60.222']
    result = subprocess.run(ssh + ['sudo /opt/gongwei/.venv/bin/python -'], input=REMOTE.encode(), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    report = json.loads(result.stdout)
    (ROOT / 'reports/platform-fixes-20261007/server-leader-mtls.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'pass_result': report['pass_result'], 'state': report['valid_get']['body'].get('result',{}).get('status'),
                      'amp_tls': report['amp_external_tls'], 'database_before': report['before'], 'database_after': report['after']}, ensure_ascii=False))
    return 0 if report['pass_result'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

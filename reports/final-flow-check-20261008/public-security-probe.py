
import ssl,socket,http.client,json,uuid,time,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from acps_sdk.aip import TaskCommand,TaskCommandType
from acps_sdk.aip.aip_rpc_model import RpcRequest,RpcRequestParams
base=Path('/opt/gongwei/secrets/generations/20261007');ids=json.loads((base/'leader/aics.json').read_text());resource=ids['工维联资源协调 Partner']['aic'];leader=ids['工维联核心业务 Leader']['aic']
def context(role='resource',cert=True):
 p=base/role;c=ssl.create_default_context(cafile=str(p/'certs/trust-bundle.pem'))
 if cert:
  stem={'resource':'resource_partner','leader':'leader-server'}[role];c.load_cert_chain(str(p/f'certs/{stem}.crt'),str(p/f'certs/private/{stem}.key'))
 return c
prefix='security-'+uuid.uuid4().hex
r={'checked_at':datetime.now(timezone.utc).isoformat(),'endpoint':'https://leader.yanyi.online/rpc','scope':'public mTLS identity rejection, no business mutation','tests':{}}
for name,ctx,sender in [('valid_identity',context(),resource),('wrong_sender',context(),leader),('no_certificate',context(cert=False),resource),('wrong_eku',context('leader'),resource)]:
 cmd=TaskCommand(id=prefix+'-'+name,sentAt=datetime.now(timezone.utc).isoformat(),senderRole='leader',senderId=sender,sessionId=prefix,taskId=prefix,command=TaskCommandType.Get)
 body=RpcRequest(id=cmd.id,params=RpcRequestParams(command=cmd)).model_dump_json().encode();start=time.perf_counter()
 try:
  with socket.create_connection(('leader.yanyi.online',443),timeout=8) as raw:
   with ctx.wrap_socket(raw,server_hostname='leader.yanyi.online') as sock:
    sock.settimeout(8);sock.sendall(b'POST /rpc HTTP/1.1\r\nHost: leader.yanyi.online\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
    response=http.client.HTTPResponse(sock);response.begin();data=json.loads(response.read());r['tests'][name]={'http_status':response.status,'body':data,'elapsed_ms':round((time.perf_counter()-start)*1000,3)}
 except Exception as e:r['tests'][name]={'error_type':type(e).__name__,'error':str(e),'elapsed_ms':round((time.perf_counter()-start)*1000,3)}
print(json.dumps(r,ensure_ascii=False,indent=2))

"""Approved one-time SNI cutover with five-site checks and routing rollback.

Requires the stream module to be installed separately. Does not install
packages or touch application code/data. Originals stay in a server backup.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import ssl,socket,http.client,json,hashlib,subprocess,shutil,re,time
from pathlib import Path
from datetime import datetime,timezone
domains=['app.yanyi.online','gongwei.yanyi.online','taluo.yanyi.online','www.yanyi.online','xiaoyi.yanyi.online']
def probe(domain,context=None):
 with socket.create_connection(('127.0.0.1',443),timeout=12) as raw:
  with (context or ssl.create_default_context()).wrap_socket(raw,server_hostname=domain) as sock:
   digest=hashlib.sha256(sock.getpeercert(binary_form=True)).hexdigest()
   sock.sendall(('GET / HTTP/1.1\r\nHost: '+domain+'\r\nConnection: close\r\n\r\n').encode())
   response=http.client.HTTPResponse(sock);response.begin();response.read()
   return {'http_status':response.status,'location':response.getheader('Location'),'certificate_sha256':digest}
def command(args):
 result=subprocess.run(args,text=True,capture_output=True)
 if result.returncode:raise RuntimeError(result.stderr or result.stdout)
 return result.stdout+result.stderr
report={'checked_at':datetime.now(timezone.utc).isoformat(),'before':{d:probe(d) for d in domains},'platform_verified':False}
root=Path('/etc/nginx');stream=root/'gongwei-stream.conf';main=root/'nginx.conf'
fastcgi=root/'gongwei-fastcgi.conf';php_snippet=root/'gongwei-fastcgi-php.conf'
created=[stream,fastcgi,php_snippet]
assert not any(p.exists() for p in created),'SNI already staged: do not overwrite without a new baseline'
assert Path('/usr/lib/nginx/modules/ngx_stream_module.so').is_file()
backup=Path('/opt/gongwei/backups')/('sni-cutover-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir(mode=0o700);shutil.copytree(root,backup/'nginx',symlinks=True)
report['backup']=str(backup)
originals={main:main.read_bytes()}; replacements={}
for domain in domains:
 p=(root/'sites-enabled'/domain).resolve()
 assert p.is_relative_to(root/'sites-available')
 text=p.read_text();originals[p]=p.read_bytes()
 assert len(re.findall(r'listen 443 ssl;',text))==1,domain
 assert len(re.findall(r'listen \[::\]:443 ssl(?: ipv6only=on)?;',text))==1,domain
 text=text.replace('listen 443 ssl;','listen 127.0.0.1:1443 ssl proxy_protocol;\n    set_real_ip_from 127.0.0.1;\n    set_real_ip_from ::1;\n    real_ip_header proxy_protocol;\n    port_in_redirect off;')
 text=text.replace('listen [::]:443 ssl','listen [::1]:1443 ssl proxy_protocol')
 if domain=='xiaoyi.yanyi.online':
  assert text.count('include snippets/fastcgi-php.conf;')==1
  text=text.replace('include snippets/fastcgi-php.conf;','include /etc/nginx/gongwei-fastcgi-php.conf;')
 replacements[p]=text
replacements[main]=main.read_text()+'\n# Authorized Gongwei end-to-end mTLS SNI routing\ninclude /etc/nginx/gongwei-stream.conf;\n'
replacements[stream]=__STREAM_CONTENT__
# Preserve the original public port/address passed to PHP. Only the HTTPS
# site's copied snippet changes; the global FastCGI configuration is retained.
fastcgi_text=(root/'fastcgi.conf').read_text()
assert '$server_addr' in fastcgi_text and '$server_port' in fastcgi_text
replacements[fastcgi]=fastcgi_text.replace('$server_addr','$proxy_protocol_server_addr').replace('$server_port','$proxy_protocol_server_port')
snippet_text=(root/'snippets/fastcgi-php.conf').read_text()
assert snippet_text.count('include fastcgi.conf;')==1
replacements[php_snippet]=snippet_text.replace('include fastcgi.conf;','include /etc/nginx/gongwei-fastcgi.conf;')
try:
 for path,text in replacements.items():path.write_text(text)
 report['nginx_test']=command(['nginx','-t'])
 report['reload']=command(['systemctl','reload','nginx'])
 time.sleep(.8)
 report['after']={d:probe(d) for d in domains}
 assert report['after']==report['before'],'Existing site response/certificate changed'
 identity=Path('/opt/gongwei/secrets/generations/20261007/resource')
 ctx=ssl.create_default_context(cafile=str(identity/'certs/trust-bundle.pem'))
 ctx.load_cert_chain(str(identity/'certs/resource_partner.crt'),str(identity/'certs/private/resource_partner.key'))
 report['leader_tls']=probe('leader.yanyi.online',ctx)
 assert report['leader_tls']['http_status']==404,'Leader TLS must reach the dedicated runtime'
 report['pass_result']=True
except BaseException as exc:
 for path,data in originals.items():path.write_bytes(data)
 for path in created:
  if path.exists():path.unlink()
 report['rollback_test']=command(['nginx','-t'])
 report['rollback_reload']=command(['systemctl','reload','nginx'])
 time.sleep(.8)
 report['restored']={d:probe(d) for d in domains}
 report.update(pass_result=False,error=str(exc),rollback_verified=report['restored']==report['before'])
(backup/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
'''


def main():
    stream = (ROOT / 'deploy/nginx/leader-sni-stream.conf.example').read_text(encoding='utf-8')
    script = REMOTE.replace('__STREAM_CONTENT__', repr(stream))
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
           '-i', str(ROOT.parent / 'gongwei.pem'), 'ubuntu@43.156.60.222']
    result = subprocess.run(ssh + ['sudo python3 -'], input=script.encode(), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    report = json.loads(result.stdout)
    (ROOT / 'reports/platform-fixes-20261007/sni-cutover.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['pass_result'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

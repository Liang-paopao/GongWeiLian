"""Read-only server report, except for an isolated temporary test database."""
import json
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
       '-i', str(ROOT.parent / 'gongwei.pem'), 'ubuntu@43.156.60.222']

REMOTE = '''import os,json,socket,sqlite3,subprocess,ssl,tempfile,sys
from pathlib import Path
from datetime import datetime,timezone
report={'checked_at':datetime.now(timezone.utc).isoformat(),'platform_verified':False}
report['leader_dns']=sorted({x[4][0] for x in socket.getaddrinfo('leader.yanyi.online',443,family=socket.AF_INET)})
report['live_release']=str(Path('/opt/gongwei/current').resolve())
report['services']={}
for role in ['web','resource','workorder','audio','leader']:
 proc=subprocess.run(['systemctl','show','gongwei-'+role,'-p','LoadState','-p','ActiveState','-p','UnitFileState'],capture_output=True,text=True)
 report['services'][role]=dict(line.split('=',1) for line in proc.stdout.splitlines() if '=' in line)
proc=subprocess.run(['sha256sum','-c','/opt/gongwei/backups/pre-platform-20261006T184217/baseline-sha256.txt'],capture_output=True,text=True)
report['original_nginx_and_units_unchanged']=proc.returncode==0
report['configuration_hash_check']=proc.stdout.splitlines()
with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
 report['database_integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
 report['work_orders']=db.execute('SELECT count(*) FROM work_orders').fetchone()[0]
 report['active_reservations']=db.execute("SELECT count(*) FROM reservations WHERE status='active'").fetchone()[0]
sys.path.insert(0,'/opt/gongwei/current')
from partner_resolver import PartnerResolver
with tempfile.TemporaryDirectory() as directory:
 resolver=PartnerResolver(db_path=Path(directory)/'test.db')
 report['restored_local_catalog']={kind:bool(resolver.resolve(kind,[skill])['selected']) for kind,skill in [('resource','gongwei.resource.query'),('workorder','gongwei.work-order.create')]}
import urllib.request
with urllib.request.urlopen('https://gongwei.yanyi.online/health',timeout=15) as response:
 health=json.load(response)
 report['web_health']={key:health.get(key) for key in ['status','transport_mode','platform_verified']}
sys.path.insert(0,'/opt/gongwei/releases/20261006-hybrid')
os.environ.update(GONGWEI_TRANSPORT_MODE='platform_mq_inbox',GONGWEI_SECRETS_DIR='/opt/gongwei/secrets/leader')
from run_leader_rpc import build_server_config
try:
 build_server_config()
 report['leader_startup_preflight']='PASS'
except Exception as exc:
 report['leader_startup_preflight']='BLOCKED'
 report['leader_startup_reason']=str(exc)
print(json.dumps(report,ensure_ascii=False,indent=2))
'''


def main():
    result = subprocess.run(SSH + ['sudo /opt/gongwei/.venv/bin/python -c ' + shlex.quote(REMOTE)], capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
    report = json.loads(result.stdout)
    (ROOT/'reports/hybrid-platform-20261006/server-final-state.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()

"""Install only the isolated Gongwei heartbeat sidecar on the authorized host.

Requires the already prepared amp-diagnostics venv. Refuses to overwrite an
existing unit or config; does not restart any of the seven business services.
"""
import base64
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/platform-followup-20261007"
SOURCES = [
    ("leader", "1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9",
     "amp_heartbeat_leader_rpc_037c95c89c455cb413c4b755b9446c4f1f94e6f764ac6a268e32f3cb1c850595.jsonl"),
    ("resource-inbox", "1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA",
     "amp_heartbeat_resource_21586e25f00f8f61999a9424c0a78dc39b6c235fda0789691e98552063b0a836.jsonl"),
    ("workorder-inbox", "1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF",
     "amp_heartbeat_workorder_3ee6b3c24a2a0bfe804a70bd28f98cd5b1988f01c56be2ceef6d7b4da5357f2b.jsonl"),
]

REMOTE = r'''
import base64,hashlib,json,os,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
unit=Path('/etc/systemd/system/gongwei-amp-heartbeat.service')
config=Path('/etc/gongwei/amp-heartbeat.json')
root=Path('/opt/gongwei/tools/amp-diagnostics')
if unit.exists() or config.exists():
 raise RuntimeError('Existing heartbeat service/config; refuse overwrite')
if not (root/'venv/bin/python').exists():
 raise RuntimeError('Isolated dependency runtime is absent')
def run(args):
 p=subprocess.run(args,text=True,capture_output=True)
 if p.returncode: raise RuntimeError(p.stderr or p.stdout)
 return p.stdout.strip()
roles=['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox']
before={r:run(['systemctl','show','gongwei-'+r,'-p','MainPID','--value']) for r in roles}
if any(not value.isdigit() or int(value)<=0 for value in before.values()):
 raise RuntimeError('A required existing business service has no live PID')
for role in roles:run(['systemctl','is-active','--quiet','gongwei-'+role])
backup=Path('/opt/gongwei/backups')/('amp-sidecar-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir(mode=0o700)
(backup/'preflight.json').write_text(json.dumps({'unit_preexisting':False,'config_preexisting':False,'business_pids':before},indent=2))
os.chmod(backup/'preflight.json',0o600)
config.parent.mkdir(mode=0o755,exist_ok=True)
files={'amp_heartbeat_forwarder.py':root/'amp_heartbeat_forwarder.py',
       'test_amp_heartbeat_forwarder.py':root/'test_amp_heartbeat_forwarder.py',
       'unit':unit,'config':config}
hashes={}
for name,path in files.items():
 data=base64.b64decode(payload[name])
 if path.exists():
  (backup/path.name).write_bytes(path.read_bytes())
  os.chmod(backup/path.name,0o600)
 path.write_bytes(data)
 os.chmod(path,0o600 if name=='config' else 0o644)
 hashes[str(path)]=hashlib.sha256(data).hexdigest()
result={'checked_at':datetime.now(timezone.utc).isoformat(),'backup':str(backup),'files_sha256':hashes,'before_business_pids':before}
try:
 run(['systemd-analyze','verify',str(unit)])
 run(['systemctl','daemon-reload'])
 run(['systemctl','enable','--now','gongwei-amp-heartbeat.service'])
 for check in range(3):
  time.sleep(1)
  state=run(['systemctl','show','gongwei-amp-heartbeat','-p','ActiveState','-p','SubState','-p','MainPID','-p','UnitFileState'])
  status=dict(line.split('=',1) for line in state.splitlines())
  if status.get('ActiveState')!='active' or status.get('SubState')!='running' or int(status.get('MainPID','0'))<=0:
   raise RuntimeError('New heartbeat service did not remain active/running')
  result['status']=status
 result['after_business_pids']={r:run(['systemctl','show','gongwei-'+r,'-p','MainPID','--value']) for r in roles}
 result['business_pids_unchanged']=result['after_business_pids']==before
 if not result['business_pids_unchanged']:raise RuntimeError('Business process PID changed during sidecar install')
except Exception as exc:
 subprocess.run(['systemctl','disable','--now','gongwei-amp-heartbeat.service'],capture_output=True)
 result['error']=str(exc)
 result['rollback']='Only new heartbeat unit stopped/disabled; diagnostic files retained'
print(json.dumps(result,indent=2))
'''


def main():
    config = {"broker": "wt.ioa.pub:19092", "sources": [
        {"role": role, "aic": aic, "log_path": f"/var/log/gongwei-{role}/amp/{filename}"}
        for role, aic, filename in SOURCES]}
    payload = {name: base64.b64encode((ROOT / name).read_bytes()).decode()
               for name in ("amp_heartbeat_forwarder.py", "test_amp_heartbeat_forwarder.py")}
    payload["unit"] = base64.b64encode((ROOT / "deploy/systemd/gongwei-amp-heartbeat.service.example").read_bytes()).decode()
    payload["config"] = base64.b64encode((json.dumps(config, indent=2) + "\n").encode()).decode()
    command = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "IdentitiesOnly=yes",
               "-i", str(ROOT.parent / "gongwei.pem"), "ubuntu@43.156.60.222", "sudo python3 -"]
    completed = subprocess.run(command, input=("payload=" + repr(payload) + "\n" + REMOTE).encode(),
                               capture_output=True, timeout=45)
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode(errors="replace"))
    report = json.loads(completed.stdout)
    REPORT.mkdir(exist_ok=True, parents=True)
    (REPORT / "amp-service-install.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())

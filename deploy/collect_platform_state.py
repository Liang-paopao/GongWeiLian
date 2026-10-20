"""Read-only service/database evidence. Never read credential contents."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import sqlite3,json,subprocess
from pathlib import Path
from datetime import datetime,timezone
result={'checked_at':datetime.now(timezone.utc).isoformat(),'platform_verified':False,'services':{},'rpc_tasks':[]}
for role in ['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox']:
 process=subprocess.run(['systemctl','show','gongwei-'+role,'-p','ActiveState','-p','MainPID','-p','UnitFileState'],text=True,capture_output=True)
 result['services'][role]=dict(line.split('=',1) for line in process.stdout.splitlines() if '=' in line)
with sqlite3.connect('file:/var/lib/gongwei-leader/rpc.sqlite3?mode=ro',uri=True) as db:
 db.row_factory=sqlite3.Row
 for row in db.execute('SELECT task_id,session_id,owner,snapshot_json FROM rpc_tasks'):
  task=dict(row);task['snapshot']=json.loads(task.pop('snapshot_json'))
  task['receipts']=[dict(r) for r in db.execute('SELECT message_id,task_id FROM rpc_receipts WHERE task_id=?',(task['task_id'],))]
  result['rpc_tasks'].append(task)
with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
 result['database']={'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'work_orders':db.execute('SELECT count(*) FROM work_orders').fetchone()[0],'active_reservations':db.execute("SELECT count(*) FROM reservations WHERE status='active'").fetchone()[0]}
for role in ['leader','resource-inbox','workorder-inbox']:
 text=subprocess.run(['journalctl','-u','gongwei-'+role,'--since','2026-10-07 00:43:00','-n','500','--no-pager'],text=True,capture_output=True).stdout
 result[role+'_journal']='\n'.join('[credential-bearing diagnostic omitted]' if any(word in line.lower() for word in ['authorization:','password','refresh_token','access_token','-----begin']) else line for line in text.splitlines())
result['heartbeat_metadata']={role:[json.loads(p.read_text().splitlines()[-1]) for p in Path('/var/log/gongwei-'+role+'/amp').glob('*.jsonl') if p.stat().st_size] for role in ['leader','resource-inbox','workorder-inbox']}
print(json.dumps(result,ensure_ascii=False,indent=2))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'reports/platform-fixes-20261007')
    args = parser.parse_args()
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
           '-i', str(ROOT.parent / 'gongwei.pem'), 'ubuntu@43.156.60.222']
    result = subprocess.run(ssh + ['sudo python3 -'], input=REMOTE.encode(), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    report = json.loads(result.stdout)
    folder = args.output_dir
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'server-final-state.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for role in ['leader', 'resource-inbox', 'workorder-inbox']:
        (folder / f'server-{role}.log').write_text(report[role + '_journal'], encoding='utf-8')
    print(json.dumps({'services': report['services'], 'database': report['database'], 'tasks': [
        {'sessionId': t['session_id'], 'taskId': t['task_id'], 'owner': t['owner'],
         'state': t['snapshot']['status']['state'], 'commands': [c['command'] for c in t['snapshot']['commandHistory']]}
        for t in report['rpc_tasks']]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

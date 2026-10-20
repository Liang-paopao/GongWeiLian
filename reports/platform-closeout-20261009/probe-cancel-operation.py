"""Real public SDK cancel/start compatibility; this client is NOT DingDang."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from deploy.probe_public_leader_continue import REMOTE

remote = REMOTE.replace('range(30)', 'range(250)').replace('time.sleep(.1)', 'time.sleep(.2)')
start, end = remote.index('started=False'), remote.index('print(json.dumps(r,ensure_ascii=False,indent=2))')
remote = remote[:start] + r'''
r['scope']='official SDK cancel/start compatibility on real public mTLS+MQ; NOT a browser DingDang conversation'
r['before']=counts()
original_task=task
started=False
try:
 started=True
 r['proposal']=settled(command('start','水泵001运行异常，明天下午两点开始，预计一小时，需要泵体检查技能。'))
 assert r['proposal']['status']['state']=='awaiting-input'
 proposed=json.loads(r['proposal']['products'][0]['dataItems'][0]['text'])
 r['confirmation_reference']=proposed['confirmationReference']
 with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
  previous=db.execute('SELECT content FROM agent_messages WHERE task_id=? AND role=? ORDER BY created_at DESC LIMIT 1',(task,'user')).fetchone()[0]
 r['routing_cancel']=settled(command('cancel'))
 assert r['routing_cancel']['status']['state']=='canceled'
 task=prefix+'-cancel-operation'
 wrapped=previous+'\n\n上一轮候选结果：方案\n叮当请求补充：请选择\n用户回答：取消任务'
 r['cancel_operation']=settled(command('start',wrapped))
 final=json.loads(r['cancel_operation']['products'][0]['dataItems'][0]['text'])
 r['business_cancellation']=final
 assert r['cancel_operation']['status']['state']=='completed'
 assert final['status']=='cancelled' and final['operation']=='cancel_plan'
 assert final['cancellationContinuation']['source_task_id']==original_task
 with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
  r['actual_plan_state']=db.execute('SELECT status FROM plans WHERE id=?',(final['cancellationContinuation']['plan_id'],)).fetchone()[0]
 assert r['actual_plan_state']=='cancelled'
 task=prefix+'-cancel-duplicate'
 r['duplicate_operation']=settled(command('start',wrapped))
 assert r['duplicate_operation']['status']['state']=='failed'
 assert '已经取消' in r['duplicate_operation']['status']['dataItems'][0]['text']
except Exception as exc:
 r['error']={'type':type(exc).__name__,'message':str(exc)}
finally:
 if started and r.get('error'):
  task=original_task
  try:r['cleanup']=settled(command('cancel'))
  except Exception as exc:r['cleanup_error']={'type':type(exc).__name__,'message':str(exc)}
r['after']=counts()
r['pass_result']=not r.get('error') and not r.get('cleanup_error') and r['before']==r['after'] and r.get('actual_plan_state')=='cancelled'
''' + remote[end:]

ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o',
       'IdentitiesOnly=yes', '-i', str(ROOT.parent / 'gongwei.pem'),
       'ubuntu@43.156.60.222', 'sudo /opt/gongwei/.venv/bin/python -']
completed = subprocess.run(ssh, input=remote.encode(), capture_output=True, timeout=150)
completed.check_returncode()
result = json.loads(completed.stdout)
Path(__file__).with_name('public-cancel-operation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: result.get(k) for k in ['scope', 'pass_result', 'actual_plan_state', 'before', 'after', 'error', 'cleanup_error']}, ensure_ascii=False))
assert result['pass_result']

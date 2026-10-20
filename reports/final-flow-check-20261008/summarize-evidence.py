"""Derive the ID table and response timings from recorded protocol snapshots."""
import csv,datetime,json,re
from pathlib import Path
FOLDER=Path(__file__).parent
v=json.loads((FOLDER/'final-state.json').read_text(encoding='utf-8'))
rows=[];timings=[];sessions={'session_1822','session_1825'}
for row in v['rpc']:
 if row['session_id'] not in sessions:continue
 s=json.loads(row['snapshot_json']);history=s['statusHistory'];commands=s['commandHistory']
 first=next((h for h in history if h['state'] not in {'accepted','working'}),None)
 elapsed=round((datetime.datetime.fromisoformat(first['stateChangedAt'])-datetime.datetime.fromisoformat(history[0]['stateChangedAt'])).total_seconds()*1000,3) if first else None
 product={}
 for p in s['products'] or []:
  for d in p['dataItems'] or []:
   if d.get('type')=='text':
    try:product=json.loads(d['text'])
    except (ValueError,TypeError):pass
 timings.append({'session_id':row['session_id'],'task_id':row['task_id'],'first_business_result':first['state'] if first else None,'leader_processing_ms':elapsed,'basis':'First accepted to first non-working state; excludes platform planning and subsequent human waits','status_history':history})
 continuation=product.get('planContinuation') or product.get('cancellationContinuation') or {}
 for cmd in commands:
  rows.append({'kind':'external','session_id':row['session_id'],'task_id':row['task_id'],'parent_task_id':continuation.get('source_task_id',''),'message_id':cmd['id'],'action':cmd['command'],'status':s['status']['state'],'plan_reference':product.get('confirmationReference') or continuation.get('reference',''),'order_number':(product.get('workOrder') or {}).get('number',''),'processing_ms':elapsed})
sessions_by_task={r['task_id']:r['session_id'] for r in v['rpc']}
subtasks_by_wire={s['external_task_id']:s for s in v['business']['task_subtasks']}
for sub in v['business']['task_subtasks']:
 if sessions_by_task.get(sub['parent_task_id']) not in sessions:continue
 rows.append({'kind':'partner','session_id':sessions_by_task[sub['parent_task_id']],'task_id':sub['external_task_id'],'parent_task_id':sub['parent_task_id'],'message_id':sub['message_id'],'action':sub['partner']+':'+sub['action'],'status':sub['status'],'plan_reference':'','order_number':'','processing_ms':round((datetime.datetime.fromisoformat(sub['updated_at'])-datetime.datetime.fromisoformat(sub['created_at'])).total_seconds()*1000,3)})
for role in ['resource','workorder']:
 for line in (FOLDER/('server-'+role+'-inbox.log')).read_text(encoding='utf-8').splitlines():
  match=re.search(r'event=mq_task_(processed|completed).*?task_id=(\S+) message_id=(\S+)',line)
  if not match:continue
  state,task,message=match.groups();sub=subtasks_by_wire.get(task)
  if not sub or sessions_by_task.get(sub['parent_task_id']) not in sessions:continue
  rows.append({'kind':'mq-wire','session_id':sessions_by_task[sub['parent_task_id']],'task_id':task,'parent_task_id':sub['parent_task_id'],'message_id':message,'action':role+':'+('complete' if state=='completed' else sub['action']),'status':state,'plan_reference':'','order_number':'','processing_ms':''})
with (FOLDER/'task-id-correspondence.csv').open('w',encoding='utf-8-sig',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=['kind','session_id','task_id','parent_task_id','message_id','action','status','plan_reference','order_number','processing_ms']);writer.writeheader();writer.writerows(rows)
(FOLDER/'response-times.json').write_text(json.dumps(timings,ensure_ascii=False,indent=2),encoding='utf-8')
cancel=next(t for t in v['business']['agent_tasks'] if t['task_id']=='3ae124af-aae7-4406-9eac-cc7eee174215')
before=json.loads((FOLDER/'before-dingdang-confirm.json').read_text(encoding='utf-8'))
after=json.loads((FOLDER/'after-dingdang-confirm.json').read_text(encoding='utf-8'))
repeat=json.loads((FOLDER/'after-duplicate-success.json').read_text(encoding='utf-8'))
checks={'final_counts':v['counts'],'database_integrity':v['integrity'],'formal_confirm_additions':{k:after['counts'][k]-before['counts'][k] for k in after['counts']},'repeat_counts_unchanged':repeat['counts']==after['counts'],'cancel_status':cancel['status'],'cancel_continuation':json.loads(cancel['context_json'])['cancellation_continuation'],'services':v['services'],'id_rows':len(rows)}
(FOLDER/'flow-conclusions.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(checks,ensure_ascii=False))
assert checks['repeat_counts_unchanged'] and checks['formal_confirm_additions']=={'work_orders':1,'active_reservations':3} and checks['cancel_status']=='cancelled'

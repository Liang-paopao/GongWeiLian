"""Update current status from this completed audit; preserve previous evidence."""
import json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];folder=Path(__file__).parent
p=ROOT/'CHECK_STATUS.json';v=json.loads(p.read_text(encoding='utf-8'))
v['as_of']='2026-10-09';v['platform_verified']=False;v['evidence']=str(folder.relative_to(ROOT)/'README.md').replace('\\','/')
v['deployment'].update(frontend_revision='precision-20261008-final3',final_audit_backup='/opt/gongwei/backups/20261008-234234-final-audit')
v['mq'].update(latest_partner_restart='PASS unchanged database; reconnected to 5671 and rejoined group via official Inbox',latest_partner_restart_evidence='reports/final-flow-check-20261008/mq-partner-restart.json')
v['discovery'].update(evidence='reports/final-flow-check-20261008/discovery-*.json',checked_at='2026-10-08')
v['dingdang'].update(full_acceptance=False,latest_session='session_1822',evidence=v['evidence'],automatic_discovery=True,automatic_discovery_evidence='reports/final-flow-check-20261008/dingdang-auto-discovery-final.png',homepage_plan_reference_order='PASS WO-20261008-1C8738, actual two MQ Partners; subsequently cancelled through normal UI for test cleanup',repeat_live_delivery='PASS exact reference new RPC; completed/idempotent=true, order and reservation counts unchanged',final_hardened_version_new_live_call='PASS main three rounds and exact repeat; final cancellation-only patch independently deployed and live cancellation verified',platform_public_statistics='HTTP200 own AICs absent in 2026-10-08 21:00–24:00',modify_live='PASS 14:00 to15:00, same external session, new protocol and business task',cancel_live='BUSINESS PASS canceled/cancelled, no side effects; platform DAG renders failed')
v['local_tests'].update(unit_total=296,unit_passed=295,unit_skipped=1,web_controls='23 groups PASS',browser_flow='PASS real public website local_rpc: clarification, resources, proposal, confirmation, repeat, cancel, lifecycle, optional WAV upload',homepage_reference_cases='27/27 server predeployment tests')
v['server_tests'].update(unit_total=296,unit_passed=296,unit_skipped=0,public_mtls_continue='PASS public443 SDK; not DingDang',public_identity_rejections='PASS missing cert, wrong EKU and wrong senderId')
v['frontend'].update(responsive_cases=12,public_asset_hashes='PASS index/app.js exact current hashes',report='reports/final-flow-check-20261008/README.md',latest_fix='Home result follows latest matching work-order status',console_errors_scope='Previous frontend audit; no new JavaScript runtime error observed in final audit')
v['final_delivery'].update(only_pdf_and_video_remaining=False,pending=['Platform AMP access/message statistics evidence','Completed work-order reusable-resource return/consumable closeout rules','Shared server full reboot recovery acceptance','DingDang canceled status displayed as failed'])
p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for name in ['stage2-pu0qsotj','stage5-4dzoln95','stage4-60-8_2bpy7s']:
 src=ROOT/'reports/local-test-runs'/name;dest=folder/'offline-integration'/name;dest.mkdir(parents=True,exist_ok=True)
 assert src.resolve().is_relative_to(ROOT.resolve())
 for f in src.rglob('*'):
  if f.is_file() and f.suffix in {'.json','.jsonl','.log','.txt'}:
   target=dest/f.relative_to(src);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
result=subprocess.run(['node','scripts/test_web_controls.cjs'],cwd=ROOT,capture_output=True)
(folder/'frontend-final.log').write_bytes(result.stdout+result.stderr);assert result.returncode==0
(folder/'review-notes.md').write_text('''# 独立复核记录\n\n审查范围为精确DAG尾注确认、未确认方案跨协议任务取消及主页工单状态。首次复核发现事务外指纹竞态P2，已实际复现红灯并补事务内offer/withdrawn/实时指纹/持久历史复核。新增回归绿灯；最终独立审查未发现P0/P1/P2。\n\n另有真实SQLite探针验证：取消先提交阻止迟到reserve；预留先提交拒绝跨task取消接续；事务前历史变化拒绝接续。前端23组通过。该审查不替代本地296、服务器296及真实浏览器证据。\n''',encoding='utf-8')
print(json.dumps({'status_updated':True,'offline_logs_included':3,'frontend_pass':True}))

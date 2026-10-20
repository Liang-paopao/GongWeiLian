"""Update the current delivery index from captured real acceptance evidence."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = Path(__file__).parent
REPORT = 'reports/platform-closeout-20261009/README.md'
data = json.loads((ROOT / 'CHECK_STATUS.json').read_text(encoding='utf-8'))
data['as_of'] = '2026-10-09'
data['platform_verified'] = False
data['deployment'].update(services_active=9, frontend_revision='precision-20261009-closeout',
    latest_closeout_backup='/opt/gongwei/backups/20261009-011144-closeout',
    latest_cancel_guard_backup='/opt/gongwei/backups/20261009-015437-cancel-guard',
    metadata_backup='/opt/gongwei/backups/20261009-012543-amp-metadata',
    full_server_reboot='PASS actual boot ID changed; 9 own and 7 other services active/enabled; 5 sites HTTPS200',
    full_server_reboot_evidence='reports/platform-closeout-20261009/reboot-final.json')
data['discovery'].update(checked_at='2026-10-09',
    evidence='reports/platform-closeout-20261009/discovery-*.json')
data['dingdang'].update(full_acceptance=False, business_acceptance=True,
    latest_session='session_1841', evidence=REPORT,
    automatic_discovery=True,
    automatic_discovery_evidence='reports/platform-closeout-20261009/dingdang-auto-discovery.png',
    homepage_plan_reference_order='PASS WO-20261009-A1044F; real two formal MQ Partners; one new order and three reservations',
    repeat_live_delivery='PASS actual new RPC task; completed/idempotent=true; same order; unchanged 5 orders/3 active reservations',
    final_hardened_version_new_live_call='PASS three rounds, repeat, independent modify and cancel after final guard deployment',
    modify_live='PASS session_1842 14:00 to15:00; real resource query; no added orders or active reservations',
    cancel_live='PASS new Start performs cancel_plan: protocol completed, business cancelled, green platform DAG and explicit member summary; true protocol Cancel remains canceled',
    platform_public_statistics='PARTIAL: Message counts Leader20/resource10/workorder10; HTTPS Access0; real callee Kafka records observed but caller pair not found in captured window',
    platform_access_evidence='reports/platform-closeout-20261009/amp-access-pairing-investigation.md')
data['local_tests'].update(unit_total=369, unit_passed=368, unit_skipped=1,
    web_controls='24 groups PASS', homepage_reference_cases='36 cases PASS independent guard review',
    evidence='reports/platform-closeout-20261009/local-regression-latest.log')
data['server_tests'].update(unit_total=369, unit_passed=369, unit_skipped=0,
    evidence='reports/platform-closeout-20261009/server-regression-fresh.json')
data['frontend'].update(latest_fix='Work-order closeout refreshes real inventory/worker data; failed-state and audit labels',
    report=REPORT, backend_changed=True,
    console_errors_scope='Previous 12-case frontend audit; this turn tests 24 controls and real inventory return')
data['amp'] = {'metadata_authorized': True, 'broker':'wt.ioa.pub:19092',
    'transport':'PLAINTEXT explicitly authorized for protocol metadata only',
    'topics':['amp.access','amp.message'], 'forwarder_service':'gongwei-amp-metadata',
    'message_statistics':'PASS Leader20/resource10/workorder10 in 01:00–04:00 capture; includes diagnostics and group fanout',
    'https_access_statistics':'NOT PASSED; caller/callee pairing needs platform investigation',
    'evidence':'reports/platform-closeout-20261009/platform-statistics.json'}
data['work_order_closeout'] = {'completed':'atomic release worker/tool; consume planned part',
    'failed':'atomic compensation of all active reservations',
    'legacy_completed_order':'WO-20261008-3D7B9C reconciled through existing API twice HTTP200',
    'tests':'9/9; repeat/concurrent/terminal/legacy/category rollback',
    'evidence':'reports/platform-closeout-20261009/legacy-order-closeout.json'}
data['final_delivery'].update(only_pdf_and_video_remaining=False,
    pending=['Platform DingDang caller AMP Access pairing/HTTPS public statistic',
             'Final technical PDF and demonstration video'])
data['evidence'] = REPORT
(ROOT / 'CHECK_STATUS.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

current = '''# 工维联当前状态（2026-10-09）

- 在现有真实项目修复并部署工单完成/失败资源结算、取消操作返回、取消重投守卫和 AMP 协议元数据采集/转发；无数据库迁移或身份变更。
- 叮当已真实登录。新三轮 session_1841 完成工单 **WO-20261009-A1044F**；通过正式 HTTPS mTLS Leader 和两个官方 MQ Partner，确认前未建单/预留，确认后只新增一张工单和三条预留。
- 再次实际执行同方案确认返回 completed/idempotent=true，仍同一工单。独立 session_1842 改期 14:00→15:00、再次查询资源、取消待确认方案通过；取消业务操作显示绿色 completed 和明确“未预留/未建单”成员摘要。真协议 Cancel 仍保持 canceled。
- 首页仍重建协议 taskId。按用户批准的明确方案编号、同一会话/调用者和持久历史接续；没有把协议编号变化写成已修复。
- 本机 369 项：368 通过、1 Windows 符号链接权限跳过；服务器 **369/369**；阶段二、阶段五、60/60 场景、24 组网页控件通过。
- 完成旧单 WO-20261008-3D7B9C 的安全结算：工具从 1/2 归还至 2/2，人员释放，密封圈已消耗一件而未加回。重复完成两次没有重复归还；网页刷新真实库存。
- 已执行授权的共享服务器整机重启，boot ID 真实变化。9 个本项目服务及 7 个其他项目依赖 active/enabled，5 个既有站点 HTTPS200，数据库 integrity=ok，正式 MQ 自动恢复。
- 三个 AIC 默认在线精确查询均 HTTP200 返回；无指定名称的叮当自动发现推荐 Leader。正式 Partner 策略仍显式 platform_catalog，目录记录不声称有实时在线字段。
- 平台 Message 统计现已检出：Leader 20、资源/工单各 10（01:00–04:00 窗口，含诊断和群组广播接收，不能解释为业务工单数量）。**HTTPS Access 仍 0**；本次 16 分区/107 条只读扫描能找到三轮 13 条真实 callee 记录，未找到配对 caller。需平台核查叮当采集/转发与匹配，未伪造 caller。
- **platform_verified=false**。当前业务调用链已通过，仍不能宣称全平台统计验收通过。技术方案 PDF 和演示视频尚未制作。

最新报告：[本轮验收与证据](reports/platform-closeout-20261009/README.md)。最新评审包：`reports/gongwei-platform-closeout-review-20261009.zip`。最终数据库 5 单/3 active，本轮未删除订单、日志、凭据或其他项目文件。

## 以下为之前阶段的历史记录，按各自日期解释

'''
old = (ROOT / 'STATUS.md').read_text(encoding='utf-8')
(ROOT / 'STATUS.md').write_text(current+old,encoding='utf-8')

readme = '''# 最新实际验收（2026-10-09）

叮当真实三轮已完成 **WO-20261009-A1044F**：补充信息→方案编号确认→正式 MQ 两个 Partner→唯一工单→completed。重复确认、独立修改/取消也通过，未重复占用资源。完成工单后的工具归还及失败补偿已修复并部署。

本机 368/369 通过（1 Windows 权限跳过）、服务器 369/369、24 组网页控件和 60/60 场景通过。共享服务器已实际重启，9 个本项目服务及其他既有服务自动恢复，5 个网站 HTTPS200。

仍有一项平台侧统计待核查：Message 已计数，Leader HTTPS Access 尚缺叮当 caller 配对证据。保持 `platform_verified=false`；不能说只剩 PDF/视频。见 [最新报告](reports/platform-closeout-20261009/README.md) 和 [人工处理项](HUMAN_ACTIONS.md)。最新评审包：`reports/gongwei-platform-closeout-review-20261009.zip`。

## 以下为此前验收历史

'''
old = (ROOT / 'README.md').read_text(encoding='utf-8')
(ROOT / 'README.md').write_text(readme+old,encoding='utf-8')

issues = '''# 当前未完成事项（2026-10-09）

1. **叮当→Leader HTTPS Access 双侧匹配未通过**：平台 Message 已显示 Leader20、资源/工单各10；HTTPS Access仍0。我方 callee已在官方Kafka观察到，01:55–02:10北京时间捕获全部16分区107条，未找到对应叮当caller。只说明该窗口，不能推广至平台全部历史。平台需核查caller emitter/转发/correlationId和匹配规则；我方不能代造caller。证据：reports/platform-closeout-20261009/amp-access-pairing-investigation.md。
2. 技术方案 PDF 和演示视频尚未制作。

已经实际解决并部署：工具归还/耗材消耗/失败补偿、取消业务操作绿色completed、取消重复新Start不生成误导方案、元数据真实Message匹配、共享整机重启自动恢复。新三轮、实际重复确认、独立改期/取消和无指定名称的自动发现均通过。当前唯一业务工单WO-20261009-A1044F，5单/3有效预留。

边界：首页协议taskId仍变化，使用用户批准的方案编号/同session和caller的安全接续。设备/人员/库存使用已有标记为模拟的演示业务数据，真实的是平台网络、协议、数据库写入和工单结果。声音仍22条冒烟辅助；本机官方broker环境未安装，直接使用正式梧桐MQ。证书有效至2026-11-24，需到期前续签。平台取消的主聊天没有追加摘要时可在成员详情读取实际取消Product和绿色DAG；未修改平台前端。

`platform_verified=false`。最新报告：reports/platform-closeout-20261009/README.md。

## 以下为历史问题，按其日期解释；已解决项见上方

'''
old=(ROOT/'KNOWN_ISSUES.md').read_text(encoding='utf-8')
(ROOT/'KNOWN_ISSUES.md').write_text(issues+old,encoding='utf-8')

human = '''# 当前平台/人工处理项（2026-10-09）

## 需平台核查：叮当 HTTPS Access caller 配对

我方已完成真实采集、官方Kafka ACK、Message双侧匹配和新三轮调用。平台 HTTPS Access仍0。请平台按以下真实标识核查叮当caller emitter、日志转发、接收/匹配过滤与correlationId：

- session_1841；caller AIC `1.2.156.3088.1.0001.00001.EZTK03.WCU6LR.14YT`。
- Leader AIC `1.2.156.3088.1.BUPT.JSQB3Y.RN5ERG.1KIZGN.0M45`。
- taskId：`a9f43cab-d4ce-4d11-b98b-432b9bf3180f`、`1847721f-6b88-40cb-a658-f51d415cbeb3`、`ce6f1ce3-d1b0-4a0a-b7be-aa8b3e623184`。
- 时间：2026-10-09 01:55–02:10北京时间（17:55–18:10Z前一日）。官方amp.access全部16分区/107条读取完成，其中三个任务callee为3/7/3条，未在该窗口找到caller。
- 官方SDK2.2.0默认caller用sessionId而平台文档要求taskId，仅为潜在差异：本轮未观察实际叮当caller，不断言其当前值错误。网站完整匹配规则尚未公开。

完整范围/样本/限制：reports/platform-closeout-20261009/amp-access-pairing-investigation.json/.md。没有向管理员发送消息，没有代造caller，没有上传对话或人员/工单正文。

## 无需再次处理的旧事项

- 已按授权使用已有凭据完成叮当登录，未保存密码到项目/日志/压缩包。
- 三个身份/证书/默认发现有效，无需重新注册。
- 已实际执行授权的整机重启，9服务及其他项目恢复，不再等待重启许可。
- 已修复终态资源结算，取消操作绿色completed真实通过。

技术方案PDF与演示视频待制作；平台统计缺项完成前保持platform_verified=false。证书应在2026-11-24到期前续签。

## 以下为之前的历史处理记录

'''
old=(ROOT/'HUMAN_ACTIONS.md').read_text(encoding='utf-8')
(ROOT/'HUMAN_ACTIONS.md').write_text(human+old,encoding='utf-8')

deploy = '''# 最新部署与恢复验收（2026-10-09）

在原3个release上增量部署13个目标文件并补Leader取消重投守卫，未迁移数据库/身份或修改其他项目配置。网页cache为precision-20261009-closeout；普通网页local_rpc，正式HTTPS Leader和两个Inbox Partner仍platform_mq_inbox。

新增受限制的gongwei-amp-metadata.service，官方broker wt.ioa.pub:19092的PLAINTEXT仅传输经用户批准的协议元数据。只读挂载3个日志目录，限制CAP_DAC_READ_SEARCH，隐藏secret/env/数据库路径，私有StateDirectory700/cursors600；只有Kafka确认后写入游标，不创建主题。at-least-once的ACK/fsync故障窗口可能重复相同log_id，未承诺exactly-once。

已执行sudo systemctl reboot；boot ID从6b8a5804-6a61-40e8-8fb8-60326c71974c变为6d3e165f-9b6a-445d-9d0b-f10b0e242564。9个本项目服务和7个其他既有服务active/enabled，5既有站点HTTPS200。备份：011144-closeout、012543-amp-metadata、013124-reboot、015437-cancel-guard（均在/opt/gongwei/backups/20261009-*，秘密/数据库备份不进评审包）。

最新证据：reports/platform-closeout-20261009/README.md。Message统计已出现，DingDang HTTPS Access配对待平台；platform_verified=false。

## 历史部署脚本边界

'''
old=(ROOT/'deploy/README.md').read_text(encoding='utf-8')
(ROOT/'deploy/README.md').write_text(deploy+old,encoding='utf-8')
print('Updated current state and preserved dated history; platform_verified=false')

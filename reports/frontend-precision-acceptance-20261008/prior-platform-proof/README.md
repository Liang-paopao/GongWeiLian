# 叮当首页方案编号接续：真实调用复核

日期：2026-10-07（北京时间）。真实项目：gongwei-step1。最终整体状态：**platform_verified=false**。

## 1. 本轮结论

**首页“补充信息 → 待确认方案 → 明确确认 → 正式 MQ 两 Partner → 唯一工单 → completed”已真实通过。** 不是调试入口，不是本地网页，也不是测试脚本伪装叮当。浏览器调用者由 mTLS 校验为叮当 AIC `1.2.156.3088.1.0001.00001.EZTK03.WCU6LR.14YT`。

用户本轮明确接受“方案编号接续，优先完成真实建单”。外部 taskId 仍由平台重建；没有声称 cancel/start 行为消失，也没有复活已取消的协议任务。

- 本轮唯一工单：**WO-20261007-8DC4AC**。
- 设备：pump-002；2026-10-08 15:00–16:00；60 分钟；泵体检查。
- 数据库人员：模拟人员甲；便携检查工具包、机械密封圈各 1。
- 数据来自已有演示种子资源，保留 simulated 标记；网络调用、资源预留和数据库写入真实执行，不代表已经安排真实员工到现场。
- 方案编号：`GW-2ec569cd1fa191e1beda84849cc6b680`。
- 方案 ID：`plan-7152f38a-5af3-4a62-a12e-82cb6b029145`。
- 会话：`session_1726`。

## 2. 要求、官方语义和定位

重新核对 20261005 智能体化方案中多轮、人工确认、取消、幂等与恢复要求，以及 20261003 全量复核要求；核对本机安装的官方 ACPs SDK 2.2.0 的 DefaultHandlers.cancel/complete/continue_。

官方 canceled 是终态；continue 处理等待输入或等待完成的任务；空 complete 是完成握手，不是创建工单的授权。故方案仍以 awaiting-input 询问人类确认，不能收到空 complete 就建单。

当前平台公开客户端 `continueSecretaryCollaboration` 仍先取消旧 run，再向 `/agent/execute` 提交新任务。工维联此前只接受原 task 的确认，无法把新 task 上的确认绑定到刚才展示的方案。另一个已修复的转发解析问题是不能将问题中的示例时间当成用户输入。

本轮替代方案已获用户明确同意：方案编号绑定方案内容摘要；接收严格确认句；对于平台历史包装，先核对已持久化来源原文，且只能追加一个包含唯一回答的新轮次；校验 RPC 身份所有者、session 和方案版本/期限后，由新的 task 引用同一个业务方案。旧 canceled task 原样保留；工单幂等键按 plan_id 稳定，两个新任务并发确认按方案串行执行。

公开客户端来源及哈希：client-source.json。官方 SDK： https://github.com/AIP-PUB/ACPs-community/tree/v2.2.0/acps-sdk 。没有修改平台客户端、浏览器内部状态或官方 SDK。

## 3. 三轮真实结果

| 轮次 | 外部 taskId | 结果 | Leader 处理耗时 |
|---|---|---|---:|
| 1 | 0baf36fd-73ff-4ce0-8fb0-501247cb6423 | accepted → working → awaiting-input；缺开始时间和时长 | 0.027 秒 |
| 2 | 6887e4c3-572c-4086-95db-8798ee5e42fd | 正式 MQ 查询资源；15:00–16:00 待确认方案 | 17.951 秒 |
| 3 | 7ecfb38d-5b15-4b52-b1ae-4f6bc14499c8 | 正式 MQ 预留、建单、completed | 5.277 秒 |

耗时按 Leader accepted 至首次业务响应的真实时间戳计算，不包含叮当意图分析、LLM 编排、浏览器渲染和人工输入间隔。叮当第三轮成员详情显示实际调用 5.04 秒、轮询 2 次；口径不同，单独保留。

第一条输入明确选择工维联 Leader，发现结果中仅勾选并执行该 Leader。首页“上新”已刷新为其他项目，因此使用本轮真实发现结果中的 Leader 卡片，而非冒称本轮点击了已不显示在上新区的旧卡片。

第二条：`下午三点开始，预计一小时，需要泵体检查技能。`

第三条：`确认方案 GW-2ec569cd1fa191e1beda84849cc6b680 并创建工单。`

第三轮首页 DAG 显示 Leader completed；点击完成的 Leader 成员详情可以看到正式 Product 中的工单编号、状态与完整结构化结果。随后同一聊天再次确认时，叮当也以可读文本展示同一工单（work-order-visible.png）。聊天摘要不作为新增 RPC 调用证据。

## 4. 数据与 MQ 证据

| 时间点 | 数据库总工单 | 总活动预留 | 本轮方案工单 | 本轮方案预留 |
|---|---:|---:|---:|---:|
| 调用前 | 1 | 3 | 0 | 0 |
| 第二轮方案后、确认前 | 1 | 3 | 0 | 0 |
| 确认后 | 2 | 6 | 1 | 3 |
| 重复聊天及重投被配额阻断后 | 2 | 6 | 1 | 3 |

原有另一张调试工单保留。本轮没有删除或覆盖旧数据。

真实子任务均为 completed：

- `6887e4c3-572c-4086-95db-8798ee5e42fd:resource:01`：query_resources。
- `7ecfb38d-5b15-4b52-b1ae-4f6bc14499c8:resource:02`：reserve_resources。
- `7ecfb38d-5b15-4b52-b1ae-4f6bc14499c8:workorder:01`：create_work_order。

三个角色日志见 after-confirm/server-*.log；群组为 group-session-1726。Partner 日志包含 accepted、working、awaiting-completion、completed 及实际 MQ command messageId。业务表 task_subtasks 存储 parent_task_id 与外部确认 messageId；完整映射见 id-correlation.json，数据库/资源/审计事件和协议快照见 database-and-protocol-final.json。新 task 的 context_json.plan_continuation 保存方案来源 task、session、sender、确认 messageId 和确认时间。

## 5. 重复确认的准确边界

再次在首页聊天输入同一确认，叮当读取既有结果，返回工单 WO-20261007-8DC4AC。

为了验证不是聊天复述，又通过候选列表只选择 Leader、填入相同方案确认并实际点击执行。平台返回：**今日使用次数已达上限，请明天再试。如需增加限额，请联系管理员。** 没有第四个任务进入 Leader。截图 repeat-quota-blocked.png；没有绕过配额，也没有用其他身份冒充叮当重放。

因此：本轮首页三轮建单通过；正式首页再次投递的幂等测试被配额阻断，尚未通过。离线测试已覆盖相同方案跨 task 重复确认、并发确认、进程重建后的重放，并验证只建一张工单、预留一次；不能用它替代这项正式重投验收。

## 6. Discovery、平台统计与部署

- 默认在线精确查询：三个当前 AIC 均返回。首次 Leader 查询遇 TLS 握手超时，重试成功，失败和重试均保留。
- 本轮叮当自然语言发现返回 Leader，随后真实调用成功。
- 当前 Leader Partner 选择策略仍是此前明确配置的 platform_catalog，使用真实 Discovery 目录，不是静态 ACS。该策略的 online=false/liveness=unknown 不能被误写为已校验在线；本轮单独的 default-discovery.json 与 leader-discovery-retry.json 才是默认在线查询证据。
- 平台公开统计 `/internal/matched-stats/top` 在 19:00–20:00 时段 HTTP 200，但未检出本项目三个 AIC；见 platform-hour-statistics.json。不能宣称后台匹配统计通过，也不能由此断言平台内部完全没有访问日志。
- 首页真实建单时 Leader 运行 `/opt/gongwei/releases/20261007-111746-maintenance`，审查补强后的最终 Leader 已发布到 `/opt/gongwei/releases/20261007-120338-maintenance`；切换前备份真实运行代码、SQLite、服务及 Nginx 配置。初次部署备份见 deployment/，最终备份见 final-deployment/。review-deployment/ 是未启用的中间候选版本。
- 8 个服务 active/enabled；只重启 Leader，其他 7 个进程 PID 保持；Nginx 配置哈希不变。
- AIC、证书、域名、其他项目和数据库结构未修改。网页 local_rpc 保持，正式 Leader 出站为官方 MQ，无 RPC 回退。

## 7. 测试与命令

新增 22 项测试，主要覆盖：cancel/start/按编号确认与重启重放、跨 session/sender 拒绝、引用和否定文本不授权、方案修改失效、并发确认唯一、明确用户取消撤销编号、过期拒绝、不同检查请求不能套用方案、旧 Inbox 入口保持原有确认方式。

初始 5 项均因缺失方案编号能力失败（red-tests.log）；Inbox 兼容检查另有失败后修复记录。独立审查又发现引用误授权、旧任务改写已确认请求、取消竞态等边界，均补复现并修复；红绿记录和最终通过意见见 code-review.md。最终：

- 本机 unittest：291 项，290 通过、1 项 Windows 符号链接权限条件跳过。
- 服务器 unittest：291/291 通过。
- 本机与服务器阶段二、阶段五集成：全部通过。
- 命令：`python -m unittest discover -p test_*.py`；`python run_stage2_tests.py`；`python run_stage5_tests.py`。
- 部署复用 deploy_experience_refresh 的 prepare/test_release 与 activate_leader_continuation，仅切换 Leader。
- `git diff --check` 与 `python -m py_compile` 对本轮实现/测试文件通过。未配置独立 lint/typecheck/build 工具，未改前端。
- 独立审查最终 30/30 及尾部保护 7/7 通过；本轮最终首页接续测试 22/22。
- 最终版本已重验生产保存的真实第二、第三轮原文及历史绑定，PASS；这是解析重验，不是一次新的叮当网络调用。
- 最终部署后 8 个服务 active/enabled，原工单仍 confirmed；本轮方案仍 1 工单/3 预留，完整数据库 2 工单/6 预留（含此前调试工单）。见 post-final-deploy-state.json。

## 8. 修改文件与剩余事项

实现：plan_continuation.py、leader_external_flow.py、leader_rpc_runtime.py、stage2_domain.py；测试：test_homepage_continuation.py。

文档：docs/superpowers/plans/2026-10-07-homepage-plan-continuation.md、README.md、STATUS.md、KNOWN_ISSUES.md、HUMAN_ACTIONS.md、CHECK_STATUS.json，以及本目录证据/报告。

剩余：

**安全补强后的最终版本没有再次执行新的首页三轮建单，原因是平台当天配额用尽。此前已完成的真实建单、最终离线回归、原命令重验、服务器部署分别提供证据。**

1. 配额恢复后，在相同会话对相同方案进行真正再次投递，验证 idempotent=true、无新增工单和资源；新增独立修改/取消任务的首页复测也待配额。
2. 平台后台访问匹配统计尚未检出本项目，需继续核对 AMP Access/Message 上报与匹配链路。
3. 严格外部 taskId 不变仍需叮当客户端修改；本轮按已获用户同意的方案编号模式通过业务链路。
4. 历史会话重载 conversation_id 类型错误本轮未重新触发；不宣称已修复。
5. 平台包装将来变化或包含非标准附加内容时，会保守拒绝并提示直接编号确认；不能将未识别内容当作授权。
6. 整机重启与全部最终平台闸门尚未完成。本轮不扩大到共享服务器重启或修改其他项目。

在这些剩余事项完成前继续保持 **platform_verified=false**。

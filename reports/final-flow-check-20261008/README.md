# 工维联最终全流程复核（2026-10-08）

## 结论与范围

在真实项目 `gongwei-step1`、现有腾讯云网站和梧桐正式 MQ 上实际操作，未另建项目、迁移 WIT、注册新智能体或改动身份/数据库结构。使用 Superpowers、systematic-debugging、verification-before-completion、frontend-design、Impeccable，并进行独立代码复核；未使用 Three.js。

网页业务流程和叮当方案编号确认建单已经通过。**仍不能宣布只剩技术方案 PDF 和演示视频；platform_verified=false。** 平台访问/消息统计证据、完成工单后的可复用资源归还、共享服务器整机重启验收尚未完成。叮当将正常取消显示为 DAG“失败”的呈现问题也仍存在。

人员、设备、库存为原有明确标注的模拟业务数据；网络、官方 SDK、mTLS、MQ、数据库操作和截图是真实运行证据。这不是实体水泵维修或现场人员派工验收。

## 验收表

| 检查项 | 实际结果 | 证据 |
|---|---|---|
| 四页网页、真实后端数据 | 通过；网站为 local_rpc | final-web-*.png/.txt |
| 网页首轮补充、资源查询、修改 | 通过；确认前不建单/预留 | web-round1.png、web-replanned.png、before-confirm.json |
| 网页确认、重复确认、工单生命周期 | 唯一工单 WO-20261008-3D7B9C，confirmed→in_progress→completed；重复返回已有结果 | web-created.png、web-order-*.png、web-duplicate-confirm.json |
| 网页取消工单、释放资源 | 通过；保留记录，不删除数据库行 | web-old-test-order-cancelled.png、final-state.json |
| 声音辅助 | 一条公开 WAV 真实上传/推理，显示疑似异常，未自动建单 | web-audio-success.png/.txt |
| 三个 AIC 默认在线 ADP 查询 | 均返回目标；两个 Partner 首次 TLS EOF，单次重试通过 | discovery-*.json |
| 无指定智能体的自动发现 | 叮当明确推荐 Leader 为 primary，未点击执行其他智能体 | dingdang-auto-discovery-final.png/.txt |
| 正式叮当三轮建单 | 通过；真实 HTTPS/mTLS Leader→官方 MQ 两 Partner | dingdang-round*.png、dingdang-completed-detail.png |
| 正式重复确认 | completed、idempotent=true；工单及预留数不变 | dingdang-duplicate-success.png、after-duplicate-success.json |
| 独立修改方案 | 14:00→15:00，资源 Partner 重新查询，未建单/预留 | dingdang-modify-*.png |
| 独立取消待确认方案 | 修复后 Leader 返回 canceled，方案/请求 cancelled，无新增工单/占用；平台 DAG 显示 failed | dingdang-cancel-after-fix.png/.txt、flow-conclusions.json |
| 无证书、错误 EKU、错误 senderId | 均拒绝；正确身份可到达协议处理 | public-mtls-security.json |
| 同 session/task 的原生 continue | 正式公网 SDK 调用通过；该测试不是叮当首页 | public-leader-continue.json |
| MQ 两 Partner 重启恢复 | 重连5671、监听 Inbox、重新邀请/入群/查询通过，重启前后工单/库存/预留一致 | mq-partner-restart.json、三个 server-*.log |
| 平台后台访问量/AMP业务匹配 | 未通过：统计 HTTP200 未出现本项目三个 AIC；不代表平台没有任何内部日志 | platform-statistics-final-retry.json |
| 整机重启 | 未执行；只重启本项目服务，8服务 active/enabled | final-state.json |

## 叮当正式三轮、重复确认

同一 `session_1822`，调用者为叮当真实身份。首页仍执行 cancel/start，因此外部 taskId **发生变化**；用户已接受“明确方案编号＋同一会话/调用者”的业务接续。不是恢复已取消的协议任务，也不是原生同 taskId 多轮。

1. 第一轮“水泵002运行异常，帮我安排明天下午检查。”：任务 `5cd15141-6add-42de-b50c-1fa88c551bbb`；accepted→working→awaiting-input，提示开始时间、预计时长。
2. 第二轮“下午两点开始，预计一小时，需要泵体检查技能。”：任务 `3dc5ed5c-0eeb-434d-8e0b-bd1357e2cf13`；资源 Partner 实际查询，生成 `GW-b469b938862008c3525395088c5fb3ed`。日期2026-10-09、14:00–15:00、模拟人员甲、检查工具包/密封圈各1。仅待确认，尚无工单和预留。
3. 第三轮“确认方案 GW-b469b938862008c3525395088c5fb3ed 并创建工单。”：任务 `c7b49b4d-e14f-457b-8f4f-6de4f02ee60f`；资源 Partner 预留、工单 Partner 创建，Leader返回 completed。真实工单 **WO-20261008-1C8738**，新增恰好1单/3预留。
4. 同会话再次发送相同确认句：任务 `c1ba5ebd-fb09-4bd7-bbec-75f420ec50e4`；completed、idempotent=true，叮当可见最终结果，数据库4单/6预留保持。此时 Leader 已实际重启，持久化方案仍可恢复。

第3轮初次执行完成后，平台曾仅在成员详情展示结构化结果；第4轮明确出现面向用户的汇总。完成上述幂等验证后，通过正常网页取消本次正式测试工单，释放3预留，为独立修改测试腾出资源。当前该工单为 cancelled，历史 completed 协议结果保留；不能将当前数据库状态写成 confirmed。

独立修改使用 `session_1825`，14:00方案改为15:00、人员重新匹配为模拟人员丙。首页新task产生新未确认业务方案，不宣称整个修改过程保持同一个 request/plan ID。首次取消错误地生成方案；修复后再次取消，任务 `3ae124af-aae7-4406-9eac-cc7eee174215` 正确关联并撤销 `d2323be0-2a20-4340-8d25-042c2acdafcc` 的未确认方案。

协议状态采用官方 SDK 实际名称：accepted、working、awaiting-input、awaiting-completion、completed、canceled。外部方案确认通过 awaiting-input + requiresConfirmation 表达；两个 MQ Partner 的日志完整包含 Accepted→Working→AwaitingCompletion→Completed。没有伪造另一种协议字段。

### ID及响应时间

完整外部消息、来源task、Partner子task、外部业务message与MQ独立wire message在 [task-id-correspondence.csv](task-id-correspondence.csv)，共40行。本业务子任务表的 message_id保存外部主消息，MQ自身生成的命令编号另由真实日志关联；两者没有假装相同。

| 操作 | Leader accepted→首个业务结果 | 叮当成员详情显示 |
|---|---:|---:|
| 首轮补充 | 36.076 ms | 未单独采集 |
| 第二轮方案（含首次入群） | 15,631.044 ms | 未单独采集 |
| 第三轮建单 | 6,595.316 ms | 4.6 s / 2次轮询 |
| 重复确认 | 48.917 ms | 2.11 s / 1次轮询 |
| 修改方案 | 5,548.380 ms | 见页面详情记录 |
| 修复后取消 | 56.419 ms | 2.28 s / 1次轮询 |

以上两列为不同计时口径，不互相替代：Leader源自持久状态时间戳，叮当为平台自报详情，可能不包含完整客户端规划与后台任务时间。`browser-observation-times.json`含调试等待，不作为实际响应时长。

## 发现的问题、实际修复和发布

1. 网页发送第二轮返回500：release日志由root创建，服务用户不能写。独立配置可写 `GONGWEI_LOG_DIR=/opt/gongwei/shared/logs/aip`，重启4个网页/local_rpc服务，真实复测通过。没有扩大证书/秘密权限。
2. 2.5 MiB录音上传返回413：网站Nginx默认1MiB限制。仅本网站HTTPS server改 `client_max_body_size 15M`，适配现有10MiB WAV的base64 JSON；nginx -t和reload通过，其他配置哈希保持。后端录音限制不变。
3. 叮当精确重复确认带固定DAG路由尾注，原校验误拒绝。只允许剥离平台已观察的固定尾注，依然拒绝任意追加文本、伪造历史、引用、跨会话/调用者和过期方案。
4. 首页取消旧task/newstart后，未确认方案取消未接续。绑定同一认证所有者、会话、唯一持久历史及当前回答；事务中复核指纹、offer、撤销/预留/工单状态并原子取消。新增用例和独立竞态审查通过。迟到资源预留被拒绝，已预留/已确认工单不误取消。
5. 主协作“工单结果”使用创建快照，生命周期变化后文字滞后。改为按本任务工单ID读取最新真实工单，不能用选中的其他工单覆盖。
6. 全量测试发现Windows真实SQLite事件循环耗时超过测试外层0.5秒。外层完成等待改5秒；取消、唯一性及补偿断言保留。单独复验及全量通过。

最近部署仅替换 Leader 的 `plan_continuation.py`、`leader_external_flow.py`，网站的 `web/app.js`、`web/index.html`。27项新增/既有接续用例在服务器部署前通过。备份包含原文件和在线SQLite备份，保存在服务器私有目录，不进评审包。

最后部署备份：`/opt/gongwei/backups/20261008-234234-final-audit`；日志修复备份`20261008-final-flow-logs-221422`；上传配置备份`20261008-230408-upload-limit`。本次没有数据库迁移，三套独立身份和证书保持原配置。

## 自动测试与浏览器验证

| 实际执行命令/入口 | 结果 |
|---|---|
| `.venv\Scripts\python.exe -B -m unittest discover` | 296项，295通过、1 Windows符号链接权限跳过，0失败；check-3-final3.log |
| 服务器 `.venv/bin/python` 全量 discover，替换27项接续用例为当前新文件 | 296/296，0跳过；server-regression.log/.json |
| `node --check web/app.js` | exit0 |
| `node scripts/test_web_controls.cjs` | 23组通过；含生命周期结果刷新/非本任务保护 |
| `.venv\Scripts\python.exe run_stage2_tests.py` | 真实本机AIP两Partner、网页建单/重投/取消/持久化通过 |
| `.venv\Scripts\python.exe run_stage5_tests.py` | 重新安排、幂等、失败补偿、恢复和审计通过 |
| `.venv\Scripts\python.exe scripts/run_60_scenarios.py` | 60/60通过 |
| 真实网站三种桌面尺寸×四页 | 12/12，无横向溢出、技术详情默认折叠 |
| 公网index/app.js字节与本机校验 | HTTP200、SHA256一致；final-public-check.json |

原生HTML/CSS/JS项目未配置独立lint/typecheck/build命令，不能杜撰这些结果。单元测试中的“Docker MQ缺失”输出来自预期负向用例；本轮正式MQ证据来自梧桐5671实际运行，不是本机替代broker。禁止安装Docker的约束保持。

完整保留首轮失败日志、诊断和最后通过日志，不删除失败历史。295项旧运行的测试本体exit0但输出包装受GBK编码报错；最终296项已用UTF-8完整重新运行、exit0。

## 最终部署与数据库

- 网站：`https://gongwei.yanyi.online`，local_rpc。
- 正式Leader：`https://leader.yanyi.online/rpc`，独立mTLS进程，身份绑定开启；出站及两Partner为 platform_mq_inbox。无静默RPC降级。
- 正式Broker `amqps://wt.ioa.pub:5671`；真实可用鉴权 `https://wt.ioa.pub:9007`；vhost `/acps`。历史443鉴权故障不是当前配置。
- Partner发现策略仍明确 platform_catalog，即访问真实平台全状态目录；默认在线ADP三个AIC另行验证，不能把目录online=false写成online=true。
- 8个本项目service active/enabled：web、resource、workorder、audio、leader、resource-inbox、workorder-inbox、amp-heartbeat。启动使用 `sudo systemctl start gongwei-leader gongwei-resource-inbox gongwei-workorder-inbox`；网站四服务保持各自入口。
- 证书三套独立clientAuth、Leader独立serverAuth，DNS SAN正确，私钥权限600；元数据见runtime-final.json，不包含私钥/证书全文。有效期至2026-11-24，需到期前续签。
- 数据库 integrity=ok；最终4张工单、3条active预留。两条历史测试工单、本次正式MQ测试单均经正常取消，记录仍在；网页完成单的3预留仍存在。

## 修改文件清单

运行代码/测试：`plan_continuation.py`、`leader_external_flow.py`、`test_homepage_continuation.py`、`test_leader_rpc_runtime.py`、`web/app.js`、`web/index.html`、`scripts/test_web_controls.cjs`。

配置/文档：`deploy/nginx/gongwei.yanyi.online.conf`（同步15M限额到原模板）、`deploy/README.md`、`STATUS.md`、`CHECK_STATUS.json`、`KNOWN_ISSUES.md`、`HUMAN_ACTIONS.md`。新增本报告及取证/受限部署脚本。服务器另修改本项目环境的日志目录和本网站上传限额；秘密环境文件不归档。

仓库还有此前阶段未提交的修改/清理记录，本轮没有用reset或覆盖来清理；本表只列本轮触及文件。

## 尚未完成

1. **平台后台访问/Message匹配**：本次21:00–24:00公开统计HTTP200未返回本项目AIC。曾发生TLS超时，单次重试200。完整AMP Message/Access安全上报/统计匹配尚未验收，公开Heartbeat不能代替。
2. **完成工单后的资源归还**：网页完成单仍有人员、工具、配件3条active预留，工具库存仍扣除。需要完成关闭/归还规则（耗材不能简单当工具全部加回），本轮未擅改业务语义。
3. **平台取消呈现**：正式SDK返回canceled、业务取消成功，但叮当DAG显示failed，未清楚展示取消成功摘要。不能把这一UI表现报告成全通过。
4. **共享服务器整机重启验收**：本项目服务重启已验，整机重启需约定窗口；不能为了验收重启其他项目。
5. **最终技术方案PDF和演示视频**：尚未生成，按本次已验证范围制作，不能宣传platform_verified=true或声音高准确率。

## 文件阅读顺序

先读本报告，再看 `flow-conclusions.json`、`task-id-correspondence.csv`、三个 `server-*.log`、`final-state.json` 和四页 `final-web-*.png`。失败与重试文件已保留；历史报告按历史日期理解。本次评审ZIP排除秘密、数据库、原始录音、环境依赖，包含代码、报告与真实截图。

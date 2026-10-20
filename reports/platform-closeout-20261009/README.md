# 工维联真实验收收尾报告 · 2026-10-09

## 1. 当前阶段与结论

当前阶段：正式梧桐调用和部署恢复的最终验收收尾。项目始终为 `G:\My Work\杂\论文单（2025）\智能体辅导\gongwei-step1`，未另建项目。

**真实业务调用链已通过**：叮当补充信息→待确认方案→用户明确确认→正式 MQ 资源预留→正式 MQ 工单创建→completed。新工单 **WO-20261009-A1044F**；实际重复确认返回同一工单，独立修改与取消也通过。

本轮修复并部署资源结算、取消业务操作、重复取消守卫及真实 AMP 协议元数据。共享服务器已实际重启并恢复。

**完整平台统计验收尚未通过**：Message 已匹配并显示三个身份；叮当→Leader 的 HTTPS Access 仍为 0。本次官方 Kafka 捕获窗口已观察到我方真实 callee，未找到对应 caller，需平台核查。保持 **platform_verified=false**，不宣称只剩 PDF/视频。

设备、人员与库存使用项目已有、明确标记为模拟的演示数据。真实的是平台网络、证书、协议、Partner执行、SQLite持久化和唯一工单结果，不表示已检修实体设备。

## 2. 身份、端点和运行模式

| 角色 | 当前真实 AIC | 正式入口 |
| --- | --- | --- |
| Leader | 1.2.156.3088.1.BUPT.JSQB3Y.RN5ERG.1KIZGN.0M45 | https://leader.yanyi.online/rpc，官方 JSON-RPC+mTLS，身份绑定 |
| 资源 Partner | 1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA | amqps://wt.ioa.pub:5671/acps?inbox=inbox_1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA |
| 工单 Partner | 1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF | amqps://wt.ioa.pub:5671/acps?inbox=inbox_1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF |

- 原批准 ACS 1.1.0 保持，不重新注册、不更换 AIC。三个身份仍使用各自证书/私钥，Leader另有有效DNS SAN serverAuth。
- 网页 https://gongwei.yanyi.online 为原 `local_rpc`；正式 Leader 与两个 Inbox Partner 使用 `platform_mq_inbox`，没有静默回退。
- Broker `amqps://wt.ioa.pub:5671`；实际可用的官方 mTLS群组鉴权 `https://wt.ioa.pub:9007`。历史443入口403不代表当前9007鉴权失败。
- 正式 Partner 选择仍显式 `platform_catalog`，从真实在线平台目录取得 ACS，目录记录 `online=false/liveness=unknown` 不冒称实时在线。默认在线精确查询另行验证，三个 AIC 均 HTTP200返回，原始响应在 `discovery-*.json`。
- 声音仍保留为可插拔22条样例冒烟辅助；未下载大型数据、未训练复杂模型。

## 3. 本轮实际修改

### 工单资源结算

`stage2_domain.py` 在同一 BEGIN IMMEDIATE事务关闭active预留：completed归还人员和可复用工具，计划使用的配件转consumed而不补回库存；failed归还全部预留。重复/并发不多退，终态不能回退，晚到reserve不能重新占用；未知资源分类回滚整个事务。旧completed订单可通过原API重复完成安全结算，无数据库迁移。

实际对已完成的 **WO-20261008-3D7B9C** 调用原状态API两次，均HTTP200。工具从1/2归还至2/2，人员释放；密封圈仍4/5，已用一件保留consumed。证据 `legacy-order-closeout.json`、`web-returned-inventory.png`。网页状态更新后重新请求真实bootstrap库存和人员，不使用静态值。

### 叮当取消与重复保护

对外新Start执行“取消待确认方案”是一个成功业务操作，返回官方completed以及业务status=cancelled、operation=cancel_plan和清晰Product；真正协议Cancel仍返回canceled，不改变协议语义。校验同会话、调用者、方案历史、无工单/无占用，保存新旧任务关联及恢复命令类型。

正式SDK诊断额外发现：已取消方案被新的wrapped Start再次取消会误进入新方案。先新增失败测试，再最小修复为明确failed，防止生成误导方案。公开mTLS实际重投通过，证据 `public-cancel-operation.json`；首次失败保留在 `public-cancel-operation-first-probe.json`。该SDK诊断使用资源身份，**不是叮当**。

### AMP 真实元数据

使用官方SDK AccessEmitter/MessageEmitter；RPC仅在SDK验证证书与senderId之后记录callee，MQ仅在验证TaskCommand/TaskResult后绑定真实taskId。MQ receive/ACK按真实delivery trace/span绑定，不使用旧messageId回填。记录不含dataItems/Product/对话/人员/工单正文/HTTP headers/凭据或异常全文。

新增受限制forwarder：固定官方broker `wt.ioa.pub:19092`、固定主题 `amp.access`/`amp.message`、当前三AIC和4个指定文件。用户已明确批准这些协议元数据通过PLAINTEXT传输；没有将AMQPS或业务RPC降级，也不声称Kafka支持TLS。

官方schema与精确字段白名单验证，符号链接/硬链接/错误所有者拒绝，只有真实Kafka ACK后fsync游标；重启/日志轮转去重。ACK与fsync之间故障窗口仍为at-least-once，可能重复同log_id，未承诺exactly-once。不创建主题、不读取秘密。

服务只读挂载三个AMP日志目录，隐藏secret/env/数据库/**备份**目录，私有state700/files600。独立审查发现备份目录遗漏后已补InaccessiblePaths；宿主28条备份、服务namespace0条，秘密备份不可见，日志可读。只重启metadata，其余8个服务PID不变。新的只读正式GET产生真实ACK partition14/offset6013，证明隔离后仍能转发；见 `metadata-hardening.json`、`metadata-after-hardening.json`。

## 4. 真实叮当三轮和幂等

当前浏览器已有账号登录完成，未将密码写入项目、日志或包。发现并只选择工维联Leader执行；隐藏分页中资源/工单Partner的直接勾选已取消，保证资源调用来自Leader的正式MQ协作。没有执行其他通用智能体。

本轮平台“上新”已滚动至其他新智能体，因此从明确发现结果选择原Leader；当前截图不冒充“上新Leader卡片”截图。原首页卡片证据属于历史验收。

session **session_1841**，已认证调用者 `1.2.156.3088.1.0001.00001.EZTK03.WCU6LR.14YT`。

| 步骤 | 外部 taskId | start messageId | 真实结果 |
| --- | --- | --- | --- |
| 首轮异常请求 | a9f43cab-d4ce-4d11-b98b-432b9bf3180f | cmd-972fa88d-8046-4c76-8a87-7fb116880795 | accepted→working→awaiting-input，询问开始时间/时长 |
| 14:00、一小时、泵体检查 | 1847721f-6b88-40cb-a658-f51d415cbeb3 | cmd-2d5baa06-c999-423f-999c-0d3530a4ff97 | 正式MQ资源查询，待用户确认，无预留/工单 |
| 明确方案编号确认 | ce6f1ce3-d1b0-4a0a-b7be-aa8b3e623184 | cmd-0ac6e41d-a69d-42f7-bc2e-7e91e7ec1651 | 正式MQ预留+工单，completed |
| 再次实际执行同确认 | cc8b5d5b-7e7d-49af-974e-3df486381bf6 | cmd-607e8cd1-4b8e-48f9-b028-371436e12e57 | completed、idempotent=true，同一工单 |

方案编号 **GW-9fe94137c776969609cf7c8469a0a16d**，方案ID `plan-4a88c9f9-ab75-4361-9a8c-90ec0d67805a`。本次用户确认句：`确认方案 GW-9fe94137c776969609cf7c8469a0a16d 并创建工单。`

工单 **WO-20261009-A1044F**，ID `wo-ac98972b-6494-43f0-b479-258c9a519179`；pump-002，2026-10-10 14:00–15:00，60分钟，模拟人员甲，机械密封圈一件、便携检查工具包一套，confirmed。

平台仍cancel旧task/start新task；**外部taskId并未保持不变**。用户已接受明确方案编号＋同session/caller校验的业务接续，旧任务不复活，持久化来源task与Partner parent关系。

### 数据库实测对照

| 时点 | 累计工单 | active预留 | 本主会话Partner子任务 |
| --- | ---: | ---: | ---: |
| 确认前 | 4 | 0 | 1（查询） |
| 确认后 | 5 | 3 | 3（查询/预留/建单） |
| 实际重复RPC后 | 5 | 3 | 3 |
| 独立修改/取消后 | 5 | 3 | 3 |

integrity_check=ok。断言真实新工单只有1张，同计划只3条active；重复确认不新增Partner业务子任务。详见 `business-flow-assertions.json`、`dingdang-before-confirm.json`、`dingdang-after-confirm.json`、`dingdang-after-repeat.json`、`dingdang-final.json`。

三个主子任务及命令关联完整CSV：`task-message-session-map.csv`；原MQ运行日志：`server-leader.log`、`server-resource-inbox.log`、`server-workorder-inbox.log`。日志使用明确UTC起始时刻过滤，Partner编号和message能对应本主任务。

### 实际时间

| 轮次 | 平台成员详情显示实际用时 | 轮询次数 | Leader working→首次业务结果 |
| --- | ---: | ---: | ---: |
| 首轮 | 2.48s | 1 | 0.020s |
| 第二轮 | 11.13s | 5 | 11.242s |
| 第三轮 | 5.41s | 2 | 7.727s |
| 重复确认 | 2.13s | 1 | 0.034s |

两个计时来源口径不同：前者为平台详情原值，后者为Leader持久状态历史间隔；不将平台显示值包装为含发现/LLM汇总的端到端总耗时。原始时间见 `response-times.json` 和round1/round2/completed/repeat-detail.txt。

## 5. 独立修改、取消、自动发现

- 独立session_1842：14:00方案 **GW-9a663421d976861db9b2cdac5683e2ec**，task4379c96b-2dec-4c05-a335-ef13086c8a1f。
- 同会话说“把检查时间改为下午三点。”，新taskfa278faf-3d12-4ab9-a6db-11bfd61744d3，正式MQ重新查询，15:00–16:00新方案 **GW-b15ff05485b2856b9d51ad593e3ab607**。没有创建或改写已完成工单，没有正式占用临时方案资源。
- 同会话说“取消任务”，taskead56793-f63f-49a1-9eab-ce42da7e5eaa，messagecmd-2b4b3b62-d342-457b-8b9d-2164088375da；官方completed，业务cancelled，Product明确“未预留资源，未创建工单”。叮当DAG绿色，成员详情显示2.63s/一次轮询。主聊天未追加独立取消摘要时，实际Product在成员详情可读；没有修改平台客户端。
- 新空白叮当会话、不指定智能体名称，发送“帮我找一个能够处理设备异常、协调检查人员和工具，并创建检查工单的智能体。”，真实自动发现推荐 **工维联核心业务 Leader**。未执行其他智能体，截图/DOM在 `dingdang-auto-discovery.png/.txt`。

## 6. 平台后台统计与未完成项

官方统计接口原响应 `platform-statistics.json`（01:00–04:00北京时间窗口）、全榜 `platform-rankings-latest.json`，浏览器实际榜单截图 `platform-leader-call-counts.png` / `platform-partner-call-counts.png`：

| 身份/榜单 | Access | Message |
| --- | ---: | ---: |
| Leader调用榜 | 0 | 20 |
| 资源Partner被调用榜 | 0 | 10 |
| 工单Partner被调用榜 | 0 | 10 |

Message数字包含SDK诊断和官方群组广播接收，不等于20张工单，也不能只凭某Partner接收到消息断言其执行业务。业务执行证据是指定action子任务、正式MQ日志和真实数据库写入。

**仍未通过HTTPS Access匹配**。01:55–02:10北京时间，本次16分区捕获107条均读取完成；三轮我方callee记录为3/7/3共13条，官方Kafka确实收到。此窗口未观察到对应叮当caller，不表示平台全部时间没有caller。官方SDK2.2.0默认caller correlation_id=sessionId与平台文档要求taskId有潜在差异，但未观察到当前叮当caller，不能断言其实际值。完整范围/白名单样本/规则出处：`amp-access-pairing-investigation.json/.md`。

我方不能生成对端caller日志或修改平台采集。需平台按真实session/task/AIC检查caller emitter、转发、correlationId、时间/身份/trace匹配条件，已写入根目录HUMAN_ACTIONS.md；本轮未擅自发管理员消息。没有关闭mTLS/身份绑定、重注册或伪造调用。

## 7. 部署与整机恢复

原release增量部署13个目标文件，随后Leader单文件守卫和独立metadata服务；没有迁移WIT/Adapter、安装Docker、购买服务器/域名或改其他项目配置。

私有备份（不进包）：

- `/opt/gongwei/backups/20261009-011144-closeout`：代码、环境、业务/RPC在线SQLite备份。
- `/opt/gongwei/backups/20261009-012543-amp-metadata`：元数据服务与依赖安装备份。
- `/opt/gongwei/backups/20261009-013124-reboot`：Nginx、9服务、SQLite和正式环境重启前备份。
- `/opt/gongwei/backups/20261009-015437-cancel-guard`：Leader守卫更新。
- `/opt/gongwei/backups/20261009-040902-metadata-hardening`：元数据服务隔离补强。

实际执行 `sudo systemctl reboot`。boot ID由 **6b8a5804-6a61-40e8-8fb8-60326c71974c** 变为 **6d3e165f-9b6a-445d-9d0b-f10b0e242564**。

9个本项目服务active/enabled：web/resource/workorder/audio/leader/resource-inbox/workorder-inbox/amp-heartbeat/amp-metadata。Nginx/MySQL/PostgreSQL/PHP-FPM/PM2/两个高考服务也active/enabled，保存PM2进程正确恢复。app/gongwei/taluo/www/xiaoyi.yanyi.online均正常HTTPS200（xiaoyi正常跳到登录页）。没有配置变更或删除其他项目。

实际重启后：正式AMQPS自动连接，Partner Inbox监听、邀约入群恢复，数据库可读写且integrity=ok。最终空闲时3条AMQPS连接并不意味着每个群组必须长期保持额外连接。重启后正式公网SDKstart/continue资源查询/取消另行通过，明确该SDK诊断不是叮当。

证据 `reboot-preflight.json`、`reboot-request.json`、`reboot-final.json`、`other-sites-before-reboot.json`、`other-sites-after-reboot.json`、`public-rpc-mq-after-reboot.json`。

## 8. 测试与实际执行命令

使用Superpowers（系统调试/TDD/计划/验证/独立审查）；库存刷新呈现使用frontend-design/Impeccable。未涉及Three.js/WebGL。

| 检查 | 实际结果 |
| --- | --- |
| 本机全量unittest | 370项，369通过，1 Windows符号链接权限跳过，无失败/错误 |
| 服务器Python3.12全量 | 369/369，无跳过/失败/错误 |
| 独立资源结算/AMP针对性测试 | 62/62 |
| 首页接续/取消守卫复核 | 36/36，独立无未关闭P0/P1/P2 |
| JavaScript语法 | node --check通过 |
| 网页控件 | 24组通过，包含状态更新后真实库存刷新 |
| 阶段二/阶段五黑盒 | 全量测试中真实启动服务执行并通过 |
| 60场景 | 60/60通过 |
| 正式公网mTLS+MQ | 重启恢复、同task continue、取消/取消重投通过 |
| 真实叮当 | 三轮、重复、独立修改/取消、自动发现通过；HTTPS Access统计仍缺项 |
| 官方本机broker测试 | 明确BLOCKED：未安装Docker/acps-infra；没有替代broker或伪造协议；正式梧桐MQ有独立真实证据 |

执行命令（项目目录）：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
node --check web/app.js
node scripts/test_web_controls.cjs
.\.venv\Scripts\python.exe reports/platform-closeout-20261009/server-regression-fresh.py
.\.venv\Scripts\python.exe reports/platform-closeout-20261009/check-default-discovery.py
.\.venv\Scripts\python.exe reports/platform-closeout-20261009/probe-cancel-operation.py
.\.venv\Scripts\python.exe reports/platform-closeout-20261009/collect-dingdang-evidence.py --phase dingdang-final --sessions session_1841 session_1842
.\.venv\Scripts\python.exe reports/platform-closeout-20261009/harden-metadata-service.py
.\.venv\Scripts\python.exe reports/platform-closeout-20261009/probe-metadata-after-hardening.py
git diff --check
```

正式进程已由systemd长期管理；各自原ExecStart与身份继续独立，日常管理命令为 `sudo systemctl status gongwei-leader gongwei-resource-inbox gongwei-workorder-inbox`。需要启动时使用 `sudo systemctl start gongwei-leader gongwei-resource-inbox gongwei-workorder-inbox`，不要在已运行时另起重复进程。

主要测试日志 `local-regression-latest.log`、`server-regression-fresh.log/.json`、`web-controls-final.log`、`cancel-repeat-red.log`/`cancel-repeat-green.log`、`closeout-red.log`/`closeout-green.log`、`independent-review.md`。

## 9. 失败记录与修复边界

- 资源结算/取消重复守卫先有真实RED，再修复GREEN；没有删除失败日志。
- 重启后首次SDK诊断仅等待3秒，首次群组建立超过这个时间导致Timeout。按实际群组初始化预算延长到50秒后通过；首失败在 `public-rpc-mq-after-reboot-first-attempt.json`。
- 取证脚本曾用旧表名/JSON字段以及Windows非UTF8读取，修正取证脚本后运行成功，不把脚本错误当成业务故障。
- 后续本机urllib默认系统代理对多个无关HTTPS站点同时产生TLS EOF；直接HTTPS仍保留证书校验，5站HTTP200。代理失败保存 `other-sites-system-proxy-failure.json`、`platform-statistics-system-proxy-failure.json`；没有改系统代理或关闭TLS验证。
- 隔离补强后空闲forwarder尚无Kafka连接属延迟初始化；新的真实只读GET产生ACK后已验证转发恢复，不用仅进程active冒充转发通过。
- 当前平台缺caller匹配仍如实保留，未将Message匹配说成HTTPS Access已通过。

## 10. 修改文件与交付

运行代码：`stage2_domain.py`、`leader_external_flow.py`、`leader_rpc_runtime.py`、`plan_continuation.py`、`mq_group_transport.py`、`mq_partner_runtime.py`，新增 `amp_telemetry.py`、`amp_metadata_forwarder.py`。

前端仅必要修复：`web/app.js`、`web/index.html`。未再次重做界面或增加业务功能。

测试：新增 `test_work_order_closeout.py`、`test_amp_telemetry.py`、`test_amp_metadata_forwarder.py`；更新取消兼容/恢复的 `test_homepage_continuation.py`、`test_leader_rpc_runtime.py`、`test_leader_external_flow.py`及库存控件 `scripts/test_web_controls.cjs`。

部署：新增 `deploy/systemd/gongwei-amp-metadata.service.example`、`deploy/requirements-amp-metadata.txt`，更新 `deploy/README.md`。官方aiokafka0.12仅安装到已有项目venv，安装输出保存，不改其他项目环境。

状态/说明：`CHECK_STATUS.json`、`README.md`、`STATUS.md`、`KNOWN_ISSUES.md`、`HUMAN_ACTIONS.md`、`docs/superpowers/plans/2026-10-09-platform-closeout.md`、本报告目录的真实日志、截图、调查、部署与取证脚本。旧Git工作区已有历史修改，本清单不是把所有历史差异算为本轮。

最新评审包：`reports/gongwei-platform-closeout-review-20261009.zip`；先读本报告。包排除secrets、环境变量秘密、私钥、证书、Token、SQLite数据库、原始录音、依赖环境和服务器私有备份；包含脱敏业务证据及公开AIC。CRC、逐文件SHA256和秘密格式扫描结果见 `package-result.json`。

仍需完成：平台叮当caller Access匹配；技术方案PDF；演示视频。证书应在2026-11-24到期前续签。无需因统计缺项再次删除或重新注册智能体。

## 11. Access 配对修复与线上复测（2026-10-09/10）

针对项目端可能丢失上游链路的问题，`leader_rpc_runtime.py` 现在在进入官方 `handle_rpc_request` 前读取 W3C `traceparent`，并在请求结束时清理请求上下文；`amp_telemetry.py` 将该 trace 作为 callee 子 span 写入 AMP Access。这样不会替叮当生成 caller 记录，也不会把本地 callee 当成平台 caller。

修复已部署到 `/opt/gongwei/releases/20261007-120338-maintenance`，Leader 编译、systemd 重启和健康状态均通过。线上正式 mTLS 探针使用独立资源 Partner 身份，只发送一条缺少时长的启动请求并立即取消：`accepted → working → awaiting-input → canceled`，工单数、有效预留数和 SQLite integrity 均保持不变。探针不是叮当调用，证据见 `traceparent-probe.json`。

线上 Leader 的新 Access 日志已包含同一 `trace_id`、上游 `parent_span_id`、新 callee `span_id` 和真实 `taskId`；元数据 forwarder 也收到两条新 Access 并获得官方 Kafka ACK。证据见 `traceparent-access-sample.json` 和 `metadata-traceprobe.log`。因此项目端的 HTTPS 接收、trace 传递、AMP 写入和转发链路已验证。

复测时平台 `matched-stats` 接口仍返回 HTTP 200，但统计物化时间尚未覆盖新探针窗口，Leader 的公开 HTTPS Access 仍为 0；该探针也不是叮当 caller，不能用它冒充平台外部调用。平台仍需按真实叮当 caller AIC、真实 taskId、AMP Access 入库和双侧匹配规则核查，`platform_verified` 保持 `false`。

## 清理记录（2026-10-10）

本轮将 8 个旧评审压缩包和测试后重新生成的 5 个项目 Python 缓存目录移出活动目录，放入 `archive/cleanup-hold-20261010/`，避免它们继续混入项目和评审包。最新评审包保留在 `reports/gongwei-platform-closeout-review-20261009.zip`。数据库、源码、正式报告、运行日志、秘密、证书、部署配置和服务器备份均保留。

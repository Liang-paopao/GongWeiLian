# 发现、MQ、AMP 与测试入口独立审计

审计日期：2026-10-07。技能：Superpowers、systematic-debugging、test-driven-development、verification-before-completion。未读取或输出真实 secrets 内容，未启动真实平台 MQ 消费者，未修改平台管理数据、Redis、alive-delta 或全局服务。涉及身份的输出仅为公开 AIC 和公开 ACS。

## 本地已复现并修复

- `mq_group_transport.py`：SDK 2.2.0 的待处理邀请以 Partner AIC 为键，两个会话同时首次初始化会得到 `already has a pending invitation`；同会话并发还会重复创建 SDK 会话。只序列化群组创建与邀请，已就绪会话保留快速通道和任务并发。
- 同文件：SDK 每五分钟检查并回收闲置一小时的群组，而本地原 `_ready_sessions` 不会随之失效。现在重新核对实际 SDK session，回收后可重建；失败、取消清理半成品群组。关闭时取消待处理初始化并调用 SDK 清理，不等待其默认 300 秒邀请超时，也不允许关闭后重新开组。
- `platform_runtime_config.py`、`.env.example`：原默认地址仍是 `https://wt.ioa.pub/mq-auth/`，与已实测可用的直接 mTLS Group ACL API 不一致。改为 `https://wt.ioa.pub:9007`，保留显式配置优先级。该问题影响新环境默认启动，不能解释当前已配置 9007 的线上发现空结果。
- `run_stage2_tests.py`、`run_stage5_tests.py`：显式 `local_rpc`/`local`，清空子进程 Discovery URL，分配随机回环端口，服务与业务日志保存到 `reports/local-test-runs/<独立目录>/`。阶段五改用系统临时数据库，不再删除 `data/stage5_test.db` 及其 WAL/SHM。阶段二逐一登记启动的进程，修复第二个启动失败时第一个进程无法清理的问题。
- `scripts/run_60_scenarios.py`：继续使用临时数据库，日志单独保存到报告目录，执行期间限定本机传输并在结束后恢复调用方环境与日志配置。

## 发现链路的新证据

见 `discovery-independent-readonly.json`。在同一端点 `/discovery/acps-adp-v2/discover`，分别对三个当前 AIC 使用 `active=true AND skills.id=<对应技能> AND aic=<精确身份>`：

|角色|默认在线查询|仅增加全状态 alive 扩展过滤|
|---|---|---|
|Leader|HTTP 200，候选为空|HTTP 200，返回当前 Leader 与匹配技能|
|资源 Partner|HTTP 200，候选为空|HTTP 200，返回当前资源 Partner 与匹配技能|
|工单 Partner|HTTP 200，候选为空|HTTP 200，返回当前工单 Partner 与匹配技能|

全状态响应均未携带 `aliveMap`。因此本轮独立验证支持：AIC、active、技能字段、请求路径与 SDK 结果遍历逻辑成立；默认在线候选仍不可得。不能把目录中存在等同在线，也不能声称本地代码修复了平台在线状态发布。

`amp_runtime.py` 使用安装的官方 `HeartbeatEmitter`。源码明确输出 `schema_version=1.0`、`log_type=heartbeat`、AIC、时间戳、`body.uptimeSeconds`，不要求心跳签名。项目 Forwarder 转发完整原始字节并使用官方常量对应的 `amp.heartbeat`，不向 `amp.heartbeat.alive-delta` 写入。SDK 的 `heartbeat_sync.py` 明确区分这两个 topic。未发现能解释当前在线查询空结果的字段或 topic 拼写问题。本轮未重新执行 Kafka 投递/回读，既有 ACK、Writer 游标与 checkpoint 证据应以原实测记录为准。

## 交给主审计的其他问题

- 已确认 `scripts/build_hybrid_leader_acs.py` 使用旧注册的 `.VGHKB0.B2TPFE.09ZF`，并覆盖共享草稿。当前正式 Leader 为 `.RN5ERG.1KIZGN.0M45`。主审计负责修复生成器身份来源。
- `scripts/build_platform_acs.py` 使用不存在的 `platform/acs` 源目录。主审计负责历史工具处置。
- SDK `GroupPartnerMqClient` 本身持有一个群组状态：`_join_group_common` 覆盖 `_group_id/_exchange/_queue`，旧消费者和回包还会读取这些字段。项目原 Partner Runtime 只创建一个该 client，第二个群组可导致串组。此问题已交给另一个审计任务实现每组独立官方 client；本报告不把该项计入本子任务已完成修复。
- `deploy/stage_platform_preflight.py`、`stage_hybrid_release.py`、`verify_platform_staging.py` 仍指向历史 `20261006-hybrid` 和旧 secrets 布局；属于历史操作脚本，不应作为当前部署入口。未执行。

如果业务需求允许“平台实时目录发现 + 官方 mTLS 实际能力探测”，可以用明确标注的降级路线继续业务，并保留 `online=unknown`、`platform_verified=false`。它不能替代“默认在线 Discovery 可发现”的验收要求；当前严格在线选择未被放宽。

## 验证结果

- 初次修复红测：8 项中 7 项失败，分别对应真实 SDK 并发冲突、过期会话、失败/取消清理、关闭重开和默认 URL；见 `mq-discovery-red.log`。
- 快速通道补充红测：已有会话被另一会话邀请阻塞；见 `mq-ready-session-red.log`。
- 最终 MQ/身份相关用例：25 项通过，见 `mq-discovery-green.log`。
- 发现、AMP、身份、MQ、Leader RPC/Inbox、外部业务等 12 模块回归：139 项通过，1 项因 Windows 无法创建 symlink 跳过；见 `mq-discovery-related-regression.json`。该轮之后补充的快速通道已在上述 25 项中验证。
- 测试隔离红测：4 项测试出现 5 个预期失败点；修复后 4 项通过，见 `test-entrypoints-red.log`、`test-entrypoints-green.log`。
- 实际顺序运行 `run_stage2_tests.py`、`run_stage5_tests.py`、`scripts/run_60_scenarios.py`，全部退出 0，60/60 场景通过；见 `isolated-blackbox-results.json` 和对应 `*-isolated.log`。
- `git diff --check -- <本次文件>` 通过；8 个修改的 Python 文件经 `ast.parse` 通过。Git 仅提示既有 Windows CRLF 转换设置。

## 检查覆盖

直接阅读并追踪：`partner_resolver.py`、`amp_runtime.py`、`amp_heartbeat_forwarder.py`、`mq_group_transport.py`、`platform_runtime_config.py`、`transport_mode.py`、`stage2_aip.py`、`stage3_leader_aip.py`、`leader_external_flow.py`、`local_log.py`、全部 `run_*.py`、`.env.example`、`pyproject.toml`、README、平台 README、本机启动脚本、`scripts/run_60_scenarios.py`、四个 ACS 生成脚本、Discovery/身份诊断脚本、部署环境示例、三个正式业务 systemd 单元、心跳单元、依赖清单、心跳安装脚本及历史 staging/preflight 脚本。

直接阅读或运行相关测试：`test_partner_resolver.py`、`test_amp_runtime.py`、`test_amp_heartbeat_forwarder.py`、`test_platform_runtime_config.py`、`test_mq_group_transport.py`、`test_partner_inbox_entrypoint.py`、`test_platform_diagnostics.py`、`test_transport_mode.py`、`test_stage3_leader_aip.py`、`test_leader_inbox_runtime.py`、`test_leader_rpc_runtime.py`、`test_leader_external_flow.py`，以及新增 `test_local_test_entrypoints.py`。

本机安装元数据核对版本为 `acps-sdk==2.2.0`。核对 SDK 的 ADP models/constants、AMP heartbeat_emitter/models/heartbeat_sync/alive_sync models与engine，以及 AIP group_leader/group_partner/group_runtime/group_auth 和 AIC 格式校验；只在测试中替换网络 I/O，保留真实 SDK 邀请状态机。未宣称阅读 SDK 所有无关模块，未通过修改 SDK 或平台状态来制造通过结果。

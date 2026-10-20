# 音频、旧入口、Web 连接、文档与本机生命周期审查

日期：2026-10-07。本文件记录本子审查范围；完整项目结果以本目录最终汇总为准。

## 审查与操作边界

- 使用 Superpowers、systematic-debugging、test-driven-development、verification-before-completion；Web 代码审查参照 frontend-design / Impeccable，只检查功能连接与内容边界，没有重新设计视觉。
- 未读取或输出 secrets 中的凭证内容；未改服务器、注册身份、正式数据库或平台配置；未运行声音训练、数据下载、注册或部署脚本。
- 没有删除数据库、上传音频、模型、MIMII 样例或文档。本机四服务实测使用随机空闲端口、临时数据库与日志目录，退出后测试端口全部释放。

## 已修复

1. **启动/停止进程归属与退出码。** 原 `stop_stage2.cmd` 固定端口并直接强制终止监听者，会漏停自定义端口服务或误伤其他程序。现 `scripts/local_services.py` 记录本项目启动的 PID、创建时间、可执行文件和包含绝对项目目录的命令行。停止前全部核对，持有目标进程句柄，身份不符则保留记录并返回非零。不会接管或终止未知监听者。原有 CMD 入口保留。
2. **真正等待健康。** 启动依次核对三个 Partner 和 Leader 的 `/health` 身份及 `status=ok`；失败时只回收本次创建的进程，返回非零。重复启动只接受配置一致且身份、健康均匹配的记录。`setup_windows.ps1` 检查 Python 编译退出码，只遍历项目源码，避免递归扫描依赖和历史副本。
3. **音频单测隔离。** `test_audio_partner.py` 原先直接写默认业务数据库和上传目录；`test_audio_pluggable.py` 虽有临时数据库，仍写默认上传目录。现分别隔离数据库、上传、日志，或隔离上传目录，均使用 `TemporaryDirectory` 与清理回调。既有文件未按“疑似测试残留”删除。
4. **MQ 多群组结果串线。** 实际安装的官方 `GroupPartnerMqClient` 在入群时覆盖 `_group_id`、`_exchange_name`、`_queue_name`，任务结果也读取同一实例字段。原 runtime 复用一个实例，红测证明 group-a 的结果会使用 group-b。新 `mq_partner_runtime.py` 保留独立 Inbox client，为每组创建独立官方 client 与回调，通过 `ContextVar` 兼容既有 `runtime.client` 调用。不同协程不会切换共享的当前 client；同组邀请复用，组身份不可替换，断连可重入，拒绝/失败回收子 client，关闭取消 pending joins 并关闭全部客户端。`mq_group_transport.py` 仅移除旧 runtime 类并重新导出新类，其余并行修复保留。
5. **过期文档。** 业务数据库版本更正为 4；本机指南改为当前对话与独立音频提示流程；说明新启动器的安全停止规则；技术报告/PPT 大纲不再使用历史测试数量或“没有 AIC/证书/公网证据”的旧说法；`SOURCES.txt` 如实说明既有 MIMII 样例、来源记录和轻量模型。

## 音频功能与数据保留

运行链仍为 `web/app.js` → `/api/audio/analyze` → Audio Partner → `audio_service.py` → `audio_detector.py`。默认模型为 `models/audio/mimii_pump_baseline.json`，审查时大小为 3,432 bytes。它属于运行资产，不是可随训练取消删除的缓存。

`audio_data.py`、`audio_detector.py`、`audio_service.py`、`audio_partner_v1.py`、全部音频测试、`data/mimii_pump/{manifest.csv,source.json,splits.json}`、样例 WAV 和训练准备源码均保留。检测仅依赖已解码波形，文件名和 normal/abnormal 路径标签不传给检测器。安全结果只允许“未发现明显异常”或“疑似异常”；分析与确认本身不直接创建工单。页面当前仅展示检测结果，后端 `/api/audio/confirm` 仍存在。

审查发现 `analyze_wav_bytes` 使用 `soundfile.read` 全量解码后才检查时长，并可接受 FLAC。一次纯内存复现以 10,448-byte 的 1 秒 FLAC 获得分析结果，说明“WAV only”限制未落实；压缩音频也有先解码再检查的资源放大风险。此项已交主审处理，不将源码审查等同已修复。下载工具 `prepare_mimii.py` 的 ZIP member 输出路径未显式验证位于 OUTPUT 之内，Range 返回内容也未验证完整长度；本轮未执行该工具。

## 清理时不能按目录名称推断“无用”

| 路径 | 实际依赖 | 处理要求 |
|---|---|---|
| `reports/platform_mq_acs/*.json` | `partner_resolver.py` 的本地候选，`build_mq_acs.py` / `build_agentic_acs_draft.py`；`test_mq_acs.py` 间接读取 | 必须保留；它是运行和测试输入 |
| `reports/acs_1_1_0_draft/*.json` | 混合 ACS 构建、历史比较及评审脚本读取 | 保留并明确历史/草稿属性，不自动提交 |
| `reports/hybrid-platform-20261006/leader-approved-acs.json`、`leader-acs-1.1.0.json` | `build_hybrid_leader_acs.py`、`deploy/stage_hybrid_release.py` 明确引用 | 不可仅因日期旧删除 |
| `models/audio/mimii_pump_baseline.json` | 音频分析及 Audio Partner 健康接口 | 必须保留 |
| `data/resources.json`、`data/stage2_seed.json` | 旧只读入口、数据库初始化和回归测试 | 必须保留；数据明确标为模拟 |
| `data/mimii_pump/` | 模型来源、样例和可复核的离线准备/训练输入 | 保留；本轮没有重新训练 |
| `docs/` 和相关报告 | 未发现本范围 runtime/单测直接读取 docs；多个评审脚本按白名单打包它们 | 文档可更新，不能把“无运行读取”当成可删除授权 |
| `data/stage2.db`、`data/audio_uploads/` | 已持久化业务和用户上传，单测历史也可能混在其中 | 不依外观推断来源，不删除 |

`scripts/build_platform_acs.py` 仍使用不存在的 `platform/acs/` 作为模板目录；提供完整参数后会找不到模板。已交主审处理。旧的固定白名单评审脚本可能漏掉新模块；最新评审脚本会收集根目录 Python 文件，但通常排除模型。因此历史评审 ZIP 不能宣称可直接运行全部功能。

## Web 与旧入口检查

- `web/app.js` 的业务数据来自 `/api/bootstrap`、`/api/work-orders`、对话/任务、音频和审计 API。主要插入 HTML 的后端字段经 `esc()` 转义，没有发现执行字符串代码、硬编码业务凭证或用本地硬编码人员/工单替换 API 的代码。
- 原工单设备/状态下拉控件没有 change 事件，原健康标记也将存在静态候选记录当作在线；两项均已交主审修复。此处记录初始发现，最终状态以最终代码和总回归为准。
- `agent_core.py` 是兼容导出；`business.py`、`leader.py`、`resource_agent.py` 仍服务旧 01/02/03 本机演示和对应测试，不是可直接删除的重复模块。旧 Partner 有回环限制，业务数据须为 `simulated=true`，Leader 失败返回非零，不冒充平台成功。
- 本范围的凭证形状扫描没有发现需输出值的命中；这仅是所读源文件的静态检查，不代表对 secrets 内容进行过扫描。

## 实际读取范围

完整/主体代码阅读：全部 `audio*.py`、上述音频测试、`agent_core.py`、`business.py`、`leader.py`、`resource_agent.py`、`test_business.py`、`test_runtime_config.py`、`test_final_audit_features.py`、`web/app.js`、`web/index.html`、`web/styles.css`、01/02/03 CMD、启动/停止 CMD、Windows setup/start/stop/test 入口；MIMII 准备/训练、60 场景、ACS 构建与评审打包脚本。

相关接口/依赖阅读：`web_app.py` 音频、状态、页面及 API 路由，`stage2_db.py` 路径/迁移/表结构，`stage2_aip.py` 端口配置，`local_log.py`，资源/工单 Partner 健康接口，`partner_resolver.py` ACS 路径，`mq_group_transport.py` runtime 和业务 handler，`leader_inbox_runtime.py`、`run_partner_inbox.py`、相关 probe 调用点；官方 SDK 的 Inbox 消费、join、send result、disconnect 和 close 实现。

文档：README、PRODUCT、DESIGN、SOURCES、docs 下 agent-contracts、database-schema、security、state-machine、observability、user-guide、final-technical-report、demo-scenarios、demo-video-script、final-architecture、final-presentation-outline。其他 docs、reports、deploy 文件按代码引用检索，deploy Python 文件做语法解析；未把引用检索声称为每份历史报告全文审读。

## 验证证据

- 原 5 项启动管理红测、6 项 MQ 群组红测先失败，分别证明安全启动器缺失和群组结果串线，再实现修复。
- 28 项音频/旧入口/启动管理定向测试通过：`audio-and-local-tests.log`。
- 51 项 MQ Partner、Group coordinator、Partner 入口、Leader Inbox 和 AMP 关联回归通过：`mq-partner-isolation-tests.log`。使用临时 DB/log，未连接真实 broker。
- 四服务随机端口启动、重复启动、停止均返回 0，停止后无残留测试端口：`local-launcher-integration.json`。
- `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/setup_windows.ps1` 返回 0；所查 Python 文件 AST 解析、`node --check web/app.js`、范围内 `git diff --check` 通过。仅有已有 Starlette/httpx 弃用提示、Windows Git 换行提示和故障测试预期日志。
- 本子审查没有部署这些修改；正式 MQ 多群组行为仍需要后续在获准的平台环境验收。本机与离线测试不改变 `platform_verified=false`。

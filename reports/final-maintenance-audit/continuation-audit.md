# Leader 与业务续接独立审计（2026-10-07）

使用 Superpowers / systematic-debugging / test-driven-development / verification-before-completion。先只读审计；收到主审授权后实施下面的小修复。没有读取或修改 secrets，没有访问或修改线上服务器/平台，没有修改前端文件。

## 已复现并修复

1. **fresh MQ Inbox start 无法建立业务任务**：真实 `handle_external_command` 在空临时 DB 下报 `no such table: agent_tasks`；初始化 DB 后报“外部任务不存在或已过期”。现仅 start 可创建；非 start 必须已有任务。调用方 AIC 与入口以 `protocol_owner` 持久记录于任务上下文，拒绝接管浏览器/RPC已有 session/task，也拒绝其他调用者在重启后续接。外部 task/session/message 原值保留。
2. **取消终态被错误回报**：外部取消原返回 completed，Inbox 无 canceled 映射；现统一 SDK canceled，后续命令只重返 canceled，不发送 accepted/working。
3. **网页取消后可再确认建单**：原复现 cancelled → completed，创建 1 工单和 3 条 active reservation。现拒绝取消/失败任务确认；取消先调用既有领域取消/释放事务，已完成工单保持不可取消，等待中的确认不能覆盖取消结果。
4. **旧 message 重放覆盖更新**：m1=14:00、m2=15:00、重放 m1 原恢复成14:00。现命中持久消息回执返回当前快照，不重新解析/更新字段；也覆盖解析期间另一个请求提交的交错情况。消息已提交但请求创建中断时从当前上下文恢复。
5. **required_skill 被忽略**：请求 `nonexistent_special_skill` 原得到 `available=true, workers=[worker-01], required_skill=pump_inspection`。根因 `_resource_preview` SQL 参数固定常量。现按请求技能筛选，空值保留原默认；既有“泵体检查”与“电气检查”映射到 seed 技能；未知技能返回无人员。

## 测试证据

- 审计基线：86 项既有后端测试全部通过，新增问题未被原测试覆盖。
- `continuation-red.log`：7 项新回归，8 个失败断言，覆盖真实缺陷。
- `continuation-edge-red.log`：6 项边界回归，其中5项失败，覆盖技能、终态、恢复和交错重放。
- `continuation-green.log`：21 项通过。
- `continuation-edge-green.log`：37 项通过。
- `continuation-regression.log`：98 项通过，0失败、0错误、0跳过。
- 9 个改动源码/测试文件 `compile(..., 'exec')` 语法检查通过；限定文件 `git diff --check` 通过，仅 Git LF/CRLF 提示。

回归入口为项目 `.venv/Scripts/python.exe -X utf8 -B`，用 `unittest.defaultTestLoader.loadTestsFromNames` 运行以下模块，并将 GONGWEI_LOG_DIR 与各测试数据库置于 TemporaryDirectory：

```text
test_leader_rpc_runtime test_leader_external_flow test_leader_inbox_runtime
test_agentic_core test_stage2_domain test_stage2_api test_business_actions
test_stage5_resilience test_stage3_leader_aip test_final_audit_features
```

## SDK 2.2.0 语义核对

本机 `.venv/Lib/site-packages/acps_sdk-2.2.0.dist-info/direct_url.json` 指向官方 `https://github.com/AIP-PUB/ACPs-community/archive/refs/tags/v2.2.0.zip`。核对安装的官方源码 `aip_base_model.py`、`aip_rpc_model.py`、`aip_rpc_client.py`、`aip_rpc_server.py`、`aip_group_partner.py` 和 `aip_group_leader.py`：

- 状态 wire 值是 awaiting-input、awaiting-completion、canceled；当前 RPC 构造 SDK枚举后正确序列化。
- TaskStatus/Product 的 dataItems 正式允许 TextDataItem 和 StructuredDataItem；SDK `GroupPartnerMqClient.request_input` 本身只发送 TextDataItem 提示。没有 requiredFields 必填字段，故不能把 text-only 判为叮当 cancel/start 的已证实原因。
- SDK continue_task保留调用方 session/task，start 已有 task 应返回当前快照；取消不覆盖 completed/failed/rejected/canceled 终态。当前公网 RPC 的持久化、owner、receipt、终态/补偿回归通过。
- `AipRpcClient.complete_task` 不携带用户文本；默认 complete 在 awaiting-completion 状态转 completed。项目待业务确认方案目前用 awaiting-completion、刻意忽略空 complete，这与默认完成握手有语义差异。建议后续评估用 awaiting-input + 明确确认问题接收人类确认；本轮未改既有接口合同，更不能将此推断为首轮换 task 的原因。
- `state_mapping.py` 使用下划线/double-l cancelled 的内部词汇，当前无生产调用者；不能将其当成 wire 状态使用。

## 仍需主审判断的限制

- 已有证据的叮当 session_1701 先 cancel 再 start 新 task，不能伪装成同一 task续接。SDK公网start→continue通过不代表叮当编排通过。
- 在线Partner发现为空是实际业务阻断，应修真实发现/状态发布或消费者契约，而非跳过发现/改外部ID/复活终态。
- `leader_external_flow._payload` 目前只消费首个 TextDataItem；官方允许多dataItems和StructuredDataItem。未找到它触发本次叮当故障的证据，未擅自扩展业务格式。
- 备用 MQ Inbox 尚没有 RPC runtime那套完整 durable command snapshot/排队补偿机制；本轮补上fresh start和owner边界，没有声称全部MQ恢复语义等同RPC。
- 网页 revise_task 仍只按 session找最新任务，若同session拥有多个task会存在目标歧义；未列入本轮授权修复。

## 审閱范围

源码：leader_rpc_runtime.py、leader_external_flow.py、leader_inbox_runtime.py、agentic_core.py、stage2_domain.py、stage2_db.py、stage2_business_actions.py、web_app.py、stage2_aip.py、stage3_leader_aip.py、local_log.py、state_mapping.py、llm_provider.py、run_leader_rpc.py、run_leader_inbox.py、leader.py，以及MQ adapter相关调用边界。

测试：上面10个回归模块；同时核对 README.md、ARCHITECTURE.md、pyproject.toml、data/stage2_seed.json和现有规格/入口说明。测试只使用临时数据库、模拟传输边界与本机mTLS回环，不调用线上系统。

## 追加授权：音频与数据准备输入边界

改动 audio_detector.py、test_audio_detector.py、scripts/prepare_mimii.py，并新增 test_prepare_mimii.py：

- `analyze_wav_bytes` 先打开 SoundFile 读取头信息，拒绝非WAV/WAVEX/RF64、与模型不匹配或超过192kHz的采样率、1–8以外的声道数、0.25–30秒以外的帧数；float32预计解码（含一个额外探测帧）最多32MiB。检查完成后才有界读取；实际解码帧数不一致也拒绝。
- ZIP写入前统一通过 `_safe_member_target`；拒绝绝对路径、`..`、Windows drive/UNC/ADS，最终resolve必须位于OUTPUT内，现有符号链接指向外部也无法通过。
- HTTPRangeReader先校验206和完整Content-Range，再最多读取期望长度+1；短/长响应均失败且不缓存，并拒绝无进展read循环。
- `audio-input-red.log`：5项测试，8个失败断言，先确认原解码和路径/Range边界缺失。
- `audio-input-green.log`：5项边界测试通过。
- `audio-input-regression.log`：16项音频与数据输入回归通过。只使用内存合成音频、临时目录、伪造HTTP响应及现有模型推理；没有下载数据、运行训练或改写模型。

音频回归模块：`test_audio_detector.AudioDecodeBoundaryTests test_prepare_mimii test_audio_data test_audio_flow test_audio_partner test_audio_pluggable`。到此停止新增审计范围。

## 浏览器验收发现的修改时间故障

主审在隔离网页复现“初始异常 → 补14点/1小时/泵体检查 → 改到下午三点”返回500。日志确认 `create_plan` 在持有写事务时对已有方案调用 `get_plan`，后者初始化数据库再次请求写锁。新增3项测试先复现数据库锁、描述覆盖和真实修改请求500，证据 `browser-revision-red.log`。

修复仍限既有流程：

- `create_plan` 的已有方案查询在外层事务释放后返回，重复调用不再嵌套写锁。
- 网页资源查询以message派生稳定的独立子task，并记录父子关系；新修改使用新子task，避免SDK返回旧时段缓存。
- 已有方案用新资源预览 `replan_request`，保留主task和plan ID、增加version；返回的request嵌套plan也同步最新版本。
- 时间/时长/技能补充保留原异常描述；明确新异常或症状才更新description。

测试使用真实领域函数和按子task缓存的传输替身；将原人员的可用时间截止在15点，验证14点修改到15点后重新选中worker-03，而不是使用worker-01旧查询。未占用任何真实资源。

`browser-revision-green.log`：3项通过。`browser-revision-regression.log`：101项后端通过。随后补上返回快照一致性断言（`browser-revision-snapshot-red.log`先确认旧嵌套版本为1而新plan为2），修复后的最终相关回归 `browser-revision-final-green.log`：44项通过。主审可重启隔离网页复测。

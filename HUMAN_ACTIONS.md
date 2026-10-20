# 当前平台/人工处理项（2026-10-11）

## 最后一个平台闸门：叮当 caller-side HTTPS Access

本轮真实叮当会话为 `session_1988`，调用方 AIC 为
`1.2.156.3088.1.0001.00001.EZTK03.WCU6LR.14YT`，新 Leader AIC 为
`1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9`。Kafka 官方 `amp.access`
只读扫描在 2026-10-10 18:50–19:06 UTC 找到 18 条 Leader callee 记录，包含真实
taskId、HTTP 方法和 200 响应；项目侧 forwarder 已取得 ACK。

但同一窗口的梧桐 `matched-stats` 仍显示 Leader16、资源8、工单8 为 Message，三方
`accessCount=0`，并且扫描中没有发现叮当作为独立 emitter 的 caller-side Access 记录。
这不是项目可以安全伪造或通过重发解决的问题。请平台管理员按上述 session、caller AIC、
Leader AIC 和真实 taskId 检查叮当 caller emitter、入库路由、匹配键和统计分类；确认
叮当调用应按 Message 统计时，也请书面确认该产品规则。未收到平台核对结果前保持
`platform_verified=false`。

最新证据：`reports/platform-final-acceptance-20261011/README.md`、
`amp-access-kafka-current.json`、`platform-statistics-current.json`。

## 已完成且无需人工处理

- 三个智能体均已审核通过，不需要删除、重新注册、重新申请 AIC 或证书。
- 默认在线发现、自动发现、三轮叮当业务、两个 MQ Partner、唯一工单和幂等均已真实通过。
- 服务器和九个工维联服务已恢复运行，项目侧没有待输入密码、验证码或私钥的操作。

---

## 需平台核查：叮当 HTTPS Access caller 配对

我方已完成真实采集、官方Kafka ACK、Message双侧匹配和新三轮调用。平台 HTTPS Access仍0。请平台按以下真实标识核查叮当caller emitter、日志转发、接收/匹配过滤与correlationId：

- session_1841；caller AIC `1.2.156.3088.1.0001.00001.EZTK03.WCU6LR.14YT`。
- Leader AIC `1.2.156.3088.1.BUPT.JSQB3Y.RN5ERG.1KIZGN.0M45`。
- taskId：`a9f43cab-d4ce-4d11-b98b-432b9bf3180f`、`1847721f-6b88-40cb-a658-f51d415cbeb3`、`ce6f1ce3-d1b0-4a0a-b7be-aa8b3e623184`。
- 时间：2026-10-09 01:55–02:10北京时间（17:55–18:10Z前一日）。官方amp.access全部16分区/107条读取完成，其中三个任务callee为3/7/3条，未在该窗口找到caller。
- 官方SDK2.2.0默认caller用sessionId而平台文档要求taskId，仅为潜在差异：本轮未观察实际叮当caller，不断言其当前值错误。网站完整匹配规则尚未公开。

完整范围/样本/限制：reports/platform-closeout-20261009/amp-access-pairing-investigation.json/.md。没有向管理员发送消息，没有代造caller，没有上传对话或人员/工单正文。

## 项目端修复已完成，仍需平台核查（2026-10-10）

- Leader HTTPS 路由已部署 `traceparent` 透传；线上 mTLS 只读探针已在 `awaiting-input` 后取消，未创建工单或预留资源。
- Leader callee Access 已写入 `trace_id`、`span_id`、`parent_span_id` 和真实探针 `taskId`；元数据 forwarder 收到两条新 Access 并取得 Kafka ACK。
- 探针 caller 是资源 Partner，不是叮当；因此不能用它填充叮当 caller Access。平台统计在新窗口仍为 HTTP 200/Access 0，且 `accessComputedAt` 尚未覆盖该窗口。
- 请平台按真实叮当 caller AIC `1.2.156.3088.1.0001.00001.EZTK03.WCU6LR.14YT`、Leader AIC、三轮真实 taskId、caller emitter、入库状态及匹配 key 核查。项目侧没有权限生成或修改平台 caller 记录。

证据：`reports/platform-closeout-20261009/traceparent-probe.json`、`traceparent-access-sample.json`、`metadata-traceprobe.log`、`platform-statistics-after-traceprobe-wide.json`。

## 无需再次处理的旧事项

- 已按授权使用已有凭据完成叮当登录，未保存密码到项目/日志/压缩包。
- 三个身份/证书/默认发现有效，无需重新注册。
- 已实际执行授权的整机重启，9服务及其他项目恢复，不再等待重启许可。
- 已修复终态资源结算，取消操作绿色completed真实通过。

技术方案PDF与演示视频待制作；平台统计缺项完成前保持platform_verified=false。证书应在2026-11-24到期前续签。

## 以下为之前的历史处理记录

# 当前平台与人工处理项（2026-10-08）

- **叮当登录与业务验收已完成**：本轮已实际登录，新三轮、重复方案确认、独立修改/业务取消通过；不需要再次登录、注册或申请证书。首页taskId变化使用用户批准的明确方案编号接续。
- **平台统计链路**：公开统计在已知真实调用时段仍无本项目 AIC。需核对完整 AMP Access/Message 安全传输与匹配要求；本轮未发送管理员消息，不能用本地日志代替平台访问统计。
- **整机重启验收**：服务器承载其他项目，本轮不擅自重启。8 服务均已 enabled；需要约定共享服务器重启时段，执行并补恢复证据。
- **资源关闭规则**：完成工单后工具尚未归还，应明确可复用工具归还与消耗品扣减规则，再补实现和验收；本轮未自动释放已完成单或直接改数据库。
- **平台取消呈现**：SDK canceled在叮当DAG中显示failed。已保存实际业务取消成功证据，可将问题交平台核对；助手未代发管理员消息。
- **最终材料**：技术方案 PDF 和演示视频尚待制作；在上述平台闸门完成前不得宣称平台全部验收通过。
- 三个默认在线发现已本轮再次确认，无需重新注册或申请证书；保持 `platform_verified=false`。

最新证据：reports/final-flow-check-20261008/README.md。本次统计查询时间窗21:00–24:00，最后重试HTTP200但未返回本项目AIC；不代表无内部日志。证书当前有效至2026-11-24，正式运行须到期前续签。

## 以下是 2026-10-07 的记录

- 首页方案编号确认已真实创建 WO-20261007-8DC4AC，两个正式 MQ Partner 均完成；无需重新注册、重申证书或重复输入密码。
- **待平台配额恢复**：同会话再次投递相同方案确认，以及独立修改/取消任务的浏览器复测，被“今日使用次数已达上限”拦截。可等待配额恢复，或由本人联系管理员增加额度；本助手未发送管理员消息，也未绕过配额。
- **后台统计**：公开匹配统计未检出本项目，需要核对 AMP 业务消息/访问记录链路；已有三角色日志和数据库证据，不能替代平台统计闸门。
- **同 taskId**：用户已接受方案编号接续，当前业务链路已通过。若仍要求协议 taskId 不变，需平台客户端改变 cancel/start 行为。
- 三个 AIC 默认在线发现已恢复。整体 `platform_verified=false`，所有剩余事项见 KNOWN_ISSUES.md。

## 以下为较早的故障定位与历史操作记录

以下早期结论按各自时间解释，不代表最新状态；保留用于追溯。本文件不含秘密，未发送给管理员。

# 平台与人工处理项（2026-10-07 维护审计）

本文件不含密码、Token、EAB或私钥。以下信息尚未发送给管理员。

## 最新状态（2026-10-07 17:30 北京时间）

默认在线发现已恢复：17:29 同一正式 ADP 接口按当前 AIC 精确查询，Leader、资源 Partner、工单 Partner 均返回 ACS 和 `alive=true`，最近心跳均为当分钟。首页在线查询也显示“工维联核心业务 Leader · 在线”。

平台于 17:28:49 成功重新获取快照，增量游标开始推进，`lastError=null`。以下故障定位保留为恢复前证据，已不是当前阻塞项；没有由本项目执行平台全局重置，也不能将平台恢复归因于本次聊天解析修复。

仍待解决的是首页协作的原任务续接与完整确认建单验收。官方调试入口此前真实三轮已通过；首页普通聊天不能据此宣称通过。`platform_verified=false`。

本轮后续补充：叮当未选卡片的新会话自然语言发现已明确推荐工维联 Leader；首页恢复历史会话则出现 `conversation_id` 传入数字而接口要求字符串的错误，需要平台修复。工维联已修复首页转发文本误读示例时间，并修复 Partner 旧群组清理卡住；正式 MQ 同 session/group 解散后重建、再次邀请两个 Partner 和查询资源已通过，工单与预留数量不变。完整证据见本轮报告。

## 恢复前定位（2026-10-07 17:14 北京时间）

以下结论更新下方早期审计记录：

- 三个当前 AIC 的新鲜 SDK 心跳均已收到 `amp.heartbeat` 的真实 Kafka ACK；Writer 已提交的消费位点也超过这些心跳位点。ACK 不能单独证明 Redis 和发现索引已更新。
- 平台只读 `GET /discovery/admin/alive-sync/status` 明确返回：`gap on shard hb-000`，随后 `AliveSyncError: Provider /sync/snapshot 响应为空（无 meta 行）`。最后应用增量仍是 2026-10-06 11:58:48 UTC，游标 2380018。平台正在自行重试，没有由本项目触发全局重置。
- 最新 `alive-delta` 队列尾部已超过 2471787。不能继续沿用“队列没有新消息”的旧推断；当前可证实的是 Discovery 遇到序列缺口后无法获取有效快照。需要平台管理员检查 Monitor Sync API 的状态码、响应体、流式代理和 Discovery Provider 配置，恢复有效的 meta 行及快照后，由平台完成同步恢复。
- 本项目没有平台 Monitor/Discovery 运维权限，不执行共享索引清空、Kafka 位点重置、管理员 resync 或直接写入 alive-delta。无需再次注册或更换 AIC。
- 叮当官方“智能体响应调试”已经完成真实三轮、同 session/task、正式 MQ 两 Partner 和唯一工单。首页卡片的普通协作输入仍走 cancel + 新 start；session_1723 再次证实。平台可让等待补充的成员走现有 `/agent/continue` 分支，保留原 session/task。不能由 Leader 忽略 cancel 来伪装通过。
- 在管理员修复前，已配置的 `platform_catalog` 策略通过真实 Discovery 全状态目录精确匹配当前 Partner AIC，再实际连接 MQ；它能支持业务，但不等于默认在线发现已经通过。`platform_verified=false`。

完整证据：`reports/online-continuation-investigation-20261007/`；可用调试入口的实际工单记录：`reports/dingdang-continuation-20261007/README.md`。

## 1. 平台在线状态发布

三个真实AIC均在目录中。默认在线查询为空；相同active、skill、AIC精确条件增加全alive状态后均能返回。详见 `reports/final-maintenance-audit/discovery-independent-readonly.json`。

请平台管理员排查：AMP Heartbeat Writer → Redis / Outbox → Relay → Discovery。既有心跳Kafka ACK和游标证据在历史归档；本轮没有以本地状态或直接写alive-delta伪造在线。

无需重新注册、删除记录或重新申请群组权限。正式Group ACL已改用实测成功的 `https://wt.ioa.pub:9007`；旧443入口的403不代表9007也失败。

## 2. 叮当主任务续接

部署后再次实测 session_1702：先start并awaiting-input，随后叮当cancel旧task、start新task。需要核对叮当消费者的continue路由。项目公网SDK诊断能保持同session/task，但不能代替叮当验收。新日志和截图见 `reports/deployment-maintenance-20261007/`。

还需核对业务“请用户确认”与官方空complete握手的语义。未收到明确同意时不能自动建单。待真实三轮、唯一工单、自动发现、后台访问记录全部通过，才能修改platform_verified。

## 3. 部署及最终验收

维护修复已上传服务器，包含新 `mq_partner_runtime.py`。旧代码、配置与SQLite备份位于 `/opt/gongwei/backups/20261006-200337-maintenance`，8个服务正常。正式三身份双群组与幂等测试通过；叮当仍被默认在线发现及主任务续接阻塞。Nginx的32个文件指纹一致，未停止其他项目服务。

三个证书应在既有报告记录的2026-11-24 UTC到期前续签；秘密保存在原受保护目录。

## 4. 清理结果

批量永久删除被自动安全审查拒绝（工具仅返回blocked by policy）。已改用Windows回收站完成598文件的可恢复清理；3个占用中的日志保留。历史证据压缩包仍在archive，数据库、源码、模型、证书和秘密未清理。明细见本轮cleanup-result.json。

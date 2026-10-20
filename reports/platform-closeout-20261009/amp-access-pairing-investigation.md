# AMP Access 双侧匹配只读调查

## 范围与证据来源

读取官方 `wt.ioa.pub:19092` 的 `amp.access`，时间范围为 **2026-10-08 17:55–18:10 UTC**，即 **2026-10-09 01:55–02:10 北京时间**。复核时间为 `2026-10-08T18:11:23.162148+00:00`。

本报告根据已经完成的读取结果保存，保存时没有再次扫描 Kafka。消费者使用 `group_id=None`、`enable_auto_commit=False`，没有使用 producer，没有提交消费位点，没有向管理员发送消息。

仅保存 `session_1841` 三个真实任务与我方 Leader 有关的协议元数据样本、分组实测数量和扫描完整性。没有保存 Kafka 原始值、HTTP headers、请求/响应正文、凭据或其他用户记录。完整机器可读证据见同目录 [amp-access-pairing-investigation.json](amp-access-pairing-investigation.json)。

## 扫描完整性

- 官方 topic 共 **16 个分区**，本次捕获的所有起止 offset 范围均读取完成。
- 范围内实际读取 **107 条 topic 记录**；16 个范围的 `end - start` 合计同为 **107**。
- offset 范围采用左闭右开，详情保存在 JSON 中；通过 Kafka `offsets_for_times` 取得，无时间对应 offset 时使用当时捕获的 topic 末尾。
- 107 是 topic 扫描总量，不是三个任务的数量。报告只保存三个指定任务的元数据。

## 真实调用观察

我方 Leader AIC：`1.2.156.3088.1.BUPT.JSQB3Y.RN5ERG.1KIZGN.0M45`。

认证后的叮当 caller AIC：`1.2.156.3088.1.0001.00001.EZTK03.WCU6LR.14YT`。

| 真实 taskId | 我方 callee Access 条数 | 方法分布 |
| --- | ---: | --- |
| `a9f43cab-d4ce-4d11-b98b-432b9bf3180f` | 3 | start 1、get 1、cancel 1 |
| `1847721f-6b88-40cb-a658-f51d415cbeb3` | 7 | start 1、get 5、cancel 1 |
| `ce6f1ce3-d1b0-4a0a-b7be-aa8b3e623184` | 3 | start 1、get 2 |

以上 **13 条**均以我方 Leader 为上传 AIC 和 callee，以实际叮当 AIC 为 caller，`correlation_id` 为对应真实 taskId。JSON 对每个 taskId/方法组保存首条实际记录的白名单样本及组总量；没有把其余记录编造为单条样本。

在捕获的全部范围内，没有找到上传 AIC 为非我方、callee 为我方 Leader 的 caller 记录；没有找到实际叮当 AIC 上传的 caller 记录，也没有找到 `correlation_id=session_1841` 的记录。样本里的 `trace_id`、`span_id`、`parent_span_id` 均未携带。

## 官方规则与源码差异

[平台当前文档](https://wt.ioa.pub/docs.html)明确要求 Access 的 `correlationId` 填写 taskId，按 taskId 双侧匹配后计算调用/被调用数量。当前窗口已有真实 callee，但未找到可配对 caller，因此本窗口的公开 topic 数据缺少完成所述双侧匹配的证据。

[官方 SDK 2.2.0 的 AipRpcClient](https://raw.githubusercontent.com/AIP-PUB/ACPs-community/v2.2.0/acps-sdk/acps_sdk/aip/aip_rpc_client.py)第 216 行使用 `correlation_id=command.sessionId`。这与平台要求 taskId 存在潜在不一致。**本次没有观察到叮当实际 caller 上传，不能将 SDK 默认实现写成叮当当前实际使用 sessionId 的事实。**

[官方 Monitor topology 物化视图](https://raw.githubusercontent.com/AIP-PUB/ACPs-community/v2.2.0/monitor-server/app/access/tables.py)第 225–230 行按 callee 视角收敛计数；它不是网站文档所述的双侧 `matched-stats` 算法。所检查的公开 v2.2.0 树未提供该网站匹配实现，因此暂不能证明其是否还要求 trace、方法、状态、时间或身份别名等条件。

我方 `amp_telemetry.py` 第 248 行使用真实 taskId，并未向 emitter 传递 trace 参数；RPC dispatch adapter 收到的是 typed `RpcRequest`，没有保留 HTTP `traceparent`。**上传元数据缺 trace 不能证明叮当入站请求没有 traceparent。**

## 结论限制

“未找到 caller”仅指这个 topic 的本次捕获 offset 范围，**不表示平台所有时间均无 caller**，也不证明 caller 从未生成。延迟上传、不同 Kafka 时间戳、其他 topic/broker、身份或 correlation 填错、其他存储路径均未由此次读取排除。使用错误身份且无相关 correlation 的 caller 也可能不满足本次目标筛选。

Kafka ACK 和本地合法 schema 可以证明发送链路的一部分，不能单独证明平台入库、双侧匹配或最终统计成功。实际叮当 caller 的 `correlation_id` 与 trace 元数据仍未观察到。

## 后续平台核查项

1. 按 `session_1841` 与三个真实 taskId 定位叮当 caller 的真实 Access 文件/记录，只核对上传 AIC、caller/callee AIC、correlation、时间、trace/span 元数据。
2. 确认 caller emitter 已开启，实际日志文件确实转发至预期 broker/topic，并检查 ACK、入库、拒收状态。
3. 确认部署版本是否使用真实 taskId，或仍使用 SDK 2.2.0 的 sessionId 默认值。
4. 确认网站匹配是否接受实际认证 caller AIC，是否另有注册别名或身份排除条件。
5. 提供网站双侧匹配的完整 key 与过滤规则，包括 trace、method、status、时间窗口、字段别名和去重条件。
6. 如上传延迟，由平台按真实任务标识检查更宽时间范围；不能代造 caller 记录。

## 保存与检查

使用 Superpowers／系统调试。仅新增本报告和对应 JSON；没有修改运行代码、配置或服务。保存后检查 JSON 可解析、分区覆盖/offset 合计、三任务分组数量和元数据白名单。

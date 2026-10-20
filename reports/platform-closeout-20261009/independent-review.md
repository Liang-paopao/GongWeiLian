# 2026-10-09 独立代码审查

## 范围与方法

启用 Superpowers。只读审查本轮 `stage2_domain.py` 工单终态结算、`amp_telemetry.py`、`amp_metadata_forwarder.py`、`deploy/systemd/gongwei-amp-metadata.service.example` 及三套对应测试。未将历史脏改动纳入本轮结论；已有取消守卫审查本轮未重复。除本报告外，未修改代码、真实数据库或秘密文件，未执行部署或网络上传。

## 结论

未发现未关闭的 P0/P1/P2。业务结算与 AMP 代码未发现具体新增阻塞；下面的唯一 P2 已修复并根据实际 namespace 证据复核关闭。

### 已关闭 P2：服务原可读取本轮凭证和数据库备份目录

位置：`deploy/systemd/gongwei-amp-metadata.service.example:29`。

原始发现：服务以 root 运行，保留 `CAP_DAC_READ_SEARCH`；`ProtectSystem=strict` 限制写入，不能限制读取。修复前 `InaccessiblePaths` 未覆盖 `/opt/gongwei/backups`。本轮 `deploy-closeout.py` 明确将 `leader.env`、业务数据库和 RPC 数据库备份到该目录，故这些敏感备份原在服务可读取的文件系统范围中。现有 forwarder 固定四个日志路径，没有读取或发送这些备份的代码路径；问题属于最小读取权限边界不完整。

修复与复核：本地 service 第 29 行已加入 `-/opt/gongwei/backups`。审查已核对 `metadata-hardening.json` 和只读查看 `harden-metadata-service.py` 的证据生成方法：实际 unit 已执行 `systemd-analyze verify`，元数据服务重启后为 active，其他八个本项目服务 PID 保持不变；实际元数据进程 mount namespace 中原凭证备份路径 `credential_backup_visible=false`，所需 AMP 日志目录 `amp_root_visible=true`。证据中的 `backup_root_visible=true` 仅检查目录节点 `os.access`，不能据此认定原备份内容可读；实际 unit 的不可访问路径及原凭证备份不可见支持关闭本问题。补充目录内容检查可由主任务继续归档。审查未打开备份内容，未执行远程操作，本次隔离路径修复未重跑此前已通过的 62 项测试。

## 已核对的实现

- 工单结算在 `BEGIN IMMEDIATE` 事务内只处理 active 预留。completed 释放人员与工具、将零件标记 consumed；failed 释放全部预留。已结算行不会再次增加库存；终态回退被拒绝。历史 completed 且仍 active 的预留可通过同一入口修复。分类错误导致整笔事务回滚。迟到预留和已有工单重规划守卫保持有效。
- MQ 采集的 receive 使用当前 validated callback 的 ContextVar 与真实 taskId 绑定；ACK/NACK 必须匹配该 delivery 的 trace_id 和 receive parent span。非法消息模型、并发复用 messageId、无 trace 均不会借用旧任务的 settlement 绑定。
- RPC Access 只记录固定路由、方法、调用者/被调用者 AIC、状态与错误代码。MQ Message 只记录协议字段；正文、products、headers、任意属性和异常正文被剔除。
- forwarder 固定官方 broker、三个 AIC 与四个官方采集文件。每轮重取固定 DynamicUser 账户 UID/GID；安全打开要求逐层无 symlink、叶子为单链接普通文件、所有者匹配，并限制大小。仅允许固定 systemd 公共/私有日志目录。
- 发送前递归验证协议字段白名单及 task correlation，发送原始已验证字节。固定 aiokafka 0.12.0，复用 all-topics metadata 请求限制；主题缺失时不发送，不主动创建主题。
- Kafka topic/partition/offset ACK 验证通过后才将 ledger 与 cursor 写入 0600 文件并 fsync；状态目录要求 0700，排他锁防止双进程共享。重启、重复 log_id、rotation 与 copytruncate 已覆盖；ACK 与本地 fsync 之间崩溃可能产生相同 log_id 的至少一次重发，这是当前明确的交付语义。
- systemd 状态目录、只读日志 bind、可写范围、secret 路径隐藏及读权限能力均已静态核对；唯一的备份目录遗漏现已修复，并有实际 namespace 证据支持关闭。

## 验证结果

本机执行：

```text
.venv\Scripts\python.exe -m unittest -q test_work_order_closeout test_amp_telemetry test_amp_metadata_forwarder
```

结果：62 项全部通过，退出码 0，无跳过。其中工单结算 9 项、采集 21 项、上传 32 项。使用真实 SQLite 临时数据库、官方 SDK 记录和本地发送替身，未连接真实 broker。

本机为 Windows，本轮测试不能证明实际 POSIX namespace 和服务器权限有效；该部分应以主任务的真实服务权限预检为准。本机没有安装 aiokafka，本轮未重新证明其服务器实际版本运行；发送实现已固定版本并在连接前执行检查。

## 平台验收边界

Access 双侧匹配仍缺平台 caller 的对应记录，已有证据应继续保留。当前项目只能生成本地 callee Access，不能替平台调用方生成 caller 记录。业务真实三轮、重复确认、修改及取消的外部验收由主任务记录；本次独立本地审查不能将这些外部状态升级为全量平台验收完成。

## 审查快照

| 文件 | SHA-256 |
| --- | --- |
| `stage2_domain.py` | `67b2a6a1492cdf67cfae5c6114caa0b3a3956d61265d9a7a602a027e4e1f2589` |
| `amp_telemetry.py` | `7a7938df408bcc5a64d9e2cc96931fcb7e3504397e3b0e662a7164ae325c335e` |
| `amp_metadata_forwarder.py` | `2694f6ff82e8737e192bad2b1c34c5ad83512545b1dbd1d83c87928b1e80c52e` |
| `deploy/systemd/gongwei-amp-metadata.service.example`（P2 修复后） | `20a4805746ecea5e4055bdc5637ad02f09daa9ca98fa604e6ec10ee03b2a7962` |

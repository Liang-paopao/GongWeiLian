# 可观测性

本机日志分为 Heartbeat、System、Message、Access、Metrics、Audit 六类，均为 UTF-8 JSONL。每次 AIP 请求会沿用 task/session 标识；MQ 任务在官方适配器中附带 group/message 标识，业务审计写入 SQLite `task_events`。

`local_log.record()` 保留按 actor 的兼容日志，同时写入分类日志；敏感字段递归脱敏，单文件达到 2 MiB 时轮转到 `.1`。评审包只保留必要样例，不包含完整历史日志、Token、证书或录音。

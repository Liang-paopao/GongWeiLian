# 变更记录

## 2026-10-05 项目审计与整理

- 在 `pre-final-cleanup-20261005` 标签保护下完成清理前基线记录。
- 保留 `local_rpc`，并保留官方 `platform_mq_inbox` Group/Inbox 传输；修正 mTLS trust bundle、vhost、官方 Complete 控制消息和 DataItems 解析。
- 文字和结构化检查请求可独立进入 Leader，缺字段返回 `awaiting_input`；声音上传在网页中明确为可选辅助。
- Leader MQ ACS 的描述和 skills 增加设备异常后的资源协调、检查安排、工单处理及声音可选边界。
- 历史 ACS、报告、截图和旧评审包归档到 `archive/legacy/`；删除项目 Python 缓存；不删除 secrets、证书、数据库或业务代码。
- 新增 `reports/final-project-audit/` 及脱敏评审压缩包。平台发现和叮当调用仍保持未验证。

# 安全边界

- `platform_verified` 固定为 `false`，没有 AIC、EAB、证书和管理员参数时不生成正式 ACS。
- 本机 Partner 只接受回环请求；正式 HTTPS 模式要求完整 HTTPS、非本机地址、AIC 和 mTLS 文件。
- MQ/HTTPS 配置状态只显示脱敏 URL 和文件路径；密码、Token、私钥和原始音频不会进入日志或 Git。
- 上传音频限制 WAV、Base64 和 10 MiB，结果只允许两种安全文案；声音结果必须由用户确认。
- 业务动作使用 SQLite 事务、幂等键和补偿/恢复事件；重复确认不会重复建单。
- 故障注入仅由测试脚本调用，演示数据库为 `simulated=true`。

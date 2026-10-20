# 安全审计边界

- 密码、Token、EAB macKey、私钥和完整证书链只存在于本机 `secrets/` 或环境变量；`.gitignore` 排除 `secrets/`、证书扩展名、Token 目录和本地数据库。
- 日志只记录 AIC、状态、时间、taskId/messageId 等非秘密证据，密钥和授权头被省略。`local_log.py` 的回归测试覆盖敏感字段脱敏。
- 三个智能体分别使用独立 AIC、EAB 和 clientAuth 私钥。资源证书冒用 Leader AIC 的 Inbox 连接实测被 `ChannelAccessRefused` 拒绝。
- 评审包生成脚本按文件白名单打包，不包含 `secrets/`、SQLite、虚拟环境、原始录音、大型数据集、浏览器会话和旧压缩包；打包后会解压检查敏感路径。
- 平台正式注册记录均为 APPROVED，但 `platform_verified=false`，因为发现服务、叮当外部调用及后台访问回执尚未完成。

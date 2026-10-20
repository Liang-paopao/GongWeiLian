# 工维联 HTTPS Leader + MQ Partner 正式接入

目标：在现有项目和服务器上部署独立 Leader，沿用三套真实身份；网页和其他服务器项目保持可用。最终入口由用户确认为 `https://leader.yanyi.online/rpc`。平台验收未全部通过前保持 `platform_verified=false`。

## 执行顺序和闸门

1. 已完成服务器代码、Nginx、四个 systemd 单元和 SQLite 一致备份：`/opt/gongwei/backups/pre-platform-20261006T184217`。数据库 integrity_check=ok。
2. 核查官方 SDK v2.2.0 TLS 身份绑定，增加持久化 Direct RPC dispatcher 和独立运行入口；先写测试，回归原业务。
3. 运行配置支持独立秘密目录，校验证书 CN/AIC、用途、有效期和私钥匹配；配置错误应启动失败。
4. 生成同 AIC 的 Leader ACS 1.1.0，端点 HTTPS/JSON-RPC/mTLS，certificate.altNames.dns 包含 leader.yanyi.online。已批准记录目前 UI 只读，官方源码仅允许草稿编辑；等待管理员支持原记录更新。
5. serverAuth 已真实签发，但尚无 DNS SAN，因此不能作为该域名合格证书。不得关闭 hostname 检查。待 ACS 更新后续签并校验。
6. 安全上传必要身份文件（不含 CLI Token/EAB/账户密钥），各服务独立配置；先做真实 AMQPS/ACL/Inbox 预检，再切换两 Partner 和网页出站 MQ，避免中途损坏网页业务。
7. HTTPS 使用 SNI 透传保留客户端原始证书；只有域名证书、运行入口和回滚检查均就绪后才改服务器 443 路由。保持其他站点的证书及内容。
8. 实测完整多轮、确认门、幂等、修改/取消、错误证书/身份、重启恢复；本地测试不计作平台验收。
9. 原注册更新获批后等待 Discovery 同步，浏览器执行叮当直接调用和自动发现，保存三智能体关联日志、数据库变化、后台访问记录。
10. 五服务正式联通后再执行获授权的服务器重启验收。更新报告、HUMAN_ACTIONS 和不含秘密/数据库的评审包。

## 目前外部闸门

- Leader 原注册记录已批准且只读，需要管理员支持保留 AIC 更新 ACS。
- 证书 DNS SAN 由注册 ACS 决定，当前签发证书仅有 AIC URI SAN。
- 需复测管理员提供的 mq-auth 443 路径是否已支持原始客户端证书；若仍 403，记录真实结果并等待管理员。

# 平台参数清单

## MQ Inbox

- broker URL
- `auth_service_url`
- vhost
- TLS/mTLS 方式和 CA、客户端证书、私钥路径
- Inbox endpoint 格式
- Leader、资源、工单 AIC
- ACS 中群组/Inbox 字段及注册页面填写位置

## HTTPS Direct RPC

- 三个稳定的完整 `https://` RPC URL
- Leader、资源、工单 AIC
- 服务端证书、客户端证书、私钥和信任链
- AIC 与证书绑定方式、发现入口、外部调用测试账号

以上参数需梧桐管理员或正式部署提供。本项目没有猜测、填充示例域名或重复提交拒绝记录。

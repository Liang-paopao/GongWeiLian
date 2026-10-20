# MQ Inbox 平台参数与核验结果

## 已取得的参数

| 参数 | 当前值/状态 |
|---|---|
| MQ Broker | `amqps://wt.ioa.pub:5671` |
| `auth_service_url` | 管理员给出 `https://wt.ioa.pub/mq-auth/`；健康和就绪检查均 200 |
| vhost | `/acps`，SDK 内部按官方 endpoint 规范归一化为 `acps` |
| TLS | mTLS；三个 AIC 各自独立 clientAuth 证书和 trust bundle |
| Inbox endpoint | `amqps://wt.ioa.pub:5671/acps?inbox=inbox_{AIC}` |
| AIC 绑定 | 三项均 APPROVED，真实 AIC/EAB/证书保存在本机被忽略的 `secrets/` |

## 仍需平台/管理员确认

1. 群组 ACL 实测使用 `https://wt.ioa.pub:9007` mTLS 返回 204；管理员提供的 443 `/mq-auth/` ACL 请求返回 403 `CLIENT_CERTIFICATE_REQUIRED`。
2. `https://wt.ioa.pub:9008` 当前 TCP 连接被拒绝，需要确认是否为 Auth API 或已下线。
3. 注册页面目前只有 ACS 文本框，没有单独的 Group Leader/Partner、Inbox endpoint 或 `auth_service_url` 字段；请确认平台后台以 ACS 发现这些能力的正式方式。
4. 发现服务器和叮当的真实调用入口、授权方式及回执保存位置仍未提供。

在这些信息确认前不猜测平台参数、不重复注册、不修改 APPROVED 记录，继续保持 `platform_verified=false`。

历史浏览器拒绝记录和截图索引保存在 `archive/legacy/20261005-mq/`，不作为当前接入成功依据。

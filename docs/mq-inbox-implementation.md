# 工维联 MQ Inbox 接入实现

## 双传输架构

`local_rpc` 服务本机网页和自动测试，`platform_mq_inbox` 使用官方 ACPs v2.2.0 Group/Inbox SDK。两者共用 `stage2_domain.py`、`stage2_business_actions.py`、SQLite、幂等、恢复和补偿逻辑，传输层不复制业务代码。

## 官方组件

- Leader：`GroupLeader`，创建群组、邀请 Partner、启动任务。
- Partner：`GroupPartnerMqClient`，监听 `inbox_{AIC}`、接收邀请、加入群组并回传官方任务状态。
- 准入：`GroupAclClient`，使用 `auth_service_url` 和每个 AIC 独立 clientAuth 证书。
- 协议：`TaskCommand`/`TaskResult`；项目不定义普通 RabbitMQ 替代协议。

## 真实验证

`logs/mq_platform_live_20261005.log` 记录了三张证书的 TLS 1.3 AMQPS 握手、mq-auth health/ready、两个 Partner Inbox 监听、Leader 创建群组、Partner 入群、资源查询/预留、工单创建、accepted → working → awaiting-completion → completed、重复消息幂等以及错误身份拒绝。没有静默回退到 RPC。

## 配置

使用 `GONGWEI_TRANSPORT_MODE=platform_mq_inbox`，注入 Broker、Auth URL、vhost、Inbox 模板、三个 AIC 和各自证书路径。秘密只在本机 `secrets/`，不进 Git 或评审包。`platform_verified` 只有在发现服务器和叮当外部调用取得真实回执后才允许改为 `true`。

## 当前参数阻塞

管理员提供的 443 `/mq-auth/` 健康接口可用，但 ACL 写入需要 mTLS 且实测由 9007 接收；9008 不可达。正式部署前须由管理员确认两个服务的正式外部参数和平台注册填写位置。

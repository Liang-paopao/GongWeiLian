# 梧桐双正式传输准备

当前代码支持 `platform_mq_inbox` 和 `platform_https_rpc`，默认 `local_rpc`。MQ 路线使用官方 Group/Inbox 适配器；HTTPS 路线使用官方 AIP RPC 客户端和 mTLS SSL context。两者都调用同一套业务动作。

正式参数到位后只需填写环境变量、运行对应 ACS 生成器和外部负正测试，不需要复制业务代码。当前没有正式外部端点、AIC、证书或管理员参数，两个正式模式都保持 pending，`platform_verified=false`。

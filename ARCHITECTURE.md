# 当前真实架构

## 业务路径

```text
外部用户或叮当（平台发现/外部调用待验证）
        |
        v
核心业务 Leader
        |  Group/Inbox AIP
        +--> 资源协调 Partner：查询人员、技能、时段、工具和库存，预留/释放资源
        |
        +--> 工单处理 Partner：创建、查询、更新、取消工单
        |
        +--> 声音辅助 Partner（可插拔，可不用）
```

Leader 同时服务网页本机入口和官方 MQ Inbox。`local_rpc` 与 `platform_mq_inbox` 只在传输层切换，业务规则、SQLite、幂等和补偿逻辑共用一套实现。

## 请求与状态

文字/结构化请求可以只带已知信息。缺少设备、日期、时间、时长或说明时，Leader 返回 `awaiting_input` 并列出字段，不占用资源。完整请求先生成方案；只有用户确认后才预留资源和创建工单。任务、消息、会话和幂等键会写入事件与调用日志。

声音上传不是前置条件。声音模块只输出“未发现明显异常”或“疑似异常”，用户确认后才会进入同一检查方案流程。

## MQ 路径

Leader 使用官方 `GroupLeader`，Partner 使用官方 `GroupPartnerMqClient`，Inbox 地址由 ACS 的 `amqps://wt.ioa.pub:5671/acps?inbox=inbox_{AIC}` 模板解析。每个 AIC 绑定独立 clientAuth 证书，mq-auth 和 RabbitMQ 返回的错误会向上显式报告，不静默回退到本机 RPC。

## 数据与恢复

SQLite 持久化检查请求、方案、资源预留、工单、幂等键和审计事件。重复消息不会重复创建工单，服务重启后通过数据库恢复业务状态。冲突或工单失败会进入失败/补偿路径并释放已预留资源。

旧的本机 ACS 与阶段一双进程入口只在 `archive/legacy/` 保留，当前正式启动脚本不再引用它们。

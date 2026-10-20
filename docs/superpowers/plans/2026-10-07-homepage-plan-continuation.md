# 首页方案编号接续实施计划

**目标：** 在叮当首页取消旧 AIP task、新建 task 的情况下，使用用户明确确认的方案编号完成唯一工单。用户已明确接受外部 taskId 变化。

**架构：** 保留官方 start/continue/cancel 语义和 mTLS 身份校验。方案报价存于现有 agent_tasks.context_json；编号绑定不可变方案摘要。RPC 入口提供同一 sender/session 的归属验证；新 task 引用旧方案，旧 canceled task 不复活。以方案为单位串行确认并复用现有资源预留、补偿和建单逻辑。

**技术：** ACPs SDK 2.2.0、SQLite、Python、正式 AMQPS。无需数据库迁移，不改平台客户端。

## 已核对要求与风险

- 20261005 方案：多轮补充、确认前不预留、取消补偿、幂等、恢复。
- 官方 SDK：canceled 为终态；continue 仅适用于 awaiting-input/awaiting-completion；complete 不是隐式建单授权。
- 当前公开叮当客户端 continueSecretaryCollaboration 明确 cancel 后 execute。不能伪装旧 taskId 未变。
- 所有引用必须来自当前明确确认句。问题示例、旧对话确认、否定/取消/修改句不能授权。
- 跨 caller、跨 session、未知编号、旧版本、已取消工单必须拒绝；重复确认返回已有工单。

## 顺序

- [x] test_homepage_continuation.py：真实临时 SQLite、真实业务函数；测试协议 start/cancel/start/确认、重启、重复、并发、越权、引用/否定和版本失效。先运行失败测试。
- [x] plan_continuation.py：核对已持久化历史，仅接受新追加的唯一明确回答、生成/校验方案引用、持久化来源关系；不执行独立业务。
- [x] leader_external_flow.py：方案返回编号；确认引用接入原 _confirm；幂等键绑定 plan；明确取消引用不触发恢复。
- [x] leader_rpc_runtime.py：提供已验证 sender/session 下的归属校验，并按方案串行处理。
- [x] 本地全量 unittest、阶段二、阶段五；服务器备份、发布目录完整回归、仅重启 Leader。
- [x] 浏览器首页实际三轮通过；重复聊天返回已有工单，真正再次投递被平台配额阻断，作为未完成闸门记录。保存 MQ、数据库、协议映射、截图和耗时。
- [x] 如平台配额或登录阻塞，真实记录；不绕过限制，不把独立测试当成首页验收。
- [x] 更新报告和评审包，保留 platform_verified=false 直到全部正式闸门实测通过。

采用本会话顺序执行；不另建项目、不提交已有混合工作区变化。

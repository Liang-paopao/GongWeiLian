# 工维联智能体化重构设计

## 目标

在现有 Leader、资源 Partner、工单 Partner、SQLite、官方 Group/Inbox、证书和可靠性底座上，把用户入口改为可恢复的中文多轮协作。`local_rpc` 继续服务本机网页和回归测试；`platform_mq_inbox` 显式使用官方 SDK，发现服务不可用时不假装在线。

## 结构

- `agentic_core.py`：可审计的中文规则解析回退、会话/任务/消息关联和缺参询问。
- `partner_resolver.py`：使用官方 ADP 请求模型访问 discovery_server，或在本地明确标记 static_fallback；候选必须满足 active、协议、Skill、JSON 输入输出、AMQP、mTLS 和 AMQPS endpoint。
- `leader_inbox_runtime.py`：用官方 `GroupPartnerMqClient` 让 Leader 接收外部 Inbox 群组任务，保持外部 session/task/message ID。
- `stage2_db.py`：只做增量 SQLite migration，增加会话、任务、消息、确认、发现快照和选择记录。
- `web_app.py`：新会话、消息、确认、修改、取消、追踪、发现、平台状态和智能体状态接口；现有业务接口保留。
- `web/`：三栏对话、计划确认、协作轨迹，声音入口收进可选辅助抽屉。

## 状态与安全

信息不完整时进入 `awaiting_input`，完整后进入 `ready_for_plan`/`proposed`，用户确认才进入资源预留和工单创建。所有调用使用同一外部 task 作为主关联，Partner 子任务使用 `:resource:01` 等后缀。平台状态由证据计算，未取得发现、叮当和后台回执时保持 `platform_verified=false`。秘密仍只在被忽略的本机配置中。

## 验证

阶段测试按计划运行：原有 88 项回归、阶段二/阶段五黑盒、中文多轮、发现过滤/失败、外部 Inbox 运行时、固定 session 检查、浏览器完整场景和无 Docker 时 MQ BLOCKED 前置检查。声音模块只作为可选辅助。

# 三个核心智能体重新注册执行计划

> **For agentic workers:** 使用 executing-plans 在本会话顺序执行。只有平台真实响应可作为注册、证书、MQ 或发现通过的依据。

**Goal:** 按用户最新指示删除三个旧平台注册记录，重新提交正确 ACS，取得新的真实身份后重新进行正式接入和调用验收。

**Architecture:** 维持 HTTPS/mTLS Leader → 官方 MQ Inbox Partners 的目标架构，以及现有 local_rpc 业务服务。重新注册期间旧身份不迁移为新身份，不混用三套证书，不将注册模板视作可运行的正式配置。

**Tech Stack:** ACPs SDK/CLI 2.2.0、梧桐注册平台、ACME CA、RabbitMQ AMQPS、ADP Discovery、现有 Python/SQLite/systemd 服务。

## 一、准备与删除闸门

- [x] 浏览器由用户完成登录，使用已有会话。
- [x] 归档本机旧身份与证书到被 Git 忽略的 secrets/identity-history，保留源文件；保存可公开的三条旧身份摘要。
- [x] 在 reports/platform-reregister-20261006/acs/ 生成三个 1.1.0 注册模板。Leader 为 https://leader.yanyi.online/rpc、JSONRPC、mTLS、text/plain/application/json，并带 certificate.altNames.dns；Partners 为官方 AMQP Inbox 模板、mTLS、rabbitmq:>=4.2。
- [x] 使用官方注册 JSON Schema 校验三份通过，并单独记录 AgentCapabilitySpec 的旧 MQ 枚举差异；确认未带旧 AIC、旧 Inbox 或秘密内容。新 AIC 未分配前为空，Partner 采用官方支持的 {AIC} 模板；仅用于注册，禁止加载到正式运行配置。
- [x] 已保存本机旧身份归档、历史 Leader ACS、删除后的 active=false ACS 和页面；两个旧 Partner 未完成新的页面导出前，用户已亲自删除，明确记录这一限制。
- [x] 用户明确确认已经自行删除三条记录；助手不再执行删除，也没有声称代为点击删除。
- [x] 三条旧身份在本机及服务器配置标记停用并验证拒绝误启动；原证书文件保留。

## 二、重新注册与证书

- [x] 依次新建资源 Partner、工单 Partner、Leader，核对网页解析出的名称、版本、技能、endpoint 和 mTLS 后提交。三条均 1.1.0；Leader/资源已通过并分配新 AIC，工单仍审核中。
- [ ] 保存审核结果；等待管理员审核时其他独立检查继续，但不伪造 AIC。
- [ ] 从已通过的新记录读出真实 AIC；核对 Partner endpoint 已由平台替换为新 AIC 的 Inbox，Leader 的域名声明保留。
- [ ] 使用官方 CLI 获取每个身份各自的 EAB，分别签发 clientAuth；为新 Leader 另签发带 leader.yanyi.online DNS SAN 的 serverAuth。
- [ ] 新身份与秘密先存独立 secrets 子目录，不覆盖旧身份归档；验证 CN/URI、用途、SAN、密钥匹配、有效期和 CA 信任。

## 三、正式联调与部署

- [ ] 先复测 mq-auth 的 mTLS 身份获取和 Group API；403 若仍存在，保存原文和 TLS 证据，不宣布重建已解决。
- [ ] 分别实测三套 AMQPS/Inbox，使用官方 GroupLeader 邀请 Partners，执行资源查询和工单完整状态流。
- [ ] 精确查询 Discovery 三个新 AIC，保存真实响应；无目标结果时不静默使用静态 ACS。
- [ ] 通过证书、群组和发现闸门后才安全更新服务器秘密与服务配置；配置需备份，避免影响其他项目。Leader 独立服务及 443 SNI/mTLS 入口按既有计划验证后启用。
- [ ] 运行全部现有回归测试和正式叮当三轮、重复确认、修改、取消、错误证书及 senderId 测试；保存数据库、资源和后台访问记录。
- [ ] 完整闭环后执行已授权的服务器重启及五服务恢复验收。全部条件通过才更改 platform_verified。

## 交付

更新 reports/platform-reregister-20261006/ 的真实记录、失败项和测试结果；更新 HUMAN_ACTIONS.md、CHECK_STATUS.json；重新生成排除所有秘密的评审包。不会将准备文件或本机测试计作平台注册/叮当验收通过。

## 当前实际进展（2026-10-06 23:00）

Leader/资源审批结果、真实 AIC 和正式 ACS 已归档；两份 EAB、两份独立 clientAuth、带域名 SAN 的 Leader serverAuth 已申请并校验。官方 AMQPS/Inbox 两个新身份预检通过。新 Leader 群组鉴权仍 403 CLIENT_CERTIFICATE_REQUIRED，两个新 AIC 的 Discovery 精确查询为空；工单尚待审核。三身份完整闸门未通过，不启用生产混合模式。全量 141 测试、阶段二 Direct RPC 和阶段五可靠性回归通过。

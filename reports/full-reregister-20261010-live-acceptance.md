# 工维联新 Leader 注册后完整复核报告

日期：2026-10-10  
项目目录：`gongwei-step1`  
结论：业务链路和正式 MQ/mTLS 已通过；梧桐默认发现索引与本轮叮当浏览器调用仍未通过，因此保持 `platform_verified=false`。

## 1. 当前平台注册身份

| 智能体 | 状态 | AIC | 版本 | 传输 |
|---|---|---|---|---|
| 工维联核心业务 Leader | 已通过 | `1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9` | 1.1.1 | HTTPS JSON-RPC + mTLS |
| 工维联资源协调 Partner | 已通过 | `1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA` | 1.1.0 | AMQPS Inbox + mTLS |
| 工维联工单处理 Partner | 已通过 | `1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF` | 1.1.0 | AMQPS Inbox + mTLS |

Leader 新 clientAuth 与 `leader.yanyi.online` serverAuth 证书已经部署到独立的 `gongwei-leader.service`。证书内容、私钥、Token 和 EAB 未写入本报告或评审包。

## 2. 正式运行环境

- Leader 公网入口：`https://leader.yanyi.online/rpc`。
- MQ：`amqps://wt.ioa.pub:5671`，vhost `/acps`，官方 `GroupLeader`、`GroupPartner`、`GroupPartnerMqClient` 和 Inbox 实现。
- 鉴权服务：`https://wt.ioa.pub:9007`。
- `gongwei-leader.service`、`gongwei-resource-inbox.service`、`gongwei-workorder-inbox.service`、网页、音频和 AMP 服务均为 `active/running` 且 `enabled`；资源和工单普通 Partner 服务也保持运行。
- 服务器数据库 `stage2.db`：`integrity_check=ok`。
- 九个 `gongwei-*` 服务的最终状态见 `reports/full-reregister-20261010-service-status.txt`，均为 `active/running`。

## 3. 新 AIC 的正式 MQ 闭环

本轮使用新的 Leader AIC，测试主关联如下：

- 主 session：`full-reregister-bac67528fae6-session`
- 主 task：`full-reregister-bac67528fae6-task`
- 资源子任务：`...:resource:01` 查询、`...:resource:02` 预留
- 工单子任务：`...:workorder:01` 创建
- 方案：`plan-a3717964-bb9c-4bbd-a80d-9ebc16a44c87`
- 工单：`WO-20261010-00A91F`

真实日志确认：

1. Leader 创建群组并完成两个 Partner 的官方 ACL 加入；
2. 资源 Partner 返回 `Accepted → Working → AwaitingCompletion → Completed`；
3. 资源预留子任务返回同样的完整状态；
4. 工单 Partner 返回 `Accepted → Working → AwaitingCompletion → Completed`；
5. 重复确认只命中已有工单，数据库没有第二张同方案工单；
6. 服务器数据库最终为 15 张工单、6 条 active 预留，其中本轮方案为 1 张工单和 3 条预留（worker-03、part-seal-ring、tool-inspection-kit）。

证据：

- Leader：`reports/full-reregister-20261010-leader.log`
- 资源 Partner：`reports/full-reregister-20261010-resource.log`
- 工单 Partner：`reports/full-reregister-20261010-workorder.log`
- 数据库：`reports/full-reregister-20261010-db.json`

## 4. mTLS 与身份拒绝测试

`reports/full-reregister-20261010-identity-mtls.json` 的公网测试结果：

- 新 Leader clientAuth：成功建立 TLS，任务返回 `accepted → working → awaiting-input`，取消后为 `canceled`；
- senderId 与客户端证书 AIC 不一致：返回 `AuthorizationFailedError`；
- 不带客户端证书：TLS 连接被拒绝；
- 使用 Leader serverAuth 证书作为客户端证书：TLS 连接被拒绝；
- 该探针只收集缺少字段的任务并取消，未创建业务工单。

三套角色的独立 Inbox/AMQPS 预检均通过：

- `reports/full-reregister-20261010-leader-preflight-default.json`
- `reports/full-reregister-20261010-resource-preflight-default.json`
- `reports/full-reregister-20261010-workorder-preflight-default.json`

## 5. 发现服务结果

真实 discovery 服务查询结果保存在 `reports/full-reregister-20261010-discovery/`：

- 三个 AIC 的目录查询均已索引；
- 资源 Partner 和工单 Partner 的默认精确查询返回 active ACS；
- 新 Leader 的 catalog 查询返回 active ACS、正确 endpoint、mTLS、skills 和输入输出模式；
- 新 Leader 的默认精确查询 HTTP 200 但 `acsMap` 为空。

因此不能把目录命中写成“默认在线发现成功”，也不能把该项当成已解决。

## 6. 自动测试

- 本机完整 unittest：376 项，375 通过，1 项因 Windows 符号链接权限跳过，退出码 0。
- 阶段二业务回归：通过。
- 阶段五可靠性回归：通过。
- 声音阶段场景：60/60 通过。
- 网页控件测试：24 组通过。
- Python 项目文件编译检查：通过；Web JS 语法与控件测试：通过。

完整日志：`reports/full-reregister-20261010-local-unittest-final.log`（此前完整日志仍保留在 `reports/full-reregister-20261010-local-unittest.log`）。

## 7. 尚未完成

1. 注册平台会话已经恢复并显示三个智能体“已通过”，但首页叮当使用独立登录会话。本轮发送首轮文本时弹出叮当登录框，消息未发送到平台；尚未完成新 Leader 的叮当三轮真实对话截图与后台访问记录。公网 SDK 测试不能替代该项。
2. 新 Leader 默认 discovery 索引仍为空，需要平台同步或管理员核查；`platform_verified` 保持 `false`。
3. 平台历史 Message 统计有记录，但 HTTPS Access 双侧配对仍为 0，需要平台核查 caller 采集和匹配。
4. 技术方案 PDF 和 3–5 分钟演示视频尚未制作。

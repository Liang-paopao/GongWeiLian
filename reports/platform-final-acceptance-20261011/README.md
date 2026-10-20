# 工维联最终验收复核（2026-10-11）

## 结论

本轮把项目端和梧桐正式 MQ 端能验证的验收项全部重新复核并留证。业务闭环已经通过：叮当真实发现 Leader、三轮补充、资源 Partner 查询、用户确认、工单 Partner 建单、重复确认幂等、独立修改和取消、自动发现、服务器重启恢复均有真实证据。

`platform_verified` 仍保持 `false`。唯一未通过的是梧桐后台的 **HTTPS Access 匹配统计**：同一时间窗口的真实 `amp.access` 已进入官方 Kafka，并包含调用方 AIC、Leader AIC、taskId、方法和 200 响应；梧桐 `matched-stats` 仍把这些调用计入 `Message`，三方 `accessCount` 均为 0。项目端不能伪造叮当调用方的 AMP Access 记录，也不能把 Message 统计改写成 HTTPS Access，因此不把这一项宣布为通过。

## 真实身份和运行状态

| 角色 | AIC | 平台状态 | 运行方式 |
|---|---|---|---|
| 工维联核心业务 Leader | `1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9` | approved / active | `https://leader.yanyi.online/rpc`，mTLS JSON-RPC |
| 工维联资源协调 Partner | `1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA` | approved / active | 正式 AMQPS Inbox |
| 工维联工单处理 Partner | `1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF` | approved / active | 正式 AMQPS Inbox |

四个服务与元数据转发服务均由 systemd 管理，服务器复核结果为 active；SQLite `integrity_check=ok`。正式业务 MQ 使用 `amqps://wt.ioa.pub:5671`，没有静默回退到本机 RPC。

## 叮当真实调用验收

本轮使用已经登录的梧桐叮当，只选择“工维联核心业务 Leader”。真实会话为 `session_1988`；平台客户端会在后续轮次换外部协议 taskId，但项目使用同一业务会话、调用方校验和方案编号继续接续。

| 验收项 | 结果 | 证据 |
|---|---|---|
| 发现 Leader 并直接调用 | PASS | 当前发现结果和 Wutong 会话证据 |
| 首轮缺少信息返回 `awaiting_input` | PASS | 询问日期、开始时间、时长和技能；未建单 |
| 第二轮资源协调 | PASS | 资源 Partner 正式 MQ 查询，生成待确认方案 |
| 用户确认后建单 | PASS | 工单 Partner 正式 MQ 创建 `WO-20261011-A432C2` |
| 重复确认 | PASS | 返回同一工单，`idempotent=true`，无第二张工单 |
| 独立修改时间 | PASS | 同一业务任务重新查询并生成新方案，未覆盖已完成工单 |
| 取消 | PASS | 返回业务 `cancelled`，未占用资源、未建新工单 |
| 自动发现 | PASS | 未手动选 Partner 时仍推荐工维联核心业务 Leader |

本次 Kafka 中可以按任务号关联的 Leader HTTPS callee 记录包括：

- `0e41b088-5af1-407d-bb74-73a64afbc156`（首轮）；
- `98272851-2271-4d82-8950-3f5b6542c207`（补充信息与方案）；
- `d919fe7e-7c84-4271-a08f-3e4f66e0823d`、`3b9d9b26-3757-4607-88eb-9bbd98bfcd0d`（后续确认/幂等调用）。

对应的真实脱敏记录见 [`amp-access-kafka-current.json`](amp-access-kafka-current.json)。记录只有协议元数据，不含对话、人员、工单正文、证书或凭据。

## 官方 AMP 与后台统计核对

读取窗口：2026-10-11 01:00–04:00（Asia/Shanghai）。

| 统计身份 | count | accessCount | messageCount |
|---|---:|---:|---:|
| Leader | 16 | 0 | 16 |
| 资源 Partner | 8 | 0 | 8 |
| 工单 Partner | 8 | 0 | 8 |

同一窗口的官方 `amp.access` 只读扫描得到 18 条 Leader callee 记录，全部有调用方 AIC、Leader callee AIC、任务号、方法和 HTTP 200；没有发现叮当作为独立 emitter 发布的 caller-side Access 记录。原始后台响应见 [`platform-statistics-current.json`](platform-statistics-current.json)。

这说明：

1. 项目 HTTPS 接收、身份绑定、AccessEmitter、元数据转发和 Kafka ACK 已通过；
2. 叮当业务调用和 MQ 协作已通过；
3. 梧桐当前把叮当调用归到 Message，未形成网站要求的 bilateral HTTPS Access 匹配；
4. 需要梧桐平台管理员核对叮当 caller emitter、入库路由或统计分类规则。项目端没有可安全的代码修复可以代替对端记录。

## 回归测试

- 本机：`380 tests`，`OK (skipped=1)`；跳过项是本机未安装 Docker/acps-infra 的本地 MQ 模拟环境，不是业务失败。日志见 [`local-full-unittest.log`](local-full-unittest.log)。
- 服务器隔离回归：`380/380` 通过，见 [`server-regression.json`](server-regression.json)。
- AMP/发现/元数据针对性测试：`63/63` 通过。
- 前端控件：`24` 组通过。
- `node --check web/app.js`：通过。
- `git diff --check`：退出码 0；仅有 Windows 换行提示。

## 当前仍需外部处理

梧桐平台需要提供以下一项即可完成最后统计闸门：让叮当真实调用产生可匹配的 caller-side `amp.access`，或确认叮当调用在该平台产品中按 Message 统计且不要求 HTTPS Access。平台返回 Access 匹配后，再复核一次三方统计并将 `platform_verified` 从 `false` 改为 `true`。在此之前不修改状态、不伪造记录、不重复注册智能体。

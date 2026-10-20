# 工维联与其他项目的 AIC 发现对照

实测：2026-10-07 16:59–17:03（北京时间）。使用 Superpowers / systematic-debugging，进行只读接口与浏览器核验；未修改业务代码、注册数据、身份、服务配置或数据库。

## 结论

工维联三个当前 AIC 的默认在线 Discovery 精确查询均 HTTP 200、成功但候选为空；同一个接口、同一种查询，仅替换 AIC，两个其他项目的智能体均返回对应 ACS 和 `alive=true`。因此不能把现象解释为所有人的发现服务均不可用。

将查询扩展为包含 online / offline / unknown 三种状态后，工维联三个 AIC 均能找到，且 ACS 的 active=true、version=1.1.0。工维联响应没有 aliveMap，不能由此断言真实进程离线，或直接认定是平台故障。已定位到与活性数据/默认过滤相关的差异，尚需对照心跳上报、平台消费和 Discovery 状态同步。

## 当前真实 AIC

| 智能体 | AIC | 默认在线查询 | 全状态目录 |
| --- | --- | --- | --- |
| 工维联核心业务 Leader | 1.2.156.3088.1.BUPT.JSQB3Y.RN5ERG.1KIZGN.0M45 | 未返回 | 找到 |
| 工维联资源协调 Partner | 1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA | 未返回 | 找到 |
| 工维联工单处理 Partner | 1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF | 未返回 | 找到 |
| 知行·项目推荐与实践规划主智能体 | 1.2.156.3088.1.BUPT.1MON3C.BH1PPS.G167WL.06M7 | 找到，alive=true | 找到 |
| 证据综合智能体 | 1.2.156.3088.1.BUPT.4GKA38.5UHO24.D4V90A.0UZQ | 找到，alive=true | 找到 |

两个其他项目分别属于不同 AIC 所有者段，仅查询公开 ACS 和状态，未调用他们的业务任务。

## 查询位置与请求

1. 浏览器首页 `https://wt.ioa.pub/` 顶部“智能体 AIC”输入框，查询在线状态。
2. 正式 ADP 接口：`POST https://wt.ioa.pub/discovery/acps-adp-v2/discover`。

精确请求使用已安装官方 SDK 的 DiscoveryRequest：type=filtered，filter.conditions 为 aic eq 当前 AIC，limit=10。全状态对照仅增加部署扩展 extFilter.conditions：alive in [online,offline,unknown]。没有使用技能、名称或自然语言过滤，以避免混入匹配问题。

通过项目 `scripts/probe_hybrid_discovery.py` 的 `fetch(aic, catalog=False/True)` 执行五个 AIC × 两种模式，共十次查询。另进行 active=true 的默认及全状态各一次目录样本查询，用来选取真实的其他项目对照对象。

原始请求与响应：`exact-aic-results.json`、`broad-default.json`、`broad-catalog.json`。

## 浏览器核验

- 工维联 Leader：显示“未查询到智能体”“Discovery 没有返回该 AIC，请检查输入是否正确”。见 `homepage-own-leader.png`。
- 知行主智能体：显示“在线”，最近心跳 2026/10/06 19:58:36。见 `homepage-other-zhixing.png`。
- 证据综合智能体：显示“在线”，最近心跳 2026/10/06 19:58:10。见 `homepage-other-evidence.png`。

两个对照项的心跳时间均早于查询时间约 21 小时。这只证明平台返回其在线标记，不代表本轮已验证其端点实时可调用，也不足以推断平台的过期策略。

首页“上新智能体”仍能显示工维联的三个卡片；上新目录与默认在线查询使用的信息不同，看到卡片与在线查询为空可以同时发生。

## 首页多轮续接的其他办法

本轮再次读取当前公开客户端：`https://wt.ioa.pub/dingdang/app.js?v=v1.8.2-aic-verify-20261004`。来源及哈希见 `public-client-provenance.json`，相关函数见 `public-client-excerpts.txt`。

- 首页协作 `continueSecretaryCollaboration` 有 run_id 时先 cancel，再 POST /agent/execute。它不会因为 Leader 提示“请 continue”而改变这个分支。
- 平台已有单智能体 `continueActiveAgentInteraction` / `continueAgentTask` 分支，会发送原 session_id/task_id 到 /agent/continue。让工维联卡片使用该分支，或让协作等待输入节点采用同一任务 continue，是可行的修改方向；需要平台维护者落实并验证，当前未发现可让用户自行切换该模式的通用按钮。
- 已经验证可用的替代入口是叮当“开发者工具 → 智能体响应调试”。此前真实三轮同 session/task、正式 MQ 与工单结果见 `../dingdang-continuation-20261007/README.md`。
- 也可以在现有工维联网站继续业务；该网站的业务流程不能作为叮当首页三轮通过的证据。
- 项目侧可以设计显式方案编号的跨任务继续，但那仍是不同外部 task，不能满足原任务续接验收；还必须区分真正取消与重新调用，不能简单忽略 cancel、复活已取消任务或自动视为用户确认。本轮没有加入这种兼容逻辑。

当前 `platform_verified=false`。本次没有重新执行创建工单、修改或取消业务任务，也没有发送管理员消息。

## 建议的下一步

在线发现：携带这五项同接口对照，以及本机/服务器真实心跳投递证据，让平台对比当前三个 AIC 的心跳消费、状态写入及默认在线过滤；若上报数据与其实际要求不一致，再针对证据修正上报端。

首页续接：将公开客户端中的协作分支和上次真实 debug 成功记录提供给平台，要求首页卡片等待输入时向原 session/task 发 continue。当前不承诺平台尚未实现的行为，也不更换或重新注册 AIC。

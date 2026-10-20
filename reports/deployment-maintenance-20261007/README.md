# 维护修复部署与正式平台复测（2026-10-07）

## 结论

代码部署通过，梧桐整体验收未通过，`platform_verified=false`。

| 项目 | 本轮真实结果 |
|---|---|
| 维护代码部署 | 已部署到 `/opt/gongwei/releases/20261006-200337-maintenance` |
| 运行服务 | 8/8 active；7个业务进程已换新版，独立心跳转发进程保持运行；NRestarts均为0 |
| 原群组鉴权403 | 当前使用 `https://wt.ioa.pub:9007`；官方群组创建、邀请、加入、任务和关闭均成功。没有声称旧443入口已修复 |
| 正式MQ多群组 | 两个群组同时存在，切换群组后回到原群组的查询成功；两个阶段均通过 |
| 默认在线Discovery | 三个AIC均返回空；增加online/offline/unknown目录过滤后三个均返回真实ACS |
| 首页卡片 | 存在；首页AIC在线查询仍显示“未查询到智能体” |
| 叮当第一轮 | 点击工维联Leader卡片并确认后真实请求到达，返回awaiting-input并显示问题 |
| 叮当第二轮 | 同session_1702，但平台发送cancel旧task、start新task；新任务因发现不到Partner而failed |
| 生产工单与预留 | 测试前后均为0；没有发送第三轮建单确认 |

服务器版本/备份名使用UTC时间，`20261006-200337` 对应北京时间2026-10-07 04:03:37。

## 备份、切换与保护

- 服务器备份：`/opt/gongwei/backups/20261006-200337-maintenance`，root目录0700，配置包0600。
- 备份内容：原网页与正式代码、Nginx、工维联systemd和环境配置、业务与RPC SQLite在线一致性副本；切换前另备份一次数据库。私密备份未下载或收入评审包。
- 网页 `current` 从 `20261006-1807` 原子切到新版本；正式Leader和两个Inbox只新增 `90-maintenance-release.conf` 覆盖WorkingDirectory，原身份/证书/环境文件/沙箱权限保留。
- 失败回滚分支已写入部署入口，本轮未触发；旧版本与备份保留。本轮没有整机重启。
- Nginx 32个文件哈希完全一致，原运行的其他服务没有停止。没有安装依赖或修改共享入口。
- 网页保留local_rpc；独立Leader RPC及两个正式Partner使用platform_mq_inbox。并非回退。
- 生产数据库完整性ok；没有结构迁移。公网实际提供的app.js与本机修复文件SHA256相同。

## 测试与命令

服务器现有 `/opt/gongwei/.venv/bin/python`（Python 3.12，acps-sdk 2.2.0），隔离测试目录与数据库：

| 命令 / 检查 | 结果 |
|---|---|
| `python -m unittest discover -v` | 最终258/258通过，16.421秒 |
| `python run_stage2_tests.py` | 真实本机AIP业务流程通过 |
| `python run_stage5_tests.py` | 故障注入、补偿、重排、恢复通过 |
| `python scripts/run_60_scenarios.py` | 60/60通过 |
| `node --check web/app.js` | 通过 |
| `node scripts/test_web_controls.cjs` | 4项通过 |
| `git diff --check` | 通过，仅有既有CRLF提示 |
| 官方MQ诊断 `scripts/probe_group_workflow.py` | 正式5671/9007，102.02秒，两个阶段均通过 |
| 公网mTLS `start→continue→cancel` | 保持同session/task，问题随补充改变，0生产工单/预留 |

项目没有单独的lint/typecheck/build命令。首次服务器单元测试有4项失败：部署包遗漏阶段一静态练习文件 `data/resources.json`；补齐并修正部署/评审打包白名单后全量重跑通过。初次失败日志也保留。

正式MQ诊断在三个生产智能体进程停止期间独占Inbox；各角色使用自己的真实证书，测试只写临时SQLite。验证两个同时存在的群组、真实资源查询/预留/工单处理、accepted/working/awaiting-completion/completed、相同messageId重放、重复创建和三套SDK客户端重建。两个阶段都只有同一工单和同三条预留。结束后自动恢复服务，群组由官方SDK关闭。该诊断没有使用Discovery选人，也不是叮当调用。

部署入口：`python deploy/stage_maintenance_release.py`、`python deploy/activate_maintenance_release.py`。前者需要本轮备份元数据，现版本存在时拒绝覆盖；后者要求测试证据通过且当前仍是预期旧版本，不是可盲目重跑的更新器。

## 叮当ID证据

| 同一会话 | taskId | messageId | 平台发来的命令 | 结果 |
|---|---|---|---|---|
| session_1702 | 192cf143-e90e-4092-a44d-9fcca5520102 | cmd-e90136ce-bd6f-4981-b8f0-0593fc2df0a9 | start | awaiting-input |
| session_1702 | 192cf143-e90e-4092-a44d-9fcca5520102 | cmd-02fb3001-dab9-4fb6-aeff-056ff7719229 | cancel | canceled |
| session_1702 | cfe51e30-0e42-4637-b322-2eea65663a00 | cmd-5983a7cb-e1d7-4a13-aa30-b51ed8d33577 | start | failed：没有符合能力和安全要求的Partner |

真实发送者为叮当AIC `1.2.156.3088.1.0001.00001.EZTK03.WCU6LR.14YT`。本轮没有收到针对原task的continue。独立SDK公网probe的start/continue能通过，但不能替代该平台行为。

## 修改/同步文件

维护源码清单沿用 `../final-maintenance-audit/changed-files.md`，已包含并部署新增 `mq_partner_runtime.py`。部署的186项源码/静态资产见 `staged-correction.json` 的manifest；后续诊断脚本和状态文档同步记录见 `final-file-verification.json`。

本轮新增：`deploy/stage_maintenance_release.py`、`deploy/activate_maintenance_release.py`、部署计划与本报告证据目录。

本轮修改：`scripts/probe_group_workflow.py`（增加真实双群组验证）、`scripts/make_maintenance_review_package.py`（补阶段一数据、包含最新证据）、`STATUS.md`、`KNOWN_ISSUES.md`、`HUMAN_ACTIONS.md`、`CHECK_STATUS.json`。业务实现未再新增功能。

## 当前仍需解决

1. 平台默认在线发现：新部署后三身份心跳仍有真实Kafka ACK，但默认Discovery为空；需核查平台Writer/Redis/Outbox/Relay到发现服务的在线状态发布。不能通过关闭在线筛选伪造通过。
2. 叮当多轮主任务：需检查awaiting-input后的cancel/start决策和continue路由。不能把被取消的task偷偷复活。
3. 以上两项解决后继续真正三轮确认建单、重复确认、自动发现和平台后台访问统计验收。目前没有完成这些验收。

## 证据文件

- `backup.json`、`activation-result.json`、`server-before.json`、`server-after.json`
- `server-unittest-final.log`、`server-stage2.log`、`server-stage5.log`、`server-scenarios60.log`
- `formal-mq-test.json`、`formal-mq-test.log`、`public-leader-continue.json`
- `discovery-after.json`、`dingdang-runtime-evidence.json`
- `deployed-leader.log`、`deployed-resource-inbox.log`、`deployed-workorder-inbox.log`、`deployed-amp-heartbeat.log`
- `platform-online-query.png`、`dingdang-selected-leader.png`、`dingdang-round1.png`、`dingdang-round2-failed.png`

使用技能：Superpowers（计划、系统排错、完成前验证）、Computer Use（真实浏览器复测）。

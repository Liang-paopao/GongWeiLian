# 叮当多轮续接专项复测

日期：2026-10-07（Asia/Shanghai）。原始日志的 `Z` / `+00:00` 为 UTC。

## 结论和入口边界

**工维联端的三轮任务已通过梧桐叮当的官方开发者调试入口真实跑通。**

同一 session、同一主 task，第一轮提问，第二轮正式 MQ 查询资源并等待确认，第三轮明确确认后正式 MQ 预留资源、创建工单，平台收到 completed。工单：**WO-20261007-89643E**。

**首页卡片的“叮当多智能体协作”入口仍未修复。** 当前公开前端实现会先取消暂停的协作，再重新 execute；本项目不能改写平台的代码。因此不把官方调试入口通过写成首页卡片正常聊天通过。默认在线发现未在本轮修改，`platform_verified=false`。

本轮真实请求来自浏览器里的梧桐叮当服务，服务器校验的调用方为 `1.2.156.3088.1.0001.00001.EZTK03.WCU6LR.14YT`。没有用本机脚本冒充平台请求，没有替换消息或伪造 taskId。

## 根因调查

查阅了 [梧桐官方指南](https://wt.ioa.pub/docs.html)、已安装的 ACPs SDK v2.2.0 和 [当前平台公开客户端](https://wt.ioa.pub/dingdang/app.js?v=v1.8.2-aic-verify-20261004)。公开源码只读访问，没有读取浏览器 Token/Cookie 或调用未授权管理接口。

1. `sendMessage` 对协作会话调用 `continueSecretaryCollaboration`。该函数存在 run_id 时先执行取消，再走 `/agent/execute`；这是客户端固定行为，改变 Leader 的提示文字不能把它变为原任务的 continue。
2. 普通单智能体续接有独立的 `continueActiveAgentInteraction` / `/agent/continue` 分支。官方开发者工具也有同会话发送 messages 的入口，但只在 `awaiting-input` 时续接。
3. Leader 原来把“用户还没确认”的业务方案标为 `awaiting-completion`。SDK 默认 complete 是确认任务结果已经完成，不能把这个空确认自动等同于允许预留资源、创建工单。
4. 未确认方案尚未发生任何预留，但旧取消路径仍发起 MQ 释放；上一轮该网络往返约 22 秒，超过 Leader 取消响应等待时间。直接调长到 25 秒并不合适：官方客户端使用的默认 HTTP 超时也需要考虑。

## 实际修复

- `leader_external_flow.py`：方案等待人工确认改为 `awaiting_input`，问题明确展示设备、日期、开始时间、时长、人员和物品，仍要求用户显式回复确认。
- 从未预留的 proposed 方案取消时，本地记录 canceled，不发送多余的 MQ 释放任务。
- 如果存在有效预留、方案已离开 proposed 状态，或曾记录 reserve_resources 尝试，即使没有收到成功响应，也保留原补偿路径。
- 没有放宽身份绑定、跨会话访问、消息去重、人工确认或终态不可复活的规则。Runtime 仍支持完整任务状态和空 complete 的保护。

修改文件：`leader_external_flow.py`、`test_leader_external_flow.py`、`test_leader_rpc_runtime.py`、`deploy/activate_leader_continuation.py`；另更新评审打包工具和本报告、README 最新入口。

## 官方平台三轮实测

入口：梧桐首页右侧叮当 → 左下账号菜单 → **开发者工具** → **智能体响应调试**。ACS 使用 `platform/approved_acs/leader.json`，只含当前批准的真实 AIC、HTTPS endpoint、mTLS 和能力信息，不含私钥。

| 轮次 | 浏览器实际输入 | 平台返回 | 平台记录耗时 |
| --- | --- | --- | --- |
| 1 | 水泵001运行异常，帮我安排明天下午检查。 | awaiting-input；询问开始时间、时长 | 4.16 秒 |
| 2 | 下午两点开始，预计一小时，需要泵体检查技能。 | awaiting-input；待确认方案 | 18.27 秒 |
| 3 | 确认这个方案并创建工单。 | completed；WO-20261007-89643E | 7.56 秒 |

三轮共同的 session：`debug_4808e66359da4b3380540679941a4cbf`。

三轮共同的 task：`5caf3f09-19c1-4573-be2a-0a283821c438`。

数据库保存的命令序列为 `start → continue → continue`，没有 cancel 或替换主任务。完整 messageId 见 `id-map.csv` 和 `task-evidence.json`。

### 实际业务结果

- 检查设备：pump-001。
- 检查时间：2026-10-08 14:00–15:00，60 分钟。
- 人员：模拟人员甲。
- 物品：机械密封圈、便携检查工具包。
- 工单：WO-20261007-89643E；状态 confirmed。
- 确认前数据库：0 工单、0 预留。
- 确认后数据库：1 工单、3 条有效预留、1 条用户确认。
- MQ 子任务 query_resources、reserve_resources、create_work_order 均 completed。

这些是当前项目明确标注的模拟业务资源，通过真实平台通信和真实数据库执行，不代表已经通知现场人员。工单保留用于验收，未删除记录。

### 取消测试

另起独立任务：`4ebd484a-7eee-46dd-954f-0f50642a5d90`，为 pump-002 生成次日 15:00–16:00 的未确认方案，然后在官方调试页发送“取消任务”。平台返回 canceled，耗时约 3.62 秒；Leader accepted 至 canceled 约 24 毫秒，未发生 MQ 释放。最终数据库仍只有上面的 1 张工单及 3 条预留。

## 真实证据

- `debug-round1.png`、`debug-round2.png`、`debug-round3-completed.png`：官方调试入口三轮截图。
- `debug-round2-response.txt`、`debug-round3-response.txt`：页面显示的原始响应。
- `debug-cancellation-response.txt`、`debug-canceled.png`：取消返回。
- `platform-debug-logs.json`：平台“调试日志”页面中的本次 28 条请求/响应记录，包含 completed 工单结果。
- `platform-debug-logs.png`：平台调试日志截图。
- `confirmed-database.json`、`before-confirmation.json`：实际数据库业务记录。
- `platform/server-*.log`：Leader 与两个 MQ Partner 真实日志。
- `task-evidence.json`、`id-map.csv`：原始外部编号与状态关系。

调试日志是平台真实调用证据，但不等同于首页排行或平台注册后台的访问量截图；本轮没有宣称该统计界面验收通过。

## 测试与部署

采用 Superpowers / systematic-debugging / test-driven-development / verification-before-completion。先复现旧状态和多余 MQ 释放失败，见 `red.log`，再修复；未做前端改动。

- 针对性回归：47 项通过，`targeted-green.log`。
- 本机全量：262 项，261 通过、1 项因 Windows 无法创建符号链接跳过，`unittest.log`。
- 服务器全量：262/262 通过，`deployment/server-unittest.log`。
- 服务器 Direct RPC 阶段二与阶段五集成测试通过，见 `deployment/server-stage2.log`、`server-stage5.log`。
- 命令：`python -m unittest discover -p test_*.py`、`python run_stage2_tests.py`、`python run_stage5_tests.py`。项目没有单独 lint/typecheck/build 命令。

原代码、Nginx、systemd、配置和 SQLite 已备份到服务器 `/opt/gongwei/backups/20261007-083559-experience`。秘密备份仅保存在服务器受限目录，没有下载到报告。

独立 Leader 活动代码为 `/opt/gongwei/releases/20261007-083559-maintenance`；网页保持原 `/opt/gongwei/current`，只有 Leader 服务重启。两个 MQ Partner、网页、资源、工单、声音和心跳服务 PID 均保持不变，Nginx 哈希保持不变。没有改 AIC、证书或 MQ 配置。

## 剩余问题及下一步

1. 首页卡片协作模式的 cancel/start 固定逻辑仍存在。平台应在任务 awaiting-input 时传原 sessionId/taskId 调用 continue，并轮询至下一个等待/终态；确需替换整次协作时才取消。
2. 本轮通过的是官方开发者直连调试入口，不是首页普通聊天入口。该调试入口可用于当前三轮验收，但不适合作为最终普通用户界面。
3. 默认在线发现问题未修改；完整平台验收继续为 false。
4. 本轮没有在 completed 后通过调试页做重复确认，因为该页面在终态后会开启新任务。后端重复确认、补偿、恢复等既有回归仍通过，不能把它们当成本轮平台 UI 重复确认实测。

![官方入口返回 completed](debug-round3-completed.png)

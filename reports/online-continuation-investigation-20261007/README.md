# 在线发现与首页多轮问题复核

日期：2026-10-07，北京时间。当前真实项目：`gongwei-step1`。使用 Superpowers、systematic-debugging、test-driven-development、verification-before-completion 和浏览器工具。`platform_verified=false`。

## 当前结论

1. **默认在线发现已恢复。** 17:29 三个当前 AIC 的正式 ADP 精确查询全部返回 ACS、active=true、alive=true 和当分钟心跳。首页也显示 Leader 在线。
2. **叮当自然语言自动发现通过。** 未选智能体的新会话发送“帮我找一个能够处理设备异常、协调检查人员和工具、并创建检查工单的智能体。先查找，不要执行任务。”，推荐组合明确包含工维联核心业务 Leader。没有执行其他项目智能体。
3. **工维联能够多轮处理。** 此前叮当官方“智能体响应调试”已真实完成 start→continue→continue、两 Partner 正式 MQ、人工确认和唯一工单。详见 `../dingdang-continuation-20261007/README.md`。这不是本轮重新建的工单。
4. **首页普通协作仍不能按原任务续接验收。** 本轮 session_1723 的多次输入仍取消旧 task 并 start 新 task；历史会话重载还出现 conversation_id 类型错误。不能把“能连续输入文字”当成“能确认原方案创建唯一工单”。

## 一、发现故障定位及真实恢复

恢复前，最新 SDK 心跳年龄为 2.5–13.3 秒；三个 AIC 均得到 amp.heartbeat Kafka ACK。Writer 提交位点超过这些记录，但 ACK 本身不证明 Redis/Discovery 已更新。

只读 `GET https://wt.ioa.pub/discovery/admin/alive-sync/status` 返回：

```text
gap on shard hb-000
AliveSyncError: Provider /sync/snapshot 响应为空（无 meta 行）
lastDeltaAppliedAt = 2026-10-06T11:58:48.559912Z
kafkaNextOffset = 2380018
```

同时 alive-delta 队列末端已超过 2471787，说明旧结论“增量队列不再产生数据”已不适用。当前证据指向平台同步遇到序列缺口后不能取得有效快照；未取得 Monitor 内部日志，无法确定 Provider 空响应的更深层原因。

17:28:49，平台成功重新获取快照，lastError 变为 null，增量应用恢复。17:29 三个 AIC 默认精确查询全部成功。没有由本项目发起平台 resync/reset、修改共享索引或直接写入 alive-delta；平台恢复与聊天解析代码部署不能建立因果关系。

| 智能体 | 当前 AIC | 默认在线查询 |
|---|---|---|
| 工维联核心业务 Leader | 1.2.156.3088.1.BUPT.JSQB3Y.RN5ERG.1KIZGN.0M45 | 返回，alive=true |
| 工维联资源协调 Partner | 1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA | 返回，alive=true |
| 工维联工单处理 Partner | 1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF | 返回，alive=true |

此前两个其他项目返回在线，但 lastSeen 时间停留在前一天；结合本轮游标停滞，不能将其他项目的旧在线标记当成其当时端点实时可用的证明。

证据：heartbeat-source-and-ack.json、kafka-readonly-watermarks.json、discovery-status-after.json、discovery-status-latest.json、exact-aic-after-sync-recovery.json、homepage-leader-online-recovered.png、dingdang-auto-discovery-recovered.png、dingdang-auto-discovery-visible.txt。own-alive-delta-readback.json 实际读取零条记录，这次读取没有结论，不能用它证明某 AIC 不在队列里。

## 二、首页真实聊天与修复

### 本轮真实会话

- sessionId：session_1723。
- 首轮：“水泵002运行异常，帮我安排明天下午检查。”
- 第一 taskId：c0c8efeb-5fc7-483f-8061-3110364c6bac，返回 awaiting-input，之后被平台 cancel。
- 第二轮：“下午三点开始，预计一小时，需要泵体检查技能。”
- 第二 taskId：826e7f98-dedd-4553-96d2-6424a5bdb3ba，平台以 start 新建，资源查询完成，但旧解析器误把叮当问题中的例子 14:00 当成了用户要求。
- 修复部署后重试修改：第三 taskId 4f099dd8-9909-4e70-a078-814a4a4e5548。解析后的真实检查请求已是 2026-10-08 15:00–16:00，但 MQ 重新入群卡住，页面未完成方案回复。后续修复、独立正式 MQ 诊断的结果另见文末记录。
- 页面恢复历史会话后再次发送，叮当先于调用 Leader 返回 `conversation_id` 应为 string、实际 input=1723 的参数错误。这是另一项平台客户端/接口兼容问题。
- 本轮没有确认错误的 14:00 方案，没有新增工单或正式资源占用。

### 已修改代码

`agentic_core.py` 兼容首页省略“用户原始需求”标签的转发格式，递归保留各轮真实用户补充，排除叮当问题、示例时间、候选方案与 DAG 引用。空回答不会采用提问中的默认时间。没有把引用中的“确认”转换成创建工单授权。

新增三项解析测试，修复前均真实失败，修复后通过。正式 Leader 已部署到 `/opt/gongwei/releases/20261007-092609-maintenance`。

`mq_partner_runtime.py` 为旧 SDK 客户端清理加入超时处理；超时后关闭该群组独立连接，确认无活动 transport 后才允许重新入群。保留官方 SDK 的邀请、身份校验、AMQP 协议和结果返回。使用真实 SDK 和 aio-pika 对象补测已删除队列及 transport 已清除但 is_closed 未置位的情况。

Partner 最终部署目录 `/opt/gongwei/releases/20261007-095036-maintenance`。两次激活均先备份；Nginx 文件哈希保持一致，未修改网页、其他项目、证书、AIC 或数据库结构。

### 可用替代入口与边界

- 现有工维联网页可以完成多轮业务。
- 叮当“开发者工具 → 智能体响应调试”使用官方 continue 接口，已有真实三轮和工单记录。
- 要让叮当首页也保持同一主任务，需要平台将等待输入的成员路由到已有 `/agent/continue` 分支。当前公开客户端的普通协作分支仍 cancel 后 `/agent/execute`。
- 可以另行设计按明确方案编号跨新任务确认的业务兼容，但它不等于外部 taskId 不变；必须校验调用者、方案版本与显式确认。当前没有加入“忽略 cancel、自动复活已取消方案”的逻辑。

## 三、测试与部署证据

- 本地：269 项，268 通过、1 项 Windows 符号链接权限条件跳过。
- 服务器：269/269 通过。
- 本地与服务器的 run_stage2_tests.py、run_stage5_tests.py 全部通过。
- 有 ResourceWarning 来自故意触发 HTTP 404 的测试；没有测试失败。
- 没有修改前端，不涉及新增前端构建或视觉验收。
- 本轮运行了 `python -m unittest discover -p test_*.py`、`python run_stage2_tests.py`、`python run_stage5_tests.py`、部署脚本、官方 ADP 只读查询、服务器 SQLite 只读核验、浏览器真实对话与自然语言发现。

主要日志：local-verified-tests.json、local-verified-*.log、deployment/、partner-deployment-final/、platform/、platform-after/。每次部署的 backup.json 给出服务器本地受保护备份位置；没有下载数据库、私钥或证书。

## 四、修改文件

- agentic_core.py
- test_agentic_core.py
- mq_partner_runtime.py
- test_mq_partner_runtime.py
- deploy/activate_partner_recovery.py
- HUMAN_ACTIONS.md
- CHECK_STATUS.json
- 本目录的真实报告、日志、截图及诊断材料。

## 五、未完成事项

- 首页普通协作连续三轮确认并创建唯一工单尚未通过，不能替代为调试入口或本地测试通过。
- 首页历史会话恢复的 conversation_id 类型错误，需要平台处理。
- 已恢复的默认在线发现是本轮实测结果，不承诺平台今后不会再次同步中断。
- 最终仍保持 platform_verified=false；不重新注册、不更换身份、不降低身份绑定。

## 六、最终正式 MQ 重建复测

实际连接梧桐正式 AMQPS，使用当前 Leader 身份邀请服务器正在运行的两个 Partner；未额外启动 Partner Inbox 消费者，没有使用 RPC 回退。

- session：mq-rejoin-036300ce924a428dbefbd310d57c6914。
- 第一次邀请两 Partner、资源查询完成：17,773.18 ms。
- 关闭第一个 Leader SDK 协调实例并解散此诊断群组，然后重建同一 session/group，两个 Partner 重新加入，资源查询再次完成：29,313.74 ms。
- 两次响应均使用实际保存的检查请求，start_at=2026-10-08T15:00:00，end_at=2026-10-08T16:00:00。人员/库存来自当前数据库的演示种子资源，响应保留 simulated=true；MQ 连接、邀请和业务查询是真实执行。
- 工单数前后均为 1，活动预留前后均为 3；本轮诊断没有创建工单或预留资源。
- 结果：`mq-rejoin-probe-fixed.json` 的 pass_result=true；日志：`mq-rejoin-probe-fixed.log`。这是正式 MQ 诊断，不冒充叮当浏览器调用。
- 前一次真实复测因 aio-pika 的 transport 已移除但 is_closed 仍为 False 而未通过，失败材料保留在 mq-rejoin-probe.json/.log。针对该实际错误补了真实 aio-pika 回归测试后才完成本次复测。

最终原始服务、数据库、协议任务证据位于 final-state/，首页 session/task/message 对照位于 homepage-protocol-final.json。完整测试与最新源码一起进入评审包；秘密配置、证书、私钥和数据库排除。

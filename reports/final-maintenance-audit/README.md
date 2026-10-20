# 工维联项目清理与维护审计（2026-10-07）

实际项目：`G:\My Work\杂\论文单（2025）\智能体辅导\gongwei-step1`。没有新建替代项目。

## 结论

已检查第一方源码、测试、部署脚本、配置、文档及运行资产，修复有复现证据的问题。**本轮改动在本机验证，未部署到服务器。platform_verified=false。**

平台首页的“上新”卡片确实包含三个智能体。实时Discovery的全alive状态查询也返回它们；但默认在线查询仍为空，不能把目录存在说成在线可调用。

## 清理

- 598个历史报告、重复压缩包、日志和缓存已送Windows回收站，可恢复；未永久销毁。
- 自动安全审查拦截了最初的批量永久删除，改用可恢复方式完成清理。
- 历史唯一证据汇总为 `archive/evidence-before-cleanup-20261007.zip`（16,120,713字节），CRC和逐文件SHA-256核对通过。
- 保留3个仍被进程占用的日志。源码、用户原始材料、数据库、原始录音、声音模型、秘密、证书及依赖环境保留。
- 当前批准ACS从历史过程报告中独立归档到 `platform/approved_acs/`；注册模板和本机运行所需ACS仍保留。
- STATUS、KNOWN_ISSUES、HUMAN_ACTIONS和CHECK_STATUS已收敛为当前结论，旧版本保存在归档中。

详见 `cleanup-plan.json`、`cleanup-result.json`。清单中的holding_directory是中转路径，已送回收站，不再存在。

## 实际修复

1. **MQ群组**：默认Group ACL地址纠正为已实测的9007；序列化官方SDK创建/邀请阶段，避免同Partner并发邀请冲突；SDK回收会话后可重建；关闭时取消等待并清理。Partner每个群组使用独立官方客户端，Inbox独立监听，并发任务通过ContextVar选择对应回包客户端。
2. **外部Inbox**：fresh start建立持久业务会话；仅start可创建；校验调用者、入口及会话归属；取消返回正式canceled终态，不能被后续命令复活。
3. **确认与幂等**：取消后不能确认建单；取消走资源/工单补偿事务；旧message重放不覆盖较新的任务时间；请求技能真正参与人员筛选。
4. **真实网页修改失败**：浏览器触发500后定位SQLite嵌套写事务。修复已有方案读取时的嵌套锁；14点改15点以新子任务重新查询资源、递增方案版本，保持同一主任务/方案；保留原始异常描述。
5. **审计与网页控件**：审计接口读取当前GONGWEI_LOG_DIR，避免旧日志掩盖当前结果；修复设备/状态下拉筛选；“已配置候选”不再显示绿色在线状态。
6. **启动与测试隔离**：只停止身份完全匹配的本项目进程；启动做真实健康检查并传播退出码；阶段测试使用临时DB、随机回环端口和独立日志；音频测试不写业务库和上传目录。
7. **ACS工具**：使用当前批准AIC，拒绝旧身份与覆盖批准输入；HTTPS端点必须显式提供，不能凭基址编造三个路由；拒绝示例域名；草稿保留当前HTTPS Leader和AMQPS Partners。
8. **声音/数据输入**：WAV解码前验证格式、采样率、帧数、声道与内存上限；ZIP写入路径必须位于输出目录；HTTP Range短响应立即失败。没有下载数据或重训声音模型。

详见 `continuation-audit.md`、`source-audit.md`、`discovery-mq-amp-audit.md`。这些分项报告保留发现顺序，最终状态以本汇总为准。

## 实际验证

|检查|最终结果|证据|
|---|---|---|
|全量unittest|258项：257通过，1项Windows符号链接权限跳过|unittest-final.log|
|阶段二真实本机AIP|通过：创建→确认→重复确认→取消→服务重启保留|stage2-final.log|
|阶段五真实本机AIP|通过：局部重排、幂等、故障补偿、重启恢复|stage5-final.log|
|固定业务场景|60/60通过|scenarios-final.log|
|网页JS控件与语法|4项行为检查通过，node --check通过|scripts/test_web_controls.cjs|
|四服务启动器|启动/重复启动/停止均退出0，端口释放|local-launcher-integration.json|
|全部第一方文件静态检查|Python AST / JSON / TOML检查通过|source-file-validation.json|
|MQ多群组修复|官方SDK模型及网络边界替换测试通过|mq-partner-isolation-tests.log|
|服务器只读复核|7个业务服务及心跳服务active/enabled；业务库integrity=ok、0工单、0有效预留|server-current/server-final-state.json、heartbeat-service-current.json|

MQ新增隔离修复尚未在正式服务器运行。官方本机acps-infra测试明确BLOCKED（无Docker），未安装Docker、未用自制broker冒充。测试输出中的BLOCKED不能解释为该集成已通过。

实际执行命令：

```text
.venv/Scripts/python.exe -B -m unittest discover -v
.venv/Scripts/python.exe -B run_stage2_tests.py
.venv/Scripts/python.exe -B run_stage5_tests.py
.venv/Scripts/python.exe -B scripts/run_60_scenarios.py
node scripts/test_web_controls.cjs
node --check web/app.js
git diff --check
```

全量测试进程设置临时DB/日志、本机传输；最终命令、耗时和退出码见 `verification-final.json`。无package.json、未配置独立lint/typecheck/build命令；没有伪称执行这些命令。

## 浏览器实测

实际运行本项目的临时数据库、四个本机HTTP服务，使用真实API及种子资源（页面明确标模拟业务数据）：

1. “水泵001运行异常，帮我安排明天下午检查。” → 询问开始时间、时长。
2. “下午两点开始，预计一小时，需要泵体检查技能。” → 14:00–15:00待确认方案。
3. 点击修改时间，发送“刚才那个方案时间不合适，改到下午三点。” → 同主任务/方案更新为15:00–16:00；确认前0工单、0预留。
4. 点击确认 → 工单 **WO-20261007-3950EB**；再次确认返回同一编号。数据库只有1工单、3条active预留。
5. 设备选“循环水泵002”及状态选“已完成”分别过滤成0条；重置恢复1条。
6. 点击取消工单 → 该单cancelled，active预留降为0，DB integrity=ok。

截图：`browser-awaiting-input.png`、`browser-revised-plan.png`、`browser-completed.png`、`browser-orders.png`、`browser-cancelled.png`。数据库证据见三个 `browser-*-confirm.json` / `browser-after-cancel.json`，完整服务日志见 `browser-runtime-logs/`。四个隔离测试进程已停止。

**这组截图属于本机网页验收，不属于梧桐叮当调用。**

## 两个正式平台问题及解决路径

- **群组403**：旧443 `/mq-auth/` 没有得到客户端证书；已有正式9007 mTLS Group API成功证据，线上已使用9007，本轮修复了仍遗留旧地址的本地默认值。无需删除/重新注册或关闭身份绑定。
- **在线状态**：AIC、active、skill过滤、请求路径均已通过真实响应核对。三个AIC同条件默认查询为空，全alive状态则正确返回。仍需平台核查Writer→Redis/Outbox→Relay→Discovery；不能由本项目伪写online状态。
- **叮当续接**：真实服务持久记录仍是cancel/start新task；公网SDK continue成功不等于叮当成功。还需核对叮当continue及业务确认协议。

本轮没有强行放宽在线筛选，也没有改用静态ACS冒充实时发现。全部正式闭环通过前保持platform_verified=false。

## 交付物与技能

当前源码小型评审包：`reports/gongwei-maintenance-review-20261007.zip`，散列和大小见 `package-result.json`。不含秘密、证书、数据库、原始录音、历史压缩包或依赖环境；包含现有小型声音基线及本轮真实证据。

实际修改文件见 `changed-files.md`。使用Superpowers、系统化调试、TDD、完成前验证；网页小修使用frontend-design与Impeccable。不涉及Three.js。服务器部署与正式平台回归是尚未完成的步骤。

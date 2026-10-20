# 工维联正式接入阻塞修复执行计划

> 执行方式：Superpowers 系统排查、TDD、分项验证；AMP 独立子任务由 subagent-driven-development 执行，其余按依赖顺序操作。用户已授权继续修复、使用三个新身份及必要的服务器接入操作。

**目标：** 修复工单凭证、官方 Group API 配置和正式入口的 AMP 心跳缺口，逐项实测；不能用本地日志代替平台在线和叮当验收。

**架构：** 保留现有业务、数据库和 local_rpc。正式 Leader 接受 mTLS Direct RPC，出站使用官方 GroupLeader/MQ Inbox。心跳由官方 HeartbeatEmitter 写入 NDJSON，网络采集走官方 Fluent Bit/Kafka；缺少有效外部接收链路时明确记录失败。

**技术：** Python 3.14、ACPs SDK/CLI 2.2.0、SQLite、AMQPS/mTLS、systemd。

## 执行结果（2026-10-07 收口）

下方清单保留最初计划；以本段实测记录为完成状态。详细证据位于 `reports/platform-fixes-20261007/README.md`。

- [x] 官方 CLI 登录、工单 EAB/clientAuth 与脱敏校验记录。
- [x] 正式三身份 MQ：邀请、加入、查询、预留、工单、原 messageId 重放及客户端重建；10 子任务，唯一工单和预留保持。
- [x] 官方 AMP HeartbeatEmitter 生命周期；三正式入口实际就绪后写入，重连通道就绪检查，关闭停止；TDD 和独立审查通过。
- [x] 服务器一致备份、新身份隔离上传、systemd 扁平 credentials 路径修复；原网页功能保留。
- [x] 经用户明确授权升级 Nginx/安装 stream；SNI 透传、公网 mTLS/senderId 绑定、原五站及客户端 IP 逐项验证。
- [x] 三个正式服务 active/enabled；两个 Inbox 实际监听，Leader 公网真实响应。
- [x] 叮当卡片首轮 awaiting-input；第二轮取消响应问题按官方语义修复，新增 6 项测试并部署复测。
- [x] 全量 175 项单元、阶段二、阶段五、Linux 定向 64 项；语法编译和 git diff --check 通过。
- [x] 状态文档与实际 Discovery、叮当、服务器日志更新。
- [x] 评审 ZIP 已生成，排密扫描与 ZIP CRC 通过；文件哈希见 `reports/platform-fixes-20261007/package-result.json`。
- [ ] AMP 网络转发：正式 Kafka/TLS 握手 EOF，缺平台可用接入参数。
- [ ] 默认在线发现与同主 taskId 续接：Discovery 目录有记录但在线为空；叮当 cancel 后另建任务，第二轮失败。
- [ ] 叮当两 Partner、人工确认唯一工单、后台统计、自动发现对话、整机重启整体验收。

`platform_verified=false`。外部闸门未通过的项目没有勾选；不因本机或独立 MQ 通过就视为平台验收通过。

## 已核实的起点

- 三个新 1.1.0 注册均 APPROVED；Leader serverAuth 已含 leader.yanyi.online DNS SAN。
- Group API 9007 真实通过，原 443 /mq-auth/ 返回 403；Discovery 已有三个新 ACS，但默认在线查询为空。
- 正式 AMP 文档公布规划外部 Kafka/TLS wt.ioa.pub:19092；实际本机验证 TLS 握手收到 EOF，须与服务器路径对照，不能降级明文。
- 生产四个 local_rpc 服务正常，独立 Leader inactive；新身份此前未部署。

## 顺序与闸门

### 1. 证书（secrets/identity-generations/20261006-reregister）

- [x] 复现 EAB 401；得到用户明确允许后使用官方 CLI 隐藏密码输入登录，不在命令参数或文件中保存密码。
- [x] 获取工单独立 EAB/clientAuth；验证 AIC、用途、密钥、有效期和 trust bundle。
- [ ] 保存脱敏元数据；后续 CLI 操作串行，避免并发刷新会话。

### 2. 正式三身份 MQ 实测

- [ ] 新增隔离诊断 scripts/probe_group_workflow.py，复用官方 adapter/handler，不复制业务。
- [ ] 真实创建群组、两 Partner Inbox 邀请入群，查询→预留→创建→重复操作，验证一张工单与一次预留。
- [ ] 关闭并重新建立客户端/群组后复用同一 SQLite 与幂等键，验证结果保持；保存所有任务消息 ID 与四种状态。
- [ ] 配置仅通过显式 auth_service_url=9007，禁止自动回退 443/RPC。

### 3. 官方心跳生命周期（AMP 子任务）

- [ ] 先写 test_amp_runtime.py 失败测试，再新增 amp_runtime.py。
- [ ] 正式入口 run_leader_rpc.py、run_partner_inbox.py、run_leader_inbox.py 就绪后写首条真实心跳，关闭后停止，启动失败不写。
- [ ] 使用 GONGWEI_AMP_LOG_DIR/GONGWEI_LOG_DIR；修复 Inbox 日志路径忽略部署可写目录的问题。
- [ ] 按真实连接状态处理暂停/恢复；不自行写 observedTimestamp、不回放历史心跳冒充在线。
- [ ] 运行 `.venv/Scripts/python.exe -m unittest test_amp_runtime -v` 和所有入口回归。

### 4. 服务器安全闸门

- [ ] 先备份 /opt/gongwei 现有发布、工维联 systemd、Nginx 配置与 SQLite 一致快照，验证数据库与备份可读。
- [ ] 安全上传新身份到独立目录，校验与原目录不同代；只切换工维联自己的秘密/服务。
- [ ] 原网页模式保持可用，直到真实在线发现与 MQ 工单流程就绪；不能提前切换后让网页业务失败。
- [ ] 独立 Leader 的 TLS/SNI 入口需实测原始客户端证书与 hostname。涉及共用 443 时只有 nginx -t、其他站点前后对照与回滚就绪才 reload。
- [ ] 若正式 AMP TLS 或认证不可用，只暂停该网络上报/依赖验收，继续本机修复与测试；不安装无用依赖或关闭 TLS。

### 5. 验证与交付

- [ ] `.venv/Scripts/python.exe -m unittest discover -v`。
- [ ] `.venv/Scripts/python.exe run_stage2_tests.py`。
- [ ] `.venv/Scripts/python.exe run_stage5_tests.py`。
- [ ] 实际发现响应、服务器与平台网络结果写入 reports/platform-fixes-20261007/。
- [ ] 更新 CHECK_STATUS.json、HUMAN_ACTIONS.md、STATUS.md 与不含秘密的评审 ZIP。
- [ ] 只有叮当与自动发现、后台访问完整验收才能 platform_verified=true；本轮未全部取得回执就保持 false。

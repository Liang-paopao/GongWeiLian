# 工维联界面改版与平台有限重试实测报告

日期：2026-10-07（中国标准时间）。证据中的 `Z`/`+00:00` 为 UTC。

## 结论

- 四个已有页面已按供应商 image2 的独立设计图重排，已部署到 https://gongwei.yanyi.online/ 。数据继续来自原业务 API，没有复制设计图示例数据，没有新增业务功能。
- 本地网页完成了补充信息、修改时间、确认、重复确认、工单状态变更、取消、资源释放和声音辅助的真实流程。
- 正式叮当调用有进展：第一轮收到补充问题，第二轮已真实通过正式 MQ 调用资源 Partner 并生成待确认方案，不再被 Partner 查询为空阻塞。
- **完整叮当验收仍未通过。** 叮当第二轮仍 `cancel + start`；最后一次补充又尝试取消，页面报告“目标智能体尚未确认取消”。后台稍后完成取消及资源释放。
- 默认在线 Discovery 仍为空。显式平台目录查询能返回三项真实 ACS，目录可查不等于在线验证通过。`platform_verified=false`。
- 本轮叮当没有完成确认创建工单；服务器工单数 0、有效资源预留数 0，SQLite integrity 为 `ok`。未把本地网页工单当作叮当平台成功。

## 设计与实施

使用技能：Superpowers（调试、测试、完成验证）、Impeccable、frontend-design、image-to-code、imagegen、Design Spells。未引入 Three.js。

图像生成使用 `config.toml` 当前供应商的 `gpt-image-2`，四条提示均以 **“使用config.toml的供应商生成图片：”** 开头。图片和不含凭证的提示保存在 `output/imagegen/`。生成用到的 OpenAI/Pillow 依赖装在项目外的独立图像工具虚拟环境，未变更业务依赖。

参考 [Linear 官方 UI 改版说明](https://linear.app/now/how-we-redesigned-the-linear-ui) 的导航对齐、层次和减少视觉噪声原则。动效限定为短淡入、轻微位移、输入框焦点和按钮反馈，支持减少动态效果设置。

- 主协作：深绿侧栏、宽对话区、右侧方案与下一步操作。
- 方案确认：检查单主体、资源明细、需求与协作者摘要。
- 工单中心：横向筛选、列表、工单详情。
- 资源与审计：资源目录、任务轨迹、调用记录；业务状态用中文，原始 JSON/技术 ID 折叠。
- 图像模型生成的“新增资源”等无现有后端功能没有加入页面。

## 平台修复及边界

### Partner 查询

`GONGWEI_PARTNER_DISCOVERY_POLICY=platform_catalog` 是明确配置的第二种查询策略。它调用正式 Discovery 的部署扩展 `extFilter.alive`，并要求预先配置对应角色的真实 AIC；继续校验 active、协议、技能、输入、AMQPS、mTLS 和 Inbox/AIC 对应关系。

来源记录为 `discovery_catalog`，活性记录为 `unknown`，不标记在线，不回退静态 ACS，不回退 local_rpc。默认 `default_online` 策略仍严格失败。

`discovery-final/` 保存三个 AIC 两种查询的真实响应：三项 `indexed=true`，三项 `default_discoverable=false`。

### 叮当多轮

外部 Product 增加明确 continue 指令、原 session/task 提示和待确认问题。实际叮当仍选择取消旧任务再新建，因此仅增加指令没有改变平台的调度行为。

| 环节 | 实际结果 |
| --- | --- |
| 选中 Leader 卡片 | 成功，有页面截图 |
| 第一轮 | accepted → working → awaiting-input |
| 第二轮 | 同一 session，但旧 task 被取消、新 task 被创建 |
| 资源查询 | 正式 MQ 成功；子任务 query_resources completed |
| 方案 | 返回 awaiting-completion；首次方案误取引用中的 30 分钟 |
| 时长解析修复 | 忽略转发文本中的助手举例，独立解析原始用户请求与最新回答；实际输入回归测试通过 |
| 修正后浏览器补充 | 叮当再次发 cancel，页面提示取消尚未确认；未实际进入修正后方案生成 |
| 取消后台结果 | 资源释放子任务 completed，外部任务最终 canceled |
| 工单确认/创建 | 本轮未完成，未确认错误的 30 分钟方案 |
| 自动发现 | 默认查询仍为空，未声明通过 |

主 session：`session_1703`。

- 第一轮 task：`c9ea98aa-fcf7-42b3-89da-36b26aa1ec2b`。
- 第二轮 task：`c3a2809e-d5e5-4246-8f1e-1eb86daad30e`。
- 完整 command/message ID、状态时间和两项 MQ 子任务见 `platform-final/id-map.csv`、`task-id-map.json`、`database-evidence.json` 和三个服务日志。
- 按平台命令 `sentAt` 至 Leader 对应状态计算：首轮约 0.51 秒，第二轮方案约 11.74 秒，最后取消约 22.61 秒。这是协议状态耗时，不是精确浏览器端到端延迟。
- 此轮没有抓取新的平台注册后台访问量截图，不能以服务日志替代该项验收。

## 自动测试与浏览器验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 本机 Python 全量 | 261 项，260 通过、1 跳过 | unittest.log；Windows 符号链接创建不可用，服务器已覆盖该项 |
| 服务器 Python 全量 | 261/261 通过 | final-deployment/server-unittest.log |
| 本机/服务器 Direct RPC 业务集成 | 通过 | stage2.log、final-deployment/server-stage2.log |
| 本机/服务器阶段五可靠性 | 通过 | stage5.log、final-deployment/server-stage5.log |
| 新外部文本与状态回归 | 49 项通过 | forwarded-parser-tests.log |
| JS 控件/状态检查 | 10 项通过 | web-controls.log |
| JS 语法 | 通过 | node --check web/app.js |
| 四页面 × 三桌面尺寸 | 12 组无横向溢出，切页回顶部 | responsive-checks.json |
| 本地与部署网页控制台 | 核验时无 error/warn | browser-observations.json |
| 部署网页四页切换 | 通过 | public-page-checks.json、deployed-*.png |

主要命令：

```text
.venv/Scripts/python.exe -m unittest discover -p test_*.py
.venv/Scripts/python.exe run_stage2_tests.py
.venv/Scripts/python.exe run_stage5_tests.py
node scripts/test_web_controls.cjs
node --check web/app.js
deploy/deploy_experience_refresh.py prepare / test / activate
```

最终部署使用同一部署模块，报告目录独立设为 `reports/experience-refresh-20261007/final-deployment`，避免覆盖首次备份。没有 package.json 或独立 lint/typecheck/build 命令。

### 本地网页业务证据

测试使用临时 SQLite 和真实本机 ACPs 服务，未向服务器数据库写入本地演示工单。

1. 信息不足时提问，补充后生成 60 分钟方案。
2. 修改为 15:00 后生成 15:00–16:00 方案。
3. 确认前：0 工单、0 预留。
4. 确认及重复确认后：仅 1 工单，人员、配件、工具共 3 条预留，没有重复占用。
5. 工单状态改为执行中后取消：原 1 工单变为 cancelled，3 条预留均 released。
6. 第二项未确认方案执行取消，确认按钮禁用。修复取消后协作栏误显示“处理中”的问题。
7. 公开泵声音样例通过原声音 Partner 实际检测，显示“未发现明显异常”，不自动创建工单。仅属冒烟测试，不代表准确率。

对应证据：`ui-before-confirmation.json`、`ui-after-duplicate-confirm.json`、`ui-after-cancel.json`、`local-ui/`、`audio-smoke-result.png`。

## 部署状态

最终活动版本：`/opt/gongwei/releases/20261006-211426-maintenance`。

备份：`/opt/gongwei/backups/20261006-211426-experience`。包含原代码、Nginx、systemd、配置及两个 SQLite 一致性备份；留在服务器受限目录，未放入评审包。

8 个既有服务全部 active：web、resource、workorder、audio、leader、resource-inbox、workorder-inbox、amp-heartbeat。网页继续独立 local_rpc；正式 Leader 继续 HTTPS/mTLS 接入并使用 MQ Partner。三套身份、证书、MQ 地址未更换。

Nginx 文件哈希未变化，其他项目服务未修改。部署期间两个 MQ Partner 的旧进程退出超过 systemd 停止时限，由 systemd 终止后正常重启；这属于待改进的优雅退出问题，不能宣称无缝重启。重启后两个 Inbox 监听、入群、资源释放均有真实日志。

## 本轮修改文件

- `web/index.html`、`web/styles.css`、`web/app.js`：四页布局、视觉、技术详情收纳、按业务状态禁用操作与中文状态。
- `partner_resolver.py`、`test_partner_resolver.py`：显式平台目录策略与真实身份约束。
- `leader_external_flow.py`、`test_leader_external_flow.py`：外部 continue/确认说明及安全回归。
- `agentic_core.py`、`test_agentic_core.py`：叮当转发内容中助手示例不能覆盖用户时长。
- `scripts/test_web_controls.cjs`：忙碌、完成、取消、重复确认和健康状态检查。
- `DESIGN.md`、`docs/experience-refresh-20261007.md`：设计与实现记录。
- `deploy/deploy_experience_refresh.py`：备份、测试、切换、失败回滚与逐服务核验。
- `scripts/make_experience_review_package.py`：本轮源码与证据打包、秘密排除和校验。
- `output/imagegen/`、本报告目录：四张设计图、真实截图、日志与验证材料。

数据库结构、API、AIC、证书、业务路由没有变更，已有声音、幂等、补偿和恢复测试保留。

## 当前未完成

1. 平台默认在线发现仍空；显式目录查询已可用，但在线索引/活性判定没有因此改变。
2. 叮当继续使用 cancel/start；最后取消确认等待也未被页面正确衔接。未完成同一外部主任务的三轮工单闭环。
3. 转发时长解析已修复并部署，修正后的浏览器新方案尚未生成；不能当作平台端到端通过。
4. 本轮没有叮当 completed 工单结果、重复确认结果、自动发现命中或新的后台访问量截图。
5. MQ Partner 优雅退出超时需后续专项处理，当前启动和连接可用。
6. 页面刷新会回到新的对话视图；数据库记录仍保留。自动恢复浏览器当前对话不是本轮新增功能。

遵照“再试一次，不行就这样”，本轮到此停止平台兼容性扩展，不放宽身份验证或人工确认门槛。

## 截图

以下是连接原业务 API 的真实运行页面，包含明确标注的模拟业务资源，不是 image2 设计稿：

![主协作](final-主协作.png)
![方案确认](final-方案确认.png)
![工单中心](final-工单中心.png)
![资源与审计](final-资源与审计.png)

服务器当前页面见 `deployed-主协作.png` 等四张截图；平台过程见 `dingdang-*.png`。

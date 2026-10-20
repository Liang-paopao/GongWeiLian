# 浅色精密工作台验收与最终交付复核

日期：2026-10-08。实际项目：`gongwei-step1`。当前阶段：已批准的四页前端落地、服务器发布与交付缺项核对。

## 1. 本轮结论

四页新界面已在现有项目实现并部署至 https://gongwei.yanyi.online 。网页完整业务流程、22 组前端控件回归、全部 Python 单元测试、阶段二、阶段五及 60 场景通过。8 个线上服务 active/enabled；本轮没有重启服务，Nginx 哈希、服务 PID、数据库记录均与发布前一致。

**还不能确认整个项目只剩技术方案 PDF 和演示视频。** 当前平台完整验收仍为 `platform_verified=false`：最终安全版的叮当新三轮、重复确认及独立修改/取消尚未完成复测；本轮叮当显示未登录，已打开登录弹窗。平台公开匹配统计在已知真实调用时段仍未检出本项目 AIC。共享服务器整机重启闸门也未实际执行。

已完成与未完成以本报告的证据分开记录；本地网页不替代叮当正式调用。

## 2. 使用技能和修改范围

使用 Superpowers（计划、增量修改、测试、独立审查、完成前验证）、frontend-design、Impeccable、design-spells、computer-use。未使用 Three.js。视觉方向已由用户确认，本轮没有再生成示意图。

本轮产品代码只修改：

- `web/index.html`：统一浅色导航、四页布局、默认折叠技术信息、语义标签、可选上传入口。
- `web/styles.css`：统一颜色、字号、留白、表格与响应式规则，修正窄屏隐藏文字定位造成的溢出。
- `web/app.js`：真实数据呈现、筛选与详情一致性、取消/完成操作状态、北京时间、任务审计隔离和对话保留。
- `scripts/test_web_controls.cjs`：保留原 10 组检查，扩展至 22 组。
- `deploy/deploy_precision_frontend.py`：限定三个前端文件的备份、原子替换、验证与失败回滚。

文档修改：`DESIGN.md`、`README.md`、`STATUS.md`、`CHECK_STATUS.json`、`KNOWN_ISSUES.md`、`HUMAN_ACTIONS.md`、实施计划及本验收目录。完整清单见 `changed-files.json`。

业务逻辑、接口路径、数据库结构、AIC、MQ 和证书配置没有修改。没有安装依赖，没有更换身份或重新注册。已有仓库的其他历史修改不计入本轮。

## 3. 自动验证

| 检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| `node --check web/app.js` | 通过 | `test-results.json` |
| `node scripts/test_web_controls.cjs` | 22 组通过 | `web-controls-final.log` |
| `.venv/Scripts/python.exe -m unittest discover` | 291 项，290 通过、1 跳过，无失败 | `unittest-final.log` |
| `run_stage2_tests.py` | 通过 | `stage2.log` |
| `run_stage5_tests.py` | 通过 | `stage5.log` |
| `scripts/run_60_scenarios.py` | 60/60 | `scenarios.log` |
| 独立代码审查 | 所有发现均修正，未留本轮阻断问题 | `code-review.md` |
| 浏览器控制台 | 本机与线上未检出 error | `browser-console.json` |
| 响应式 | 16 组，均无整页横向溢出 | `responsive-metrics.json` |

Windows 跳过项为符号链接权限要求。项目为原生 HTML/CSS/JS，没有另设 package.json、打包、lint 或 typecheck 任务。首次单元测试因按钮文案合同失败，已修复并重新运行；初次结果保留于 `unittest.log`，最终结果以 `unittest-final.log` 为准。Windows 输出编码已从 GB18030 无损转换为 UTF-8，未改测试结果。

日志中的 `MQ INBOX INTEGRATION BLOCKED` 来自检查“缺少官方本机环境时必须明确阻断”的负向测试，不能解释为本机 broker 验收通过；本轮没有安装 Docker/acps-infra。

## 4. 网页真实流程

在现有代码中启动四个 `local_rpc` 服务，使用本验收目录中的隔离 SQLite：资源 18212、工单 18213、声音 18214、网页 18210。所有 `/health` 返回正常；没有复制业务项目或使用假的响应。

### 第一笔验收工单

1. 输入“水泵001运行异常，帮我安排明天下午检查。”：实际返回缺少开始时间和时长的问题。
2. 输入“下午两点开始，预计一小时，需要泵体检查技能。”：真实查询人员与库存，生成 2026-10-09 14:00–15:00 的待确认方案。
3. 点击“修改安排”并发送改到下午三点：同一任务重新查询，方案变为 15:00–16:00。
4. 确认前数据库为 0 工单、0 有效预留；点击确认后创建 `WO-20261008-6AB9EA`，产生 3 条预留。
5. 使用相同任务确认请求重投：后端实际返回 `idempotent=true`，仍为 1 张工单、3 条预留；见 `duplicate-confirm.json`。这是本机接口重投，未冒充叮当重复调用。
6. 在工单中心点击开始处理、取消工单：状态真实改变，原工单的人员、配件、工具三条预留均 released。

### 第二笔与其他交互

- 信息不完整时点击“取消本次任务”，随后新建任务可正常执行。
- 第二笔 `WO-20261008-2B4A62` 完成用户确认、开始处理、标记已完成全过程。
- 在“待处理/处理中”筛选下状态改变后，旧工单移出列表且详情正确清空；设备空筛选、重置、刷新均运行。
- 人员/库存、业务/调用记录、五类审计筛选、方向键切换、技术详情折叠、返回对话与记录导航均检查。
- 刷新协作记录后，助手提问与方案回复保留在当前对话中；旧任务延迟响应不能覆盖新任务。
- 真实上传公开 WAV 样本，声音基线返回“疑似异常”，分数 7.807125，未确认、未创建任务或工单；仅作为功能冒烟，不当作准确率指标。
- 响应式测试的额外待确认方案已取消，没有额外建单。

隔离数据库最终 2 张工单：一张取消、一张完成；取消工单的 3 条预留已释放，第二张按现有后端规则保留 3 条有效预留。没有修改完成后的资源规则。正式服务器数据库仍为原 2 张工单、6 条有效预留。

真实 session/task/message/子任务/工单/预留对应见 `browser-database-final.json`。浏览器截图与数据库同时保存，未仅凭按钮存在宣称通过。

## 5. 四页截图与尺寸

| 页面 | 1440×900 真实运行截图 |
| --- | --- |
| 主协作 | `final-home-1440.png` |
| 方案确认 | `final-plan-1440.png` |
| 工单中心 | `final-orders-1440.png` |
| 资源与审计 | `final-resources-1440.png` |

以上为隔离本机真实业务数据。`final-*-1366.png`、`final-*-1920.png`、`final-*-390.png` 为各尺寸运行截图。线上新版本截图为 `online-home-1440.png`、`online-orders-1440.png`、`online-resources-1440.png`、`online-plan-empty-1440.png`；线上方案页没有伪填未生成的方案。

16 组测量均验证实际 `innerWidth/innerHeight`，不是仅设置配置。桌面发送与方案确认按钮均在可视区域，技术详情默认折叠；窄屏确认区纵向可滚动，表格只在局部横向滚动。

## 6. 发布与回滚证据

运行 `.venv/Scripts/python.exe deploy/deploy_precision_frontend.py`，最终备份：`/opt/gongwei/backups/20261008-133659-precision-frontend`。

正式网页仍在既有 release `/opt/gongwei/releases/20261006-211426-maintenance`，只发布三个前端文件。Leader 与两个正式 Inbox Partner 的 release、工作目录和身份配置保持。公开 HTTPS 的三文件 SHA-256 与本机一致；见 `deployment.json`。

首次发布健康检查误用历史本机端口 18010，被验证闸门拦截并自动回滚。随后只读核对实际 Nginx upstream 为 18110，将脚本改为从现有配置读取该 upstream，重发验证通过。失败证据保留 `deployment-rolled-back.json`。没有修改端口、Nginx、systemd 或其他站点。

## 7. 全项目最终复核

| 范围 | 实际状态与证据 |
| --- | --- |
| 前端四页与业务 API | 本轮真实网页流程与全部回归通过 |
| 服务器运行 | 8 服务 active/enabled，发布前后 PID 一致，数据库 integrity=ok |
| 三套身份与正式 MQ | 原批准 AIC/独立证书保留；正式三服务和新鲜心跳持续；历史真实 MQ 建单证据未删除 |
| 默认在线发现 | 本轮按三个当前 AIC 精确查询均返回；工单首次 TLS EOF，单次重试 HTTP200 找到 |
| 叮当自动发现与真实建单 | 2026-10-07 已实际通过，session_1726，`WO-20261007-8DC4AC`；采用用户接受的方案编号接续 |
| 最终安全版的新叮当三轮、重投、修改/取消 | 本轮未完成；现有叮当会话失效，登录弹窗已打开；不能把旧截图算本轮新复测 |
| 平台后台匹配/访问统计 | 本轮重查真实调用的 2026-10-07 19:00–20:00，HTTP200，未找到本项目 AIC |
| 完整 AMP Access/Message 链路 | 公开心跳转发可用，完整业务记录安全上报尚未完成验证 |
| 整机重启自动恢复 | 服务均 enabled，但没有重启共享服务器；不能据此宣称整机重启验收完成 |
| 声音辅助 | 保留 22 样例与简单基线，只作冒烟/演示 |
| 技术方案 PDF / 演示视频 | 尚未制作最终交付版本 |

外部 taskId 由首页客户端重建，不能承诺完全不变。用户已接受方案编号与相同调用者/session 校验的业务接续，不再将这一差异当作未实现多轮业务。当前 Partner 选择策略为显式 `platform_catalog`（真实平台目录），本轮另行保存默认在线查询，未把目录查询冒充在线查询。

因此目前可交付前端版本和已有功能演示；若按此前全部平台闸门验收，还需要登录后复测、后台记录链路及整机重启证据，不能直接将 `platform_verified` 改为 true。

## 8. 评审包与秘密边界

最新评审包包含当前源码、设计规范、四页运行截图、本轮测试和只读平台/服务器证据，并附此前真实叮当建单的关键证据。秘密配置、私钥、证书、Token、原始录音、数据库、依赖环境与 Git 均排除。ZIP CRC 与清单哈希验证结果见 `package-result.json`。

当前仍待人工的动作列入 `HUMAN_ACTIONS.md`；其他限制在 `KNOWN_ISSUES.md`。本轮没有购买服务、重置平台数据或修改共享服务器入口。

验收完成后仅停止本轮创建且命令/端口已核对的4个182xx临时进程，记录见 browser-runtime/stopped-processes.json；线上与原本机环境保持。取消方案的下一步提示已修正为“新建检查任务”，第22组检查先失败后通过。

最后线上截图重新测量为1440×900，四页宽度无溢出，见 online-responsive-metrics.json。此前网页临时截图已用准确尺寸的截图替换。

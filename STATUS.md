# 工维联当前状态（2026-10-11）

- 新注册的工维联核心业务 Leader 已通过审核，AIC 为 `1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9`，资源 Partner 和工单 Partner 也均 approved/active；三套证书和身份独立。
- 服务器正式服务、两个 Inbox Partner、AMP metadata sidecar 均由 systemd 管理并 active；正式 AMQPS `amqps://wt.ioa.pub:5671` 连接、入群、任务状态和重启恢复通过；SQLite integrity=ok。
- 默认在线精确发现已恢复：三个 AIC 均返回 active；无指定名称的叮当自动发现也推荐工维联核心业务 Leader。根因是重新注册后心跳和 metadata 配置仍引用旧 Leader AIC，已迁移并部署修复。
- 最新叮当真实会话 `session_1988` 已完成首轮 `awaiting_input`、第二轮资源查询和待确认方案、第三轮用户确认建单；重复确认返回同一工单并命中幂等，独立改期和取消也通过。工单为 `WO-20261011-A432C2`，没有重复资源占用。
- 本轮本机 `380 tests` 全部 OK（1 项因 Windows 符号链接权限跳过）；服务器隔离回归 `380/380`；AMP/发现/元数据 63/63；网页控件 24 组；JavaScript 语法检查通过。
- 本轮真实 `amp.access` 已进入官方 Kafka：18 条 Leader callee 记录包含叮当调用方 AIC、Leader AIC、taskId、方法和 200 响应。梧桐 matched-stats 仍将本窗口计为 Leader16、资源8、工单8 的 Message，三方 HTTPS Access 均为 0；这一步需要梧桐平台核对叮当 caller emitter/统计分类，项目端不能伪造对端记录。
- 因此当前仍为 **platform_verified=false**。技术方案 PDF 和演示视频也尚未制作。

最新报告：[平台最终验收复核](reports/platform-final-acceptance-20261011/README.md)。最新评审包仍为 `reports/gongwei-platform-closeout-review-20261009.zip`；秘密、私钥、证书、数据库和服务器私有备份未进入评审包。

## 以下为之前阶段的历史记录，按各自日期解释

# 工维联当前状态（2026-10-08 晚至10-09零点全流程复核）

- 已完成用户批准的浅色精密工作台四页，部署至 https://gongwei.yanyi.online 。只修改前端呈现，没有更改业务、API、数据库结构或正式身份配置。
- 本轮最终本机296项：295通过、1 Windows符号链接权限跳过；服务器296/296。前端23组、阶段二、阶段五、60/60场景通过。真实网站补充/修改/确认/重投/取消/生命周期/录音上传通过，最新四页×三种桌面尺寸12/12无横向溢出。
- 三个当前 AIC 默认在线发现均再次返回。工单首次查询 TLS EOF，单次重试成功，保留失败与重试证据。
- 叮当已登录并真实完成新三轮：session_1822，WO-20261008-1C8738，正式mTLS Leader→官方MQ两个Partner。精确方案编号重复确认再次实际RPC执行，completed/idempotent=true，数量不变。独立session_1825修改14:00→15:00后，修复取消接续并实际撤销未确认方案。
- 首页仍由平台cancel/start更换taskId，按用户批准的方案编号/同一调用者会话校验接续；不能宣称同一外部taskId。平台将canceled呈现为DAG failed，业务及协议取消结果已取证。
- 已修复并部署日志目录权限、网页录音413、平台固定DAG尾注误拒绝、未确认取消接续与主协作工单状态滞后；独立复核通过。网页公开HTML/JS哈希一致，8服务active/enabled。只重启本项目服务；MQ Partner重启/重入群真实验证通过，未重启共享服务器。
- **不能确认只剩PDF和视频**：平台21:00–24:00公开访问统计仍未返回本项目AIC，完整AMP访问/消息链路、共享整机重启未验；完成工单后的工具归还规则仍需补齐。
- 保持 **platform_verified=false**。技术方案 PDF 与演示视频也待最终制作。

最新报告：[最终全流程复核](reports/final-flow-check-20261008/README.md)。最新评审包：`reports/gongwei-final-flow-review-20261008.zip`。最终数据库4单/3条有效预留，integrity=ok；为演示腾出资源的测试单通过正常取消，未删记录。前端设计与发布证据另见 reports/frontend-precision-acceptance-20261008。

## 以下是 2026-10-07 正式叮当建单与安全补强的已完成证据

- 实际项目：本目录 gongwei-step1，未另建项目。
- **叮当首页实际完成方案编号确认建单**：session_1726，工单 WO-20261007-8DC4AC；资源查询、预留、工单创建均通过两个正式 MQ Partner。确认前没有新增预留或工单；确认后只新增 1 工单、3 预留。
- 用户接受方案编号接续。外部 taskId 仍由平台 cancel/start 更换，旧任务不复活；来源 task、调用者、session、message 与方案关系持久化。
- 三个 AIC 默认在线查询均返回；首页自动发现能找到 Leader。当前业务 Partner 策略仍显式 platform_catalog，分别记录目录与在线查询证据。
- 整体 **platform_verified=false**：正式重复投递受当天配额阻断，公开匹配统计尚未检出本项目；最终安全补强版未再次跑新首页三轮，原真实命令/历史重验通过。
- 最终 Leader 发布：`/opt/gongwei/releases/20261007-120338-maintenance`。网页仍 `/opt/gongwei/releases/20261006-211426-maintenance`，两个 Inbox Partner 仍 `/opt/gongwei/releases/20261007-095036-maintenance`。8 个服务 active/enabled；只重启 Leader，其他 7 个 PID、Nginx 哈希保持。
- 最终服务器：**291/291 单元测试通过**；本机 **291 项，290 通过、1 项 Windows 符号链接权限跳过**；两端阶段二、阶段五通过。此前 60 场景证据属于先前维护审计，本轮未新跑。
- 新增 22 项首页方案接续测试；独立审查已通过，覆盖历史引用、确认/取消权限、终态、并发、重放、恢复及取消补偿。没有数据库迁移、证书或 AIC 变更。
- 最终部署后数据库 integrity=ok；共 2 张测试工单、6 条有效预留（含此前调试工单），本轮方案仍 1 张/3 条，未删除旧数据。

报告：[首页真实验收及证据](reports/dingdang-homepage-recheck-20261007/README.md)。问题：[KNOWN_ISSUES.md](KNOWN_ISSUES.md)。人工/平台处理项：[HUMAN_ACTIONS.md](HUMAN_ACTIONS.md)。

此前的过程清理、基础功能审计与历史回归保留在 reports/final-maintenance-audit/ 和 archive/evidence-before-cleanup-20261007.zip，不与本轮新验收混淆。

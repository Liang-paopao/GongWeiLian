# 最新实际验收（2026-10-11）

## 2026-10-11 最终平台复核

已完成完成/失败/取消后的工具与配件结算、库存手动调整、正式 AMQPS 两 Partner、默认在线发现、自动发现、叮当三轮确认建单、重复确认幂等、独立改期和取消。最新叮当会话 `session_1988` 创建唯一工单 **WO-20261011-A432C2**；两个 Partner 真实执行，数据库 integrity=ok，服务重启恢复正常。

本机全量 `380 tests` 全部 OK（1 项 Windows 符号链接权限跳过）；服务器 `380/380`；AMP/发现/元数据 63/63；网页控件24组；JavaScript语法通过。正式 `amp.access` Kafka 只读扫描得到18条带真实调用方、Leader AIC、taskId和200响应的 callee 记录。

梧桐 `matched-stats` 同时段仍把 Leader16、资源8、工单8计为 Message，三方 HTTPS Access 均为0，未发现叮当 caller-side Access。此项需要梧桐平台核对 emitter、入库或统计分类，项目端不能伪造对端记录；`platform_verified=false` 保持不变。详见 [最新平台复核报告](reports/platform-final-acceptance-20261011/README.md) 和 [人工处理项](HUMAN_ACTIONS.md)。

最新评审包：`reports/gongwei-platform-final-acceptance-review-20261011.zip`。秘密、私钥、证书、数据库和服务器私有备份均未进入评审包。

## 以下为此前验收历史

# 最新实测入口（2026-10-08晚至10-09零点）

用户批准的浅色精密工作台已部署至 https://gongwei.yanyi.online ，保留四页与全部已有业务。最新23组前端检查、本机296项（295通过/1 Windows权限跳过）、服务器296/296、阶段二/五及60场景通过。真实网站与叮当三轮、精确方案重复确认、正式MQ、修改/业务取消已本轮验证；默认在线发现与无指定名称的自动发现返回Leader。

最终交付仍不只有PDF/视频：平台公开访问统计未检出本项目，完整AMP业务记录与共享整机重启闸门未验；这些平台侧闸门不影响本地工单的资源归还规则。`platform_verified=false`。详见 [最终全流程复核](reports/final-flow-check-20261008/README.md)。最新评审包：reports/gongwei-final-flow-review-20261008.zip。

## 2026-10-07 已完成的正式叮当证据

叮当首页已完成“补充信息 → 方案编号确认 → 正式 MQ 两个 Partner → 唯一工单 → completed”，实际工单 **WO-20261007-8DC4AC**，会话 session_1726。用户已接受方案编号接续；外部 taskId 仍由平台重建，旧任务不复活。

三个 AIC 的默认在线查询已返回，首页自动发现也返回 Leader。正式重复投递测试被当天配额拦截，后台匹配统计未检出本项目，整体继续保持 `platform_verified=false`。详见 [首页真实验收报告](reports/dingdang-homepage-recheck-20261007/README.md)、[当前状态](STATUS.md) 和 [未完成事项](KNOWN_ISSUES.md)。

---

# 工维联

工维联是一个设备异常后的检查协调台。它接收文字或结构化检查请求，校验缺失输入，查询人员与库存，生成待确认方案，用户确认后预留资源并创建可追踪工单。声音分析只作为可选辅助，不能替代人工确认，也不推断具体损坏部件。

## 当前正式入口

- 网页与本机 `local_rpc`：`start_stage2.cmd`，默认 Leader `http://127.0.0.1:18010/`。
- MQ 模式：由 `GONGWEI_TRANSPORT_MODE=platform_mq_inbox` 显式启用，业务代码与本机模式共用，使用官方 ACPs Group/Inbox SDK 和 mTLS。
- 测试：`.venv\Scripts\python.exe -m unittest discover -v`；黑盒阶段二、阶段五分别运行 `run_stage2_tests.py`、`run_stage5_tests.py`。
- MQ 官方本机前置检查：`run_mq_inbox_integration.py`。缺少 Docker/acps-infra 时会明确返回 BLOCKED，不会伪造通过。

## 配置边界

复制 `.env.example` 到本机环境后按需设置。密码、Token、EAB、私钥和证书只放在被忽略的 `secrets/` 或本机环境变量中。`platform_verified` 当前必须保持 `false`，直到平台发现和叮当外部调用有真实回执。

当前批准 ACS 快照在 `platform/approved_acs/`，保留三个真实 AIC 和当前端点。`reports/platform_mq_acs/` 是注册前模板及本机测试资产，不能作为当前批准记录重复提交。历史证据已归档至 `archive/evidence-before-cleanup-20261007.zip`。清理明细见 `reports/final-maintenance-audit/cleanup-result.json`。

## 本地智能体化重构

现有页面支持自然语言补充、方案确认、工单、资源和审计；声音是可选辅助。网站已部署至 https://gongwei.yanyi.online ，正式HTTPS Leader为 https://leader.yanyi.online/rpc ，通过官方MQ连接两个Partner。三个智能体已取得批准身份和证书；默认在线发现、叮当按方案编号确认及真实重复投递通过；后台统计等最终闸门未完成，`platform_verified=false`。

本轮测试和评审包入口见 `reports/final-maintenance-audit/README.md`。历史部署脚本含固定旧 release 路径，请勿当作当前一键部署入口。

# 库存归还与手动调整验收（2026-10-10）

## 结论

本轮修复已部署到 `https://gongwei.yanyi.online`。工单完成、失败或取消时，人员、工具和配件预留都会变为 `released`，库存数量归还；同一工单重复关闭不会重复增加库存。历史版本留下的终态 `consumed` 配件预留已在服务启动恢复阶段幂等恢复。

资源页“资源与审计 → 工具与配件”新增每行“− / ＋”控制。后端接口为 `POST /api/resources/inventory/{item_id}/adjust`，同时更新可用量和总量并记录 `inventory_adjusted` 审计事件；不能低于 0，也不能减少活动预留占用的数量。

## 真实服务器结果

- 发布版本：`/opt/gongwei/releases/20261010-042637-inventory-reconcile`
- 发布前备份：`/opt/gongwei/backups/20261010-042650-inventory-reconcile`
- 七个工维联 systemd 服务均为 `active`；网页仍为 `local_rpc`，正式 MQ/平台身份配置未改动。
- 启动恢复后，历史终态 `consumed` 数量为 0。
- `机械密封圈`：`4 / 5`；其中 1 件仍由当前 `confirmed` 工单活动预留，完成或取消该工单后会自动回到 5/5。
- `便携检查工具包`：`1 / 2`；其中 1 套由当前 `confirmed` 工单活动预留。
- 真实网页操作已验证：机械密封圈从 4/5 增加为 5/6，再减少回 4/5，页面显示成功提示，数据库最终数量未被测试改变。

## 自动化验证

- 全量回归：375 项通过，1 项 Windows 符号链接权限检查跳过。
- 阶段二黑盒：通过。
- 阶段五黑盒：通过。
- 阶段四 60 场景：60/60 通过。
- 网页控件：24 组通过，包含订单完成刷新库存和手动库存增减。
- Python `py_compile`、Node `--check web/app.js`、`git diff --check`：通过。
- 官方 MQ Inbox 集成本机前置仍按既有结果为 BLOCKED（本机未安装 Docker/acps-infra）；本轮未把它改写成通过。

## 边界

本轮没有修改 AIC、证书、MQ 参数、数据库结构、工单确认门或平台注册记录；`platform_verified` 继续为 `false`。当前确认中的工单仍会占用对应资源，只有完成、失败或取消后才归还。

## 本轮清理

已删除本轮生成的过程性文件：

- `reports/local-test-runs/` 下的原始测试运行目录和临时日志；
- 项目源码目录下的 `__pycache__/`（仅项目根目录和 `scripts/`）；
- 本地 `logs/` 下的运行日志；
- `archive/cleanup-hold-20261010/` 下的临时留存缓存和中间包；
- `C:\Windows\Temp` 下的本轮发布临时包和 `gongwei-live-orders.json`。

源码、数据库、`secrets/`、虚拟环境、部署配置、服务器回滚备份、当前发布版本和最终报告均保留。

## 后续发布回归修复（同日）

上一版发布包遗漏了运行时依赖的 `reports/platform_mq_acs/resource_partner.json` 和 `work_order_partner.json`。本地 `local_rpc` 在整理资源方案时读取不到 ACS，异常被统一包装成“在线发现暂时不可用”。

已在当前服务器 release 补齐两个公开 ACS，并更新 `deployment-manifest.json`；`deploy/activate_maintenance_release.py` 增加了 release 切换前的必备文件检查。用原失败会话重试补充信息后，返回 `ready_for_plan` 和 `proposed` 方案，发现结果为 `static_fallback` 且已选中 Partner；该方案 `work_order_id=null`，预留数为 0，未创建工单。

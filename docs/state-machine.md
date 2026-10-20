# 状态机与映射

## 业务状态

`created` → `awaiting_input`（缺参）→ `planned` → `awaiting_confirmation` → `confirming` → `reserved` → `work_order_created` → `in_progress` → `completed`。

冲突和异常走 `failed`；补偿过程使用 `compensating`；服务重启发现未完成确认使用 `recovery_required`，恢复后进入 `cancelled` 或 `confirmed`。

## AIP 状态

官方任务状态使用 `accepted`、`working`、`awaiting_input`、`awaiting_completion`、`completed`、`failed`、`cancelled`、`rejected`。

映射实现集中在 `state_mapping.py`。`planned` 与 `awaiting_confirmation` 都映射为 `awaiting_completion`，反向映射使用规范状态 `awaiting_confirmation`，页面和审计以业务状态为准，AIP 状态同时保留。

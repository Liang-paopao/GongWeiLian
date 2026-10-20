# SQLite 数据库与迁移

当前业务数据库版本为 **4**，以 `stage2_db.py` 的 `SCHEMA_VERSION` 和 `PRAGMA user_version` 为准。`initialize_database()` 在事务中执行建表和增量迁移，保留旧数据；发现高于代码支持版本的数据库时拒绝启动。不得用重置数据库代替迁移。

核心表：`pumps`、`workers`、`worker_skills`、`worker_availability`、`inventory_items`、`inspection_requests`、`plans`、`reservations`、`work_orders`、`task_events`、`idempotency_keys`、`audio_analyses`。

对话与协作表：`agent_sessions`、`agent_tasks`、`agent_messages`、`task_subtasks`、`user_confirmations`、`partner_discovery_snapshots`、`partner_selections`。平台 RPC/Inbox 的运行状态存储以相应 runtime 配置为准，不应混同业务数据库版本。

约束和索引：工单编号、幂等键和各主键唯一；资源窗口索引支持冲突查询；任务事件只追加；关键预留、建单、释放和恢复操作在 `BEGIN IMMEDIATE` 事务中完成。

库存生命周期：`reservations.status='active'` 表示当前占用，工单完成、失败或取消后变为 `released`，并将工具与配件数量归还到 `inventory_items.available_qty`。库存数量的手动调整通过业务接口完成，同时调整 `total_qty` 与 `available_qty` 并记录 `inventory_adjusted` 审计事件；不会修改活动预留。

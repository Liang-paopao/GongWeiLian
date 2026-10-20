# 核心 Agent 合约

## Leader

- AIC（本机占位）：`stage2-gongwei-leader`
- 能力：创建检查请求、生成/重排方案、查看时间线和工单。
- 输入：`{"action":"propose_inspection","request_id":"req-*"}`。
- 输出：`{"simulated":true,"ok":true,"result":{"plan":{...}}}`。
- 缺参：返回 `awaiting_input` 或结构化业务错误；不猜测设备信息。

## 资源 Partner

- AIC（本机占位）：`stage2-gongwei-resource`
- 能力：查询人员技能/时间、工具和配件库存，预留与释放资源。
- 输入 action：`query_resources`、`reserve_resources`、`release_resources`。
- 输出：包含 `ok`、资源列表、预留编号和原因；冲突不会部分成功。

## 工单 Partner

- AIC（本机占位）：`stage2-gongwei-work-order`
- 能力：创建、更新、取消工单；创建必须带 `idempotency_key`。
- 输入 action：`create_work_order`、`update_work_order`、`cancel_work_order`。
- 输出：包含工单编号、状态和幂等标记；重复请求返回同一工单。

## 可选声音 Partner

- AIC（本机占位）：`stage2-gongwei-audio`
- 只输出“未发现明显异常”或“疑似异常”，不推断具体零件损坏。
- 分析结果必须经过用户确认，才会进入 Leader 的检查请求流程。

所有 Partner 使用同一 JSON 文本消息和官方 AIP task 状态，拒绝未知 action、非法 sender 或不安全的音频结果。

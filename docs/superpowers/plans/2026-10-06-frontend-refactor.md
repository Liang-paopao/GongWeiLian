# 工维联前端四视图重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有工维联前端中实现主协作、方案确认、工单中心、资源与审计四个真实数据视图。

**Architecture:** 使用现有 FastAPI API 和 SQLite 数据作为唯一数据源，`web/app.js` 负责 hash 视图、状态和事件，`web/index.html` 提供四个视图壳层，`web/styles.css` 提供共享视觉系统与响应式布局。业务执行仍走既有会话、确认、工单和审计接口。

**Tech Stack:** 原生 HTML、CSS、JavaScript、Fetch API、现有 FastAPI 服务。

---

### Task 1: 四视图壳层与数据边界

**Files:**
- Modify: `web/index.html`
- Modify: `web/styles.css`

- [x] 创建顶部状态栏、主导航、技术详情折叠区和四个视图容器。
- [x] 在主协作页保留对话、任务计划、当前任务、协作轨迹和声音辅助入口。
- [x] 在方案、工单、资源审计视图中使用明确的空状态，不写入示例日期、姓名或编号。
- [x] 使用响应式断点适配宽屏、平板和窄屏。

### Task 2: 前端状态和真实 API 适配

**Files:**
- Modify: `web/app.js`

- [x] 复用现有 `/api/conversations`、`/api/conversations/{session}/messages`、`/api/tasks/{task}/confirm`、`/api/tasks/{task}/revise`、`/api/tasks/{task}/cancel` 接口。
- [x] 通过 `/api/bootstrap`、`/api/work-orders`、`/api/tasks/{task}/trace` 和 `/api/aip-calls` 加载业务事实。
- [x] 统一状态徽标、任务步进器、技术详情和协作节点更新。
- [x] 对确认、取消、工单状态更新增加忙碌和错误反馈，保持既有幂等请求头。

### Task 3: 浏览器和回归验证

**Files:**
- Create: `reports/frontend-refactor-acceptance-20261006.md`
- Create: `reports/screenshots/frontend-*.png`（若浏览器环境支持保存）

- [ ] 重启现有本机页面服务并确认 `/health`、`/api/bootstrap` 正常返回。
- [ ] 在浏览器访问四个 hash 视图，验证导航、筛选、详情、刷新和技术详情折叠。
- [ ] 完成缺参、多轮补充、方案确认、重复确认保护和工单状态操作。
- [ ] 在 1366×768、1440×900、1920×1080 检查布局，并记录截图和未完成事项。
- [ ] 运行现有 Python 回归测试与页面脚本语法检查。

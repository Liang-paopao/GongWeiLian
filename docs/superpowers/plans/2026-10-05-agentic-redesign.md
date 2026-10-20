# Agentic Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在当前工维联项目中完成本地智能体化重构，并在本地验收后停止部署动作。

**Architecture:** 共享现有领域业务和两种传输模式；增加会话核心、官方 ADP 发现边界、Leader Inbox Runtime、增量 SQLite 表和三栏对话界面。规则解析是明确标注的本地回退，业务状态由确定性代码控制。

**Tech Stack:** Python 3.14、FastAPI、SQLite、官方 ACPs SDK 2.2.0、原生 HTML/CSS/JS、unittest。

---

### Task 1: 基线和保护点

Files: Git metadata, `reports/agentic-baseline-unittest-20261005.log`, `docs/superpowers/specs/2026-10-05-agentic-redesign-design.md`.

- [x] 检查当前工作树和秘密排除规则。
- [x] 运行全部基线测试并记录真实输出。
- [x] 提交审计基线，建立 `pre-agentic-redesign-20261005` 和 `feature/agentic-redesign`。

### Task 2: 会话核心和数据库迁移

Files: `stage2_db.py`, `agentic_core.py`, `stage2_domain.py`, `test_agentic_core.py`.

- [x] 先写自然语言字段提取、缺参、多轮和长度校验测试。
- [x] 实现确定性回退解析和共享 session/task/message 表。
- [x] 运行核心测试和全量回归。

### Task 3: 发现和外部 Inbox

Files: `partner_resolver.py`, `leader_inbox_runtime.py`, `mq_group_transport.py`, `stage2_aip.py`.

- [x] 先写发现过滤、发现失败、固定 session 防回归测试。
- [x] 接入官方 ADP 数据模型、显式 static fallback 和官方 GroupPartner Inbox。
- [x] 运行 MQ/Inbox 合同测试；缺 Docker/acps-infra 时保留 BLOCKED 证据。

### Task 4: API 与界面

Files: `web_app.py`, `web/index.html`, `web/app.js`, `web/styles.css`, `test_stage2_api.py`.

- [x] 写会话、多轮、确认、取消、平台状态合同测试。
- [x] 保留旧 API，新增会话 API 和确认门。
- [x] 实现三栏对话、计划、协作轨迹和声音抽屉。
- [x] 用浏览器运行首轮缺参、补充、方案、确认建单场景并截取截图。

### Task 5: ACS、报告与验收包

Files: `scripts/build_agentic_acs_draft.py`, `reports/acs_1_1_0_draft/`, `reports/agentic-*`, `STATUS.md`.

- [x] 生成未提交的 ACS 1.1.0 草稿。
- [x] 运行 88 项回归、阶段二/阶段五黑盒和浏览器场景。
- [ ] 在线梧桐发现、叮当真实调用、后台访问证据和官方 Docker MQ 前置仍需外部条件。
- [ ] 生成脱敏本地评审压缩包后停止，不进入腾讯云或域名部署。

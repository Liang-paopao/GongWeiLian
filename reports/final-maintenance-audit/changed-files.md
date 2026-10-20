# 本轮修改文件

只列本轮新增/修改；没有把此前未提交的前端重构、Nginx部署等改动算作本轮新增。

## 业务与传输

- `agentic_core.py`
- `leader_external_flow.py`
- `leader_inbox_runtime.py`
- `mq_group_transport.py`
- `mq_partner_runtime.py`（新增）
- `platform_runtime_config.py`
- `stage2_domain.py`
- `web_app.py`
- `audio_detector.py`
- `web/app.js`

## 启动、工具与配置

- `.env.example`、`.gitignore`
- `start_stage2.cmd`、`stop_stage2.cmd`
- `run_stage2_tests.py`、`run_stage5_tests.py`
- `scripts/local_services.py`（新增）
- `scripts/setup_windows.ps1`
- `scripts/prepare_mimii.py`
- `scripts/run_60_scenarios.py`
- `scripts/build_platform_acs.py`
- `scripts/build_hybrid_leader_acs.py`
- `scripts/build_agentic_acs_draft.py`
- `scripts/make_maintenance_review_package.py`（新增）
- `scripts/test_web_controls.cjs`（新增）
- `deploy/stage_hybrid_release.py`（批准ACS输入路径修正；没有执行部署）

## 测试

- `test_acs_builders.py`（新增）
- `test_agentic_core.py`
- `test_audio_detector.py`
- `test_audio_partner.py`
- `test_audio_pluggable.py`
- `test_leader_inbox_runtime.py`
- `test_local_services.py`（新增）
- `test_local_test_entrypoints.py`（新增）
- `test_mq_group_transport.py`
- `test_mq_partner_runtime.py`（新增）
- `test_platform_runtime_config.py`
- `test_prepare_mimii.py`（新增）
- `test_stage2_api.py`
- `test_stage2_domain.py`

## 文档与公开ACS

- `README.md`、`STATUS.md`、`KNOWN_ISSUES.md`、`HUMAN_ACTIONS.md`、`CHECK_STATUS.json`、`SOURCES.txt`
- `docs/database-schema.md`、`docs/user-guide.md`、`docs/final-technical-report.md`、`docs/final-presentation-outline.md`
- `platform/README.md`、`deploy/README.md`
- `platform/approved_acs/{leader,resource_partner,work_order_partner}.json` 与说明（新增公开批准快照）
- `reports/acs_1_1_0_draft/` 三个草稿及说明
- `reports/final-maintenance-audit/` 汇总、真实日志、截图、检查清单

过程文件的回收清单在 `cleanup-result.json`。数据库、原始录音、模型、私钥、证书、secrets和原始交付材料未删除。

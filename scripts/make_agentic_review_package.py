"""Create a small credential-free local agentic redesign review package."""
from __future__ import annotations
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "gongwei-agentic-redesign-review-20261006.zip"
FILES = [
    "README.md", "STATUS.md", "ARCHITECTURE.md", "SECURITY.md", "HUMAN_ACTIONS.md", "KNOWN_ISSUES.md", "CHECK_STATUS.json", ".env.example", "pyproject.toml", "uv.lock",
    "web/index.html", "web/app.js", "web/styles.css", "web_app.py", "agent_core.py", "agentic_core.py", "llm_provider.py", "partner_resolver.py", "leader_inbox_runtime.py", "leader_external_flow.py", "run_leader_inbox.py", "run_partner_inbox.py", "platform_runtime_config.py", "stage2_db.py", "stage2_domain.py", "stage2_aip.py", "stage3_leader_aip.py", "mq_group_transport.py", "transport_mode.py", "platform_runtime.py", "local_log.py",
    "resource_partner_v1.py", "work_order_partner_v1.py", "audio_partner_v1.py", "audio_service.py", "audio_detector.py", "audio_data.py", "start_stage2.cmd", "stop_stage2.cmd", "run_stage2_tests.py", "run_stage5_tests.py", "run_mq_inbox_integration.py",
    "scripts/build_agentic_acs_draft.py", "scripts/make_agentic_review_package.py",
    "docs/superpowers/specs/2026-10-05-agentic-redesign-design.md", "docs/superpowers/plans/2026-10-05-agentic-redesign.md",
    "reports/acs_1_1_0_draft/README.md", "reports/acs_1_1_0_draft/leader.json", "reports/acs_1_1_0_draft/resource_partner.json", "reports/acs_1_1_0_draft/work_order_partner.json",
    "reports/mq-cert-bootstrap-20261005.md", "reports/mq-live-integration-20261005.md", "reports/mq-local-integration-report.md",
    "reports/agentic-local-acceptance-20261005.md", "reports/agentic-conversation-demo-20261005.md",
    "reports/dingdang-live-acceptance-20261006.md",
    "reports/dingdang-live/platform-leader-approved-acs.json",
    "reports/dingdang-live/leader-acs-1.1.0-archive.json",
    "reports/dingdang-live/discovery-resolver-official-20261006.json",
    "reports/dingdang-live/discovery-cli-leader-aic-20261006.json",
    "reports/dingdang-live/discovery-cli-resource-20261006.json",
    "reports/dingdang-live/discovery-cli-workorder-20261006.json",
    "reports/dingdang-live/leader-mq-runtime-20261006.log",
    "reports/dingdang-live/resource-partner-mq-runtime-20261006.log",
    "reports/dingdang-live/workorder-partner-mq-runtime-20261006.log",
    "reports/dingdang-live/mq-process-status-20261006.json",
    "reports/dingdang-live/dingdang-rounds-20261006.txt",
    "reports/dingdang-direct-call-acceptance-20261006.md",
    "reports/dingdang-live/leader-inbox-direct-call-20261006.log",
    "reports/dingdang-live/resource-partner-inbox-direct-call-20261006.log",
    "reports/dingdang-live/workorder-partner-inbox-direct-call-20261006.log",
    "reports/dingdang-live/database-direct-call-state-20261006.json",
    "test_agentic_core.py", "test_partner_resolver.py", "test_leader_inbox_runtime.py", "test_leader_external_flow.py", "test_partner_inbox_entrypoint.py", "test_stage2_api.py", "test_mq_group_transport.py",
    "reports/agentic-baseline-unittest-20261005.log", "reports/agentic-stage2-tests-20261005.log", "reports/agentic-stage2-6-tests-20261005.log", "reports/agentic-stage2-9-tests-20261005.log", "reports/agentic-full-unittest-20261005.log", "reports/agentic-stage2-blackbox-20261005.log", "reports/agentic-stage5-blackbox-20261005.log", "reports/agentic-full-unittest-20261006.log", "reports/agentic-stage2-blackbox-20261006.log", "reports/agentic-stage5-blackbox-20261006.log",
]
FILES += sorted(p.name for p in ROOT.glob("test_*.py"))
with ZipFile(OUTPUT, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    archive.writestr("README_REVIEW_PACKAGE.txt", "工维联本地智能体化重构评审包（2026-10-06）。不含 secrets、私钥、Token、数据库、原始录音、浏览器会话或历史压缩包。platform_verified=false。腾讯云和域名部署未执行。\n")
    for relative in sorted(set(FILES)):
        path = ROOT / relative
        if path.is_file() and not any(part in {"secrets", ".venv", ".git", ".python-runtime", "__pycache__"} for part in path.parts):
            archive.write(path, relative)
print(OUTPUT)
print(f"{OUTPUT.stat().st_size} bytes")

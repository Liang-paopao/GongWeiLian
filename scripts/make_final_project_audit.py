"""Build the credential-free final project audit package."""
from __future__ import annotations
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "gongwei-final-project-audit-20261005.zip"
FILES = [
    "README.md", "STATUS.md", "ARCHITECTURE.md", "CHANGELOG.md", "KNOWN_ISSUES.md", "HUMAN_ACTIONS.md", "SECURITY.md", "CHECK_STATUS.json", ".env.example", "pyproject.toml", "uv.lock",
    "start_stage2.cmd", "stop_stage2.cmd", "01_prepare.cmd", "02_start_resource.cmd", "03_run_leader.cmd",
    "web/index.html", "web/app.js", "web/styles.css",
    "web_app.py", "stage2_domain.py", "stage2_db.py", "stage2_aip.py", "stage2_business_actions.py", "stage2_partner_common.py", "stage3_leader_aip.py", "state_mapping.py", "transport_mode.py", "platform_runtime.py", "mq_group_transport.py", "local_log.py", "resource_partner_v1.py", "work_order_partner_v1.py", "audio_data.py", "audio_detector.py", "audio_partner_v1.py", "audio_service.py", "business.py", "leader.py", "resource_agent.py",
    "run_stage2_tests.py", "run_stage5_tests.py", "run_mq_inbox_integration.py",
    "scripts/build_mq_acs.py", "scripts/make_final_project_audit.py", "scripts/run_all_tests.cmd", "scripts/setup_windows.ps1", "scripts/start_local_windows.cmd", "scripts/stop_local_windows.cmd", "scripts/run_60_scenarios.py", "scripts/prepare_mimii.py",
]
FILES += sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "tests").rglob("*") if p.is_file()) if (ROOT / "tests").exists() else []
FILES += sorted(p.name for p in ROOT.glob("test_*.py"))
FILES += sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "reports" / "platform_mq_acs").glob("*.json"))
FILES += sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "reports" / "final-project-audit").glob("*"))
FILES += [
    "reports/mq-cert-bootstrap-20261005.md", "reports/mq-live-integration-20261005.md", "reports/mq-local-integration-report.md",
    "logs/mq_platform_live_20261005.log", "logs/browser_audit_ui_20261005.md", "logs/audit_pre_cleanup_unittest_20261005.log", "logs/audit_pre_cleanup_git_status_20261005.txt", "logs/audit_post_cleanup_unittest_20261005.log", "logs/audit_post_cleanup_stage2_20261005.log", "logs/audit_post_cleanup_stage5_20261005.log", "logs/audit_post_cleanup_mq_preflight_20261005.log", "logs/audit_post_cleanup_inventory_20261005.json", "logs/audit_post_cleanup_compile_20261005.log", "logs/final_audit_tests_20261005.log",
    "docs/agent-contracts.md", "docs/database-schema.md", "docs/mq-inbox-implementation.md", "docs/mq-platform-parameters-needed.md", "docs/observability.md", "docs/platform-dual-transport-plan.md", "docs/platform-parameters-checklist.md", "docs/state-machine.md", "docs/user-guide.md", "platform/README.md",
]
SENSITIVE_PARTS = {"secrets", ".venv", ".python-runtime", ".git", "__pycache__", ".pytest_cache"}

def scrub_json(raw: bytes) -> bytes:
    try: value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError): return raw
    hidden = {"password", "token", "authorization", "private_key", "client_secret", "mackey", "eab"}
    def scrub(item):
        if isinstance(item, dict): return {k: "[omitted]" if k.lower() in hidden else scrub(v) for k, v in item.items()}
        if isinstance(item, list): return [scrub(v) for v in item]
        return item
    return (json.dumps(scrub(value), ensure_ascii=False, indent=2) + "\n").encode("utf-8")

with ZipFile(OUTPUT, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    archive.writestr("README_REVIEW_PACKAGE.txt", "工维联最终项目审计包（2026-10-05）。不含 secrets、私钥、Token、数据库、浏览器数据、缓存、原始录音或历史压缩包。platform_verified=false。\n")
    for relative in sorted(set(FILES)):
        path = ROOT / relative
        if not path.is_file() or any(part in SENSITIVE_PARTS for part in path.parts): continue
        data = scrub_json(path.read_bytes()) if path.suffix == ".json" else path.read_bytes()
        archive.writestr(relative, data)
print(OUTPUT)
print(OUTPUT.stat().st_size)

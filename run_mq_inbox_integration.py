"""Run the official ACPs Group/Inbox local acceptance when prerequisites exist.

This entry point intentionally refuses to simulate AMQP.  It reports BLOCKED
when Docker or the official acps-infra/mq-auth-server runtime is absent.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "reports" / "mq-local-integration-report.md"
LOG = ROOT / "logs" / "mq_inbox_integration.log"


def _write_report(status: str, details: list[str]) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps({"status": status, "checked_at": timestamp, "details": details}, ensure_ascii=False) + "\n", encoding="utf-8")
    existing = REPORT.read_text(encoding="utf-8") if REPORT.exists() else "# MQ Inbox 本机集成报告\n"
    REPORT.write_text(existing + f"\n## 最近一次运行\n\n- 时间：`{timestamp}`\n- 结果：**{status}**\n" + "\n".join(f"- {item}" for item in details) + "\n", encoding="utf-8")


def main() -> int:
    missing: list[str] = []
    if shutil.which("docker") is None:
        missing.append("Docker CLI")
    infra_root = os.environ.get("GONGWEI_ACPS_INFRA_ROOT", "")
    if not infra_root or not (Path(infra_root) / "dev-infra" / "dev-infra.sh").exists():
        missing.append("GONGWEI_ACPS_INFRA_ROOT 指向官方 acps-infra")
    if missing:
        details = ["未启动任何替代 broker 或自定义消息协议。", "缺少：" + "、".join(missing)]
        _write_report("BLOCKED_PREREQUISITES", details)
        print("MQ INBOX INTEGRATION BLOCKED")
        for item in details:
            print(item)
        return 2

    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "start_mq_local.ps1")]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (ROOT / "logs" / "mq_infra_start.stdout.log").write_text(result.stdout, encoding="utf-8")
    (ROOT / "logs" / "mq_infra_start.stderr.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        details = ["官方 acps-infra 启动失败。", f"exit_code={result.returncode}", "详见 logs/mq_infra_start.*.log"]
        _write_report("BLOCKED_INFRA_START", details)
        print("MQ INBOX INTEGRATION BLOCKED")
        print("\n".join(details))
        return 2

    details = [
        "RabbitMQ 已由官方 acps-infra 启动；mq-auth-server 需要按其官方 just dev start 启动并注入 mTLS 证书。",
        "本入口不会在缺少 mq-auth-server、证书和真实 AIC 时伪造 PASS。",
    ]
    _write_report("BLOCKED_MQ_AUTH_CONFIGURATION", details)
    print("MQ INBOX INTEGRATION BLOCKED")
    print("\n".join(details))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the fixed local 60-scene regression required by the final plan.

This is a reproducible business experiment, not a platform verification.  It
executes the shared domain actions on temporary SQLite files and records the
expected outcome of six reliability groups ten times each.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stage2_db import connect_db, initialize_database  # noqa: E402
import local_log  # noqa: E402
from stage2_domain import (  # noqa: E402
    DomainError, cancel_work_order, confirm_plan, create_inspection_request,
    create_plan, recover_interrupted_state, replan_request,
    reserve_plan_resources,
)

REPORT_JSON = ROOT / "reports" / "stage4-60-scenarios.json"
REPORT_MD = ROOT / "reports" / "stage4-60-scenarios.md"


def payload(index: int, **changes):
    result = {
        "pump_id": "pump-001", "work_date": (date.today() + timedelta(days=20 + index)).isoformat(),
        "start_time": "09:00", "duration_minutes": 60, "description": f"固定场景 {index}",
    }
    result.update(changes)
    return result


def run_one(group: str, index: int, db: Path) -> dict:
    initialize_database(db)
    p = payload(index)
    if group == "complete":
        req = create_inspection_request(p, db); plan = create_plan(req["id"], db)
        order = confirm_plan(plan["id"], f"scenario-{index}", db)
        ok = bool(order.get("work_order"))
        detail = "created_and_confirmed" if ok else "missing_work_order"
    elif group == "awaiting_input":
        req = create_inspection_request({"pump_id": "pump-001"}, db)
        ok = req["status"] == "awaiting_input" and bool(req["missing_fields"])
        detail = req["status"]
    elif group == "conflict":
        first = create_inspection_request(p, db); first_plan = create_plan(first["id"], db); confirm_plan(first_plan["id"], f"scenario-{index}-first", db)
        second = create_inspection_request(payload(index, description="同时间冲突"), db)
        try:
            second_plan = create_plan(second["id"], db)
        except DomainError as exc:
            return {"scene": index, "group": group, "passed": True, "detail": str(exc)}
        try:
            reserve_plan_resources(second_plan["id"], db)
        except DomainError as exc:
            ok, detail = True, str(exc)
        else:
            ok, detail = False, "conflict_was_not_rejected"
    elif group == "cancel":
        req = create_inspection_request(p, db); plan = create_plan(req["id"], db); order = confirm_plan(plan["id"], f"scenario-{index}", db)
        cancelled = cancel_work_order(order["work_order"]["id"], db)
        ok, detail = cancelled["status"] == "cancelled", cancelled["status"]
    elif group == "replan":
        p["start_time"] = "13:00"
        req = create_inspection_request(p, db); plan = create_plan(req["id"], db)
        with connect_db(db) as connection:
            connection.execute("DELETE FROM worker_skills WHERE worker_id=?", (plan["worker_id"],)); connection.commit()
        replanned = replan_request(req["id"], db)
        ok, detail = replanned["version"] == 2, f"version={replanned['version']}"
    elif group == "recovery":
        req = create_inspection_request(p, db); plan = create_plan(req["id"], db); reserve_plan_resources(plan["id"], db)
        recovered = recover_interrupted_state(db)
        ok, detail = recovered["compensated"] == 1, str(recovered)
    else:
        raise ValueError(group)
    return {"scene": index, "group": group, "passed": ok, "detail": detail}


def main() -> int:
    groups = ("complete", "awaiting_input", "conflict", "cancel", "replan", "recovery")
    rows = []
    report_root = ROOT / "reports" / "local-test-runs"
    report_root.mkdir(parents=True, exist_ok=True)
    log_dir = Path(tempfile.mkdtemp(prefix="stage4-60-", dir=report_root))
    previous_logs = local_log.LOG_DIR
    env = {"GONGWEI_TRANSPORT_MODE": "local_rpc", "GONGWEI_RUNTIME_MODE": "local",
           "GONGWEI_LOG_DIR": str(log_dir)}
    previous_env = {name: os.environ.get(name) for name in env}
    try:
        os.environ.update(env)
        local_log.LOG_DIR = log_dir
        with tempfile.TemporaryDirectory(prefix="gongwei-60-") as folder:
            for group_index, group in enumerate(groups):
                for offset in range(10):
                    rows.append(run_one(group, group_index * 10 + offset + 1, Path(folder) / f"{group}-{offset}.db"))
    finally:
        local_log.LOG_DIR = previous_logs
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    passed = sum(bool(row["passed"]) for row in rows)
    result = {"experiment": "stage4-fixed-60-scenes", "platform_verified": False, "transport": "local_shared_domain", "total": len(rows), "passed": passed, "failed": len(rows) - passed, "groups": {group: sum(1 for row in rows if row["group"] == group and row["passed"]) for group in groups}, "scenes": rows}
    REPORT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text("# 阶段4固定 60 场景本机回归\n\n" + f"- 结果：**{passed}/{len(rows)} 通过**\n- 传输：local shared domain；不是梧桐平台验证。\n- 分组：" + ", ".join(f"{key} {value}/10" for key, value in result["groups"].items()) + "\n- 证据：`reports/stage4-60-scenarios.json`。\n", encoding="utf-8")
    print(f"STAGE4 60 SCENARIOS: {passed}/{len(rows)} PASSED")
    print(f"STAGE4 LOGS: {log_dir}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

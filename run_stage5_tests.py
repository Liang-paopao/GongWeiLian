"""Black-box stage five checks using the real local Leader and three Partners."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from stage2_db import connect_db
from stage2_domain import confirm_plan, reserve_plan_resources
import local_log
from run_stage2_tests import allocate_loopback_ports

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "reports" / "local-test-runs"
PORTS = {"resource": 18212, "workorder": 18213, "leader": 18210, "audio": 18214}


def http_json(url: str, method: str = "GET", payload: dict | None = None, headers: dict | None = None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=8) as response:
            content = response.read().decode("utf-8")
            return response.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {detail}") from exc


def wait_health(url: str) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            status, payload = http_json(url)
            if status == 200 and payload.get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(.25)
    raise RuntimeError(f"服务未健康：{url}")


def start_service(module: str, port: int, env: dict[str, str], name: str) -> subprocess.Popen:
    LOG_DIR.mkdir(exist_ok=True)
    stdout = (LOG_DIR / f"stage5_{name}.log").open("w", encoding="utf-8")
    stderr = (LOG_DIR / f"stage5_{name}.err.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", f"{module}:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
    )
    process._stage5_files = (stdout, stderr)  # type: ignore[attr-defined]
    return process


def stop_service(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=6)
    for stream in getattr(process, "_stage5_files", ()):  # type: ignore[attr-defined]
        stream.close()


def main() -> int:
    global LOG_DIR, PORTS
    report_root = ROOT / "reports" / "local-test-runs"
    report_root.mkdir(parents=True, exist_ok=True)
    LOG_DIR = Path(tempfile.mkdtemp(prefix="stage5-", dir=report_root))
    PORTS = allocate_loopback_ports(("resource", "workorder", "leader", "audio"))
    processes: list[subprocess.Popen] = []
    temporary = tempfile.TemporaryDirectory(prefix="gongwei-stage5-")
    db_path = Path(temporary.name) / "stage5.db"
    previous_logs = local_log.LOG_DIR
    local_log.LOG_DIR = LOG_DIR
    env = os.environ.copy()
    env.update({
        "GONGWEI_TRANSPORT_MODE": "local_rpc",
        "GONGWEI_RUNTIME_MODE": "local",
        "GONGWEI_DISCOVERY_URL": "",
        "DISCOVERY_URL": "",
        "GONGWEI_LOG_DIR": str(LOG_DIR),
        "GONGWEI_STAGE2_DB": str(db_path),
        "GONGWEI_STAGE2_RESOURCE_PORT": str(PORTS["resource"]),
        "GONGWEI_STAGE2_WORKORDER_PORT": str(PORTS["workorder"]),
        "GONGWEI_STAGE2_LEADER_PORT": str(PORTS["leader"]),
        "GONGWEI_STAGE2_AUDIO_PORT": str(PORTS["audio"]),
        "NO_PROXY": "127.0.0.1,localhost,::1",
    })
    try:
        (LOG_DIR / "run.json").write_text(json.dumps({"transport": "local_rpc", "ports": PORTS,
            "temporary_database": str(db_path)}, indent=2) + "\n", encoding="utf-8")
        print(f"STAGE5 LOGS: {LOG_DIR}")
        for module, key in (("resource_partner_v1", "resource"), ("work_order_partner_v1", "workorder"), ("audio_partner_v1", "audio"), ("web_app", "leader")):
            processes.append(start_service(module, PORTS[key], env, key))
        for key in PORTS:
            wait_health(f"http://127.0.0.1:{PORTS[key]}/health")
        _, audio_health = http_json(f"http://127.0.0.1:{PORTS['audio']}/health")
        assert audio_health["model_role"] == "auxiliary_smoke_baseline"
        work_date = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400))
        payload = {"pump_id": "pump-001", "work_date": work_date, "start_time": "13:00", "duration_minutes": 60, "description": "阶段五黑盒测试"}
        _, request = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests", "POST", payload)
        _, plan = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests/{request['id']}/propose", "POST")
        with connect_db(db_path) as connection:
            connection.execute("DELETE FROM worker_skills WHERE worker_id=?", (plan["worker_id"],))
            connection.commit()
        _, replanned = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests/{request['id']}/replan", "POST")
        assert replanned["version"] == 2 and replanned["worker_id"] != plan["worker_id"]
        _, confirmed = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/plans/{replanned['id']}/confirm", "POST", headers={"Idempotency-Key": "stage5-confirm-001"})
        _, duplicate = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/plans/{replanned['id']}/confirm", "POST", headers={"Idempotency-Key": "stage5-confirm-001"})
        assert confirmed["ok"] and duplicate["idempotent"]
        _, audit = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/audit?request_id={request['id']}")
        event_types = {event["event_type"] for event in audit["events"]}
        assert {"plan_replanned", "resource_reserved", "work_order_created"}.issubset(event_types)

        # Reserve a second plan and restart only the Leader.  Its lifespan
        # recovery must compensate the orphaned reservation exactly once.
        with connect_db(db_path) as connection:
            connection.execute("INSERT OR IGNORE INTO worker_skills(worker_id,skill) VALUES('worker-01','pump_inspection')")
            connection.commit()
        payload["description"] = "阶段五恢复测试"
        _, request2 = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests", "POST", payload)
        _, plan2 = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests/{request2['id']}/propose", "POST")
        reserve_plan_resources(plan2["id"], db_path)
        stop_service(processes[-1])
        processes[-1] = start_service("web_app", PORTS["leader"], env, "leader_recovery")
        wait_health(f"http://127.0.0.1:{PORTS['leader']}/health")
        with connect_db(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM reservations WHERE status='active' AND plan_id=?", (plan2["id"],)).fetchone()[0] == 0
        # Direct domain injection verifies the same compensation used by the
        # Work-order Partner failure path.
        payload["description"] = "阶段五失败补偿测试"
        _, request3 = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests", "POST", payload)
        _, plan3 = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests/{request3['id']}/propose", "POST")
        try:
            confirm_plan(plan3["id"], "stage5-failure-001", db_path, force_failure=True)
        except Exception as exc:
            assert "创建失败" in str(exc)
        with connect_db(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM reservations WHERE status='active' AND plan_id=?", (plan3["id"],)).fetchone()[0] == 0
        print("STAGE5 INTEGRATION PASSED")
        print("AUDIO: auxiliary pluggable baseline health verified")
        print("REPLAN: resource change -> version 2 -> confirm -> duplicate confirm")
        print("RECOVERY: restart compensated orphaned reservations")
        print("COMPENSATION: injected work-order failure released reservations")
        print("AUDIT: replan, reserve and work-order events persisted")
        return 0
    finally:
        try:
            for process in reversed(processes):
                stop_service(process)
        finally:
            local_log.LOG_DIR = previous_logs
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

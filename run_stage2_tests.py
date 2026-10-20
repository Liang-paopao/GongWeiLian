"""Black-box stage two integration checks with three real local services."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from contextlib import ExitStack

from stage2_db import connect_db, initialize_database

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "reports" / "local-test-runs"
PORTS = {"resource": 18112, "workorder": 18113, "leader": 18110}


def allocate_loopback_ports(names) -> dict[str, int]:
    # Keep all sockets bound until every port is chosen to avoid duplicates.
    with ExitStack() as stack:
        ports = {}
        for name in names:
            listener = stack.enter_context(socket.socket())
            listener.bind(("127.0.0.1", 0))
            ports[name] = listener.getsockname()[1]
        return ports


def http_json(url: str, method: str = "GET", payload: dict | None = None, headers: dict | None = None) -> tuple[int, dict | list]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=8) as response:
        content = response.read().decode("utf-8")
        return response.status, json.loads(content) if content else {}


def wait_health(url: str) -> None:
    deadline = time.time() + 20
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            status, payload = http_json(url)
            if status == 200 and payload.get("status") == "ok":
                return
        except Exception as exc:  # service is still starting
            last_error = exc
        time.sleep(.25)
    raise RuntimeError(f"服务未在预期时间内健康：{url}; {last_error}")


def start_service(module: str, port: int, env: dict[str, str], log_name: str) -> subprocess.Popen:
    stdout = (LOG_DIR / f"stage2_{log_name}.log").open("w", encoding="utf-8")
    stderr = (LOG_DIR / f"stage2_{log_name}.err.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", f"{module}:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
    )
    process._stage2_files = (stdout, stderr)  # type: ignore[attr-defined]
    return process


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=6)
    for stream in getattr(process, "_stage2_files", ()):  # type: ignore[attr-defined]
        stream.close()


def expect_http_error(url: str, payload: dict, expected_status: int) -> dict:
    try:
        http_json(url, method="POST", payload=payload)
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        if exc.code != expected_status:
            raise AssertionError(f"预期 HTTP {expected_status}，实际 {exc.code}: {body}")
        return body
    raise AssertionError(f"请求应返回 HTTP {expected_status}: {url}")


def main() -> int:
    global LOG_DIR, PORTS
    report_root = ROOT / "reports" / "local-test-runs"
    report_root.mkdir(parents=True, exist_ok=True)
    LOG_DIR = Path(tempfile.mkdtemp(prefix="stage2-", dir=report_root))
    PORTS = allocate_loopback_ports(("resource", "workorder", "leader"))
    processes: list[subprocess.Popen] = []
    with tempfile.TemporaryDirectory(prefix="gongwei-stage2-") as temporary:
        db_path = str(Path(temporary) / "stage2.db")
        env = os.environ.copy()
        env.update({
            "GONGWEI_TRANSPORT_MODE": "local_rpc",
            "GONGWEI_RUNTIME_MODE": "local",
            "GONGWEI_DISCOVERY_URL": "",
            "DISCOVERY_URL": "",
            "GONGWEI_LOG_DIR": str(LOG_DIR),
            "GONGWEI_STAGE2_DB": db_path,
            "GONGWEI_STAGE2_RESOURCE_PORT": str(PORTS["resource"]),
            "GONGWEI_STAGE2_WORKORDER_PORT": str(PORTS["workorder"]),
            "GONGWEI_STAGE2_LEADER_PORT": str(PORTS["leader"]),
            "NO_PROXY": "127.0.0.1,localhost,::1",
        })
        (LOG_DIR / "run.json").write_text(json.dumps({"transport": "local_rpc", "ports": PORTS,
            "temporary_database": db_path}, indent=2) + "\n", encoding="utf-8")
        print(f"STAGE2 LOGS: {LOG_DIR}")
        try:
            for module, role in (("resource_partner_v1", "resource"),
                                 ("work_order_partner_v1", "workorder"), ("web_app", "leader")):
                processes.append(start_service(module, PORTS[role], env, role))
            wait_health(f"http://127.0.0.1:{PORTS['resource']}/health")
            wait_health(f"http://127.0.0.1:{PORTS['workorder']}/health")
            wait_health(f"http://127.0.0.1:{PORTS['leader']}/health")

            missing_status, missing = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests", "POST", {"pump_id": "pump-001"})
            assert missing_status == 201 and missing["status"] == "awaiting_input"
            work_date = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400))
            payload = {"pump_id": "pump-001", "work_date": work_date, "start_time": "09:00", "duration_minutes": 60, "description": "集成测试检查任务"}
            _, request = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests", "POST", payload)
            _, plan = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests/{request['id']}/propose", "POST")
            assert plan["status"] == "proposed"
            _, confirmed = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/plans/{plan['id']}/confirm", "POST", headers={"Idempotency-Key": "integration-confirm-001"})
            assert confirmed["ok"] and confirmed["work_order"]["status"] == "confirmed"
            _, duplicate = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/plans/{plan['id']}/confirm", "POST", headers={"Idempotency-Key": "integration-confirm-001"})
            assert duplicate["idempotent"] and duplicate["work_order"]["id"] == confirmed["work_order"]["id"]
            order_id = confirmed["work_order"]["id"]
            _, in_progress = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/work-orders/{order_id}/status", "POST", {"status": "in_progress"})
            assert in_progress["status"] == "in_progress"
            _, cancelled = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/work-orders/{order_id}/cancel", "POST")
            assert cancelled["status"] == "cancelled"
            _, timeline = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/inspection-requests/{request['id']}/timeline")
            event_types = {event["event_type"] for event in timeline["events"]}
            assert {"request_created", "plan_generated", "resource_reserved", "work_order_created", "work_order_cancelled"}.issubset(event_types)
            _, calls = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/aip-calls")
            partners = {row.get("partner") for row in calls}
            assert {"resource", "workorder"}.issubset(partners)
            with connect_db(db_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0] == 1
                assert connection.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] >= 5
            stop_process(processes.pop())
            stop_process(processes.pop())
            stop_process(processes.pop())
            processes.clear()
            # A restart must read the same SQLite file and preserve the cancelled order.
            processes.append(start_service("web_app", PORTS["leader"], env, "leader_restart"))
            wait_health(f"http://127.0.0.1:{PORTS['leader']}/health")
            _, orders = http_json(f"http://127.0.0.1:{PORTS['leader']}/api/work-orders")
            assert len(orders) == 1 and orders[0]["status"] == "cancelled"
            print("STAGE2 INTEGRATION PASSED")
            print("REAL AIP PARTNERS: resource, workorder")
            print("WEB FLOW: create -> propose -> confirm -> duplicate confirm -> in_progress -> cancel")
            print("PERSISTENCE: restart retained cancelled work order")
            return 0
        finally:
            for process in reversed(processes):
                stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())

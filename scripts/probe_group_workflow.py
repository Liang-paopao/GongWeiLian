"""Real three-identity MQ regression against an isolated seeded SQLite DB.

This diagnostic tests transport and business idempotency, not DingDang or live
Discovery. It deliberately does not publish availability for transient clients.
"""
import argparse
import asyncio
import json
import logging
import ssl
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from acps_sdk.aip import TaskState
from mq_group_transport import OfficialMqGroupLeaderAdapter, OfficialMqPartnerHandler, OfficialMqPartnerRuntime
from platform_runtime_config import validate_identity_certificate
from scripts.probe_group_resource import SafeDiagnosticLog, public_message
from stage2_db import connect_db, initialize_database
from stage2_domain import create_inspection_request, create_plan


def replay_receipt(events, role, message_id):
    return next((event for event in events if event.get("event") == "command_processed"
                 and event.get("role") == role and event.get("id") == message_id
                 and event.get("mentioned") and event.get("duplicate") and event.get("ok")), None)


async def probe(secrets, auth_url, db, report):
    identities = json.loads((secrets / "aics.json").read_text(encoding="utf-8"))
    selected = {}
    for role, name, stem in (("leader", "工维联核心业务 Leader", "leader"),
                             ("resource", "工维联资源协调 Partner", "resource_partner"),
                             ("workorder", "工维联工单处理 Partner", "workorder")):
        record = identities[name]
        if record.get("approval_status") != "APPROVED" or record.get("is_active") is not True:
            raise RuntimeError(f"{role} is not approved/active")
        aic = record["aic"]
        cert, key = secrets / f"certs/{stem}.crt", secrets / f"certs/private/{stem}.key"
        validate_identity_certificate(cert, key, aic)
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=str(secrets / "certs/trust-bundle.pem"))
        context.load_cert_chain(str(cert), str(key))
        selected[role] = (aic, {"host": "wt.ioa.pub", "port": 5671, "vhost": "acps",
                               "ssl_context": context, "auth_service_url": auth_url,
                               "identity_binding_enabled": True})
    assert len({value[0] for value in selected.values()}) == 3
    initialize_database(db)
    tomorrow = (datetime.now(timezone(timedelta(hours=8))).date() + timedelta(days=1)).isoformat()
    request = create_inspection_request({"pump_id": "pump-001", "work_date": tomorrow,
        "start_time": "14:00", "duration_minutes": 60, "description": "正式 MQ 隔离回归"}, db)
    session_id = "mq-fix-" + uuid.uuid4().hex
    second_session_id = session_id + "-second"
    parent_task_id = session_id + "-main"
    report.update(session_id=session_id, second_session_id=second_session_id, parent_task_id=parent_task_id, request_id=request["id"],
                  identities={role: data[0] for role, data in selected.items()}, phases=[])
    plan, expected_order, expected_reservations = None, None, None
    for phase in (1, 2):
        row = {"phase": phase, "fresh_sdk_clients": True, "events": [], "tasks": []}
        report["phases"].append(row)
        leader_aic, leader_config = selected["leader"]
        leader = OfficialMqGroupLeaderAdapter(leader_aic=leader_aic, rabbitmq_config=leader_config)
        partners = []
        async def admit(invitation):
            row["events"].append({"event": "inbox_invitation", **public_message(invitation)})
            return invitation.senderId == leader_aic and invitation.groupId in {
                f"group-{session_id}", f"group-{second_session_id}"}

        async def call(role, action, *, target_session=None, **payload):
            target_session = target_session or session_id
            task_id = f"{parent_task_id}:phase{phase}:{len(row['tasks'])}:{role}"
            begin = time.perf_counter()
            session = leader.group_leader.group_sessions[target_session]
            await leader.start_task(session_id=target_session, task_id=task_id, target_partners=[selected[role][0]],
                task_content=json.dumps({"action": action, "parent_task_id": parent_task_id, **payload}))
            deadline, completing = asyncio.get_running_loop().time() + 35, False
            while asyncio.get_running_loop().time() < deadline:
                snapshot = session.get_partner_task_snapshot(task_id, selected[role][0])
                if snapshot and snapshot["state"] == TaskState.AwaitingCompletion and not completing:
                    await leader.group_leader.complete_task(target_session, task_id, selected[role][0])
                    completing = True
                if snapshot and snapshot["state"] in {TaskState.Completed, TaskState.Failed, TaskState.Rejected}:
                    break
                await asyncio.sleep(0.05)
            summary = session.get_task_summary(task_id)
            messages = [public_message(m) for m in session.message_history if getattr(m, "taskId", None) == task_id]
            result = json.loads(summary["products"].get(selected[role][0]) or "null")
            task = {"session_id": target_session, "task_id": task_id, "parent_task_id": parent_task_id, "role": role,
                    "action": action, "elapsed_ms": round((time.perf_counter() - begin) * 1000, 2),
                    "messages": messages, "result": result}
            row["tasks"].append(task)
            assert summary["states"].get(selected[role][0]) == TaskState.Completed, summary["states"]
            assert result and result.get("ok"), result
            assert {"accepted", "working", "awaiting-completion", "completed"}.issubset(
                {m.get("state") for m in messages})
            return result

        try:
            for role in ("resource", "workorder"):
                aic, config = selected[role]
                runtime = OfficialMqPartnerRuntime(partner_aic=aic, rabbitmq_config=config)
                handler = OfficialMqPartnerHandler(role, runtime.client, db_path=db)
                async def on_command(command, is_mentioned=True, *, business=handler, partner_role=role):
                    row["events"].append({"event": "received_command", "role": partner_role, **public_message(command)})
                    if command.sessionId not in {session_id, second_session_id}:
                        raise RuntimeError("Unexpected diagnostic task session")
                    duplicate = (command.groupId or "", command.taskId or "", command.id) in business._processed
                    result = await business.handle(command, is_mentioned)
                    row["events"].append({"event": "command_processed", "role": partner_role,
                        **public_message(command), "mentioned": is_mentioned, "duplicate": duplicate,
                        "ok": result.get("ok", False)})
                    return result
                runtime.set_command_handler(on_command)
                partners.append(runtime)
                await asyncio.wait_for(runtime.start_inbox(admit), 25)
            row["group"] = await asyncio.wait_for(leader.create_group_and_invite(session_id=session_id,
                partners=[{"aic": selected[r][0], "amqp_endpoint": f"amqps://wt.ioa.pub:5671/acps?inbox=inbox_{selected[r][0]}",
                           "auth_service_url": auth_url} for r in ("resource", "workorder")]), 50)
            row["second_group"] = await asyncio.wait_for(leader.create_group_and_invite(session_id=second_session_id,
                partners=[{"aic": selected[r][0], "amqp_endpoint": f"amqps://wt.ioa.pub:5671/acps?inbox=inbox_{selected[r][0]}",
                           "auth_service_url": auth_url} for r in ("resource", "workorder")]), 50)
            # Both groups remain open. Returning to the first after using the second
            # catches SDK clients accidentally sharing one mutable group route.
            await call("resource", "query_resources", target_session=second_session_id, request_id=request["id"])
            query = await call("resource", "query_resources", request_id=request["id"])
            row["two_live_groups_query_passed"] = True
            if phase == 1:
                plan = create_plan(request["id"], db, preview=query["result"])
            await call("resource", "reserve_resources", plan_id=plan["id"])
            await call("resource", "reserve_resources", plan_id=plan["id"])
            created = await call("workorder", "create_work_order", plan_id=plan["id"], idempotency_key=parent_task_id)
            repeated = await call("workorder", "create_work_order", plan_id=plan["id"], idempotency_key=parent_task_id)
            order_id = created["result"]["work_order"]["id"]
            assert repeated["result"]["work_order"]["id"] == order_id
            session = leader.group_leader.group_sessions[session_id]
            replay = next(m for m in session.message_history if getattr(m, "taskId", None) == row["tasks"][-1]["task_id"] and getattr(m, "type", None) == "task-command")
            count_before = len(row["events"])
            await session.leader_mq_client.publish_message(replay)
            deadline = asyncio.get_running_loop().time() + 10
            while replay_receipt(row["events"][count_before:], "workorder", replay.id) is None and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.05)
            receipt = replay_receipt(row["events"][count_before:], "workorder", replay.id)
            assert receipt is not None, "Target workorder Partner did not finish handling the duplicate message"
            row["duplicate_receipt"] = receipt
            with connect_db(db) as conn:
                orders = [dict(r) for r in conn.execute("SELECT * FROM work_orders")]
                reservations = [dict(r) for r in conn.execute("SELECT * FROM reservations WHERE status='active'")]
                row["database"] = {"work_orders": orders, "reservations": reservations,
                    "inventory": [dict(r) for r in conn.execute("SELECT id,available_qty FROM inventory_items")]}
            assert len(orders) == 1 and len(reservations) == 3
            ids = sorted(r["id"] for r in reservations)
            if phase == 1:
                expected_order, expected_reservations = order_id, ids
            else:
                assert order_id == expected_order and ids == expected_reservations
            row.update(pass_result=True, exact_message_replayed=replay.id)
        finally:
            for runtime in reversed(partners):
                await asyncio.wait_for(runtime.close(), 20)
            await asyncio.wait_for(leader.close(), 25)
            row["clients_and_group_closed"] = True
    report["pass_result"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-dir", type=Path, required=True)
    parser.add_argument("--auth-service-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(args.output.with_suffix(".log"), encoding="utf-8")
    handler.addFilter(SafeDiagnosticLog())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "group_api": args.auth_service_url,
              "broker": "amqps://wt.ioa.pub:5671", "database": "isolated seeded diagnostic database",
              "restart_scope": "all three SDK clients reconstructed; not OS/server reboot",
              "dingdang_test": False, "online_discovery_test": False, "platform_verified": False}
    try:
        with tempfile.TemporaryDirectory(prefix="gongwei-mq-workflow-") as temp:
            asyncio.run(probe(args.secrets_dir.resolve(), args.auth_service_url, Path(temp)/"test.db", report))
    except Exception as exc:
        report.update(pass_result=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"pass": report.get("pass_result"), "error": report.get("error"), "phases": len(report.get("phases", []))}))
    return 0 if report.get("pass_result") else 2


if __name__ == "__main__":
    raise SystemExit(main())

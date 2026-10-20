"""Bounded official Group/Inbox diagnostic using an isolated business database.

The caller must explicitly select the identity generation and Group API. This
does not modify the production transport configuration or create work orders.
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
from stage2_db import connect_db, initialize_database
from stage2_domain import create_inspection_request


class SafeDiagnosticLog(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if any(word in message.lower() for word in ("token", "password", "authorization", "-----begin")):
            message = "[credential-bearing diagnostic omitted]"
        record.msg, record.args, record.exc_info, record.exc_text = message, (), None, None
        return True


def public_message(message):
    result = {key: getattr(message, key, None) for key in
              ("type", "id", "sessionId", "taskId", "groupId", "senderId", "senderRole", "sentAt")}
    state = getattr(getattr(message, "status", None), "state", None)
    if state is not None:
        result["state"] = state.value
    return result


async def probe(secrets, auth_url, db, report):
    identities = json.loads((secrets / "aics.json").read_text(encoding="utf-8"))
    selected = {}
    for role, name, stem in (("leader", "工维联核心业务 Leader", "leader"),
                             ("resource", "工维联资源协调 Partner", "resource_partner")):
        identity = identities[name]
        if identity.get("approval_status") != "APPROVED" or identity.get("is_active") is not True:
            raise RuntimeError(f"{role} identity is not approved and active")
        aic = identity["aic"]
        cert, key = secrets / "certs" / f"{stem}.crt", secrets / "certs/private" / f"{stem}.key"
        validate_identity_certificate(cert, key, aic)
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=str(secrets / "certs/trust-bundle.pem"))
        context.load_cert_chain(str(cert), str(key))
        selected[role] = (aic, {"host": "wt.ioa.pub", "port": 5671, "vhost": "acps",
                               "ssl_context": context, "auth_service_url": auth_url,
                               "identity_binding_enabled": True})
    leader_aic, leader_config = selected["leader"]
    resource_aic, resource_config = selected["resource"]
    if leader_aic == resource_aic:
        raise RuntimeError("The two roles must have independent identities")
    run_id = uuid.uuid4().hex
    session_id, task_id = f"self-audit-{run_id}", f"resource-query-{run_id}"
    initialize_database(db)
    tomorrow = (datetime.now(timezone(timedelta(hours=8))).date() + timedelta(days=1)).isoformat()
    request = create_inspection_request({"pump_id": "pump-001", "work_date": tomorrow,
        "start_time": "14:00", "duration_minutes": 60, "description": "群组自查：只查询资源，不预留、不创建工单。"}, db)
    report.update(leader_aic=leader_aic, resource_aic=resource_aic, session_id=session_id,
                  task_id=task_id, request_id=request["id"], events=[])
    partner = OfficialMqPartnerRuntime(partner_aic=resource_aic, rabbitmq_config=resource_config)
    adapter = OfficialMqGroupLeaderAdapter(leader_aic=leader_aic, rabbitmq_config=leader_config)
    handler = OfficialMqPartnerHandler("resource", partner.client, db_path=db)

    async def invitation(message):
        report["events"].append({"stage": "inbox_invitation_received", **public_message(message)})
        # Official Inbox invitations carry groupId, not a business sessionId.
        # A False policy result rejects stale diagnostics without stopping Inbox.
        return message.senderId == leader_aic and message.groupId == f"group-{session_id}"

    async def command(message, is_mentioned=True):
        report["events"].append({"stage": "partner_received_command", **public_message(message)})
        if message.sessionId != session_id:
            raise RuntimeError("Unrelated task rejected by diagnostic runtime")
        return await handler.handle(message, is_mentioned)

    partner.set_command_handler(command)
    started = time.perf_counter()
    try:
        await asyncio.wait_for(partner.start_inbox(invitation), 25)
        report["resource_inbox"] = "PASS"
        report["group"] = await asyncio.wait_for(adapter.create_group_and_invite(
            session_id=session_id, partners=[{"aic": resource_aic,
                "amqp_endpoint": f"amqps://wt.ioa.pub:5671/acps?inbox=inbox_{resource_aic}",
                "auth_service_url": auth_url}]), 45)
        report["inbox_invite_and_join"] = "PASS"
        session = adapter.group_leader.group_sessions[session_id]
        await adapter.start_task(session_id=session_id,
            task_content=json.dumps({"action": "query_resources", "request_id": request["id"],
                                     "parent_task_id": task_id}),
            target_partners=[resource_aic], task_id=task_id)
        deadline, completion_sent = asyncio.get_running_loop().time() + 30, False
        while asyncio.get_running_loop().time() < deadline:
            snapshot = session.get_partner_task_snapshot(task_id, resource_aic)
            if snapshot and snapshot["state"] == TaskState.AwaitingCompletion and not completion_sent:
                await adapter.group_leader.complete_task(session_id, task_id, resource_aic)
                completion_sent = True
            if snapshot and snapshot["state"] in {TaskState.Completed, TaskState.Failed, TaskState.Rejected}:
                break
            await asyncio.sleep(0.05)
        summary = session.get_task_summary(task_id)
        report["final_state"] = str(summary["states"].get(resource_aic))
        product = summary["products"].get(resource_aic)
        report["resource_result"] = json.loads(product) if product else None
        report["leader_message_history"] = [public_message(m) for m in session.message_history]
        report["states_received"] = [m["state"] for m in report["leader_message_history"] if m.get("state")]
        report["task_pass"] = (summary["states"].get(resource_aic) == TaskState.Completed
                               and bool(report["resource_result"] and report["resource_result"].get("ok")))
    except Exception as exc:
        report.update(task_pass=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        # Leave before Leader disbands so two SDK cleanup paths do not race.
        for name, close in (("partner_close", partner.close), ("group_cleanup", adapter.close)):
            try:
                await asyncio.wait_for(close(), 20)
                report[name] = "PASS"
            except Exception as exc:
                report[name] = f"{type(exc).__name__}: {exc}"
    with connect_db(db) as connection:
        report["database_counts"] = {table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                                     for table in ("work_orders", "reservations")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-dir", required=True, type=Path)
    parser.add_argument("--auth-service-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.auth_service_url.startswith("https://"):
        parser.error("The Group API must use verified HTTPS")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    log = logging.FileHandler(args.output.with_suffix(".log"), encoding="utf-8")
    log.addFilter(SafeDiagnosticLog())
    log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[log])
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "tested_group_api": args.auth_service_url,
              "broker": "amqps://wt.ioa.pub:5671", "identity_binding_enabled": True,
              "data_scope": "isolated seeded diagnostic database; real platform MQ",
              "production_configuration_changed": False, "platform_verified": False}
    try:
        with tempfile.TemporaryDirectory(prefix="gongwei-group-audit-") as directory:
            asyncio.run(probe(args.secrets_dir.resolve(), args.auth_service_url, Path(directory) / "audit.db", report))
    finally:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("task_pass", "inbox_invite_and_join", "states_received", "error", "group_cleanup")}))
    return 0 if report.get("task_pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())

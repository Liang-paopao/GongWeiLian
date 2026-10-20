"""Leader-side AIP runtime for the stage three platform preparation.

The runtime exposes the same business operations as the web application through
the official ACPs SDK.  It deliberately keeps identity binding disabled while
the registration is pending and the platform-issued AIC is not available.
"""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from acps_sdk.aip import TaskCommand, TaskResult, TaskState
from acps_sdk.aip.aip_rpc_server import CommandHandlers

from local_log import record
from stage2_aip import PartnerCallError, call_partner
from stage2_domain import (
    DomainError,
    create_inspection_request,
    create_plan,
    get_request,
    list_events,
    list_work_orders,
)
from agentic_core import create_conversation, handle_conversation_message
from stage2_partner_common import (
    complete_with_identity,
    extract_payload,
    failure_payload,
    result_with_payload,
)

LEADER_AIC = "stage2-gongwei-leader"


async def handle_start(command: TaskCommand, previous: TaskResult | None) -> TaskResult:
    """Handle a new Leader task and return a serialisable business result."""
    if previous is not None:
        previous.senderId = LEADER_AIC
        return previous

    try:
        payload = extract_payload(command)
        action = payload.get("action")
        if action in {"handle_maintenance_request", "chat"} or payload.get("text"):
            session_id = command.sessionId or f"external-session-{uuid.uuid4()}"
            task_id = command.taskId or f"external-task-{uuid.uuid4()}"
            try:
                create_conversation(session_id=session_id, task_id=task_id)
            except sqlite3.IntegrityError:
                # A retried external command reuses the durable conversation.
                pass
            result = await _handle_external_text(command, str(payload.get("text") or payload.get("message") or ""), session_id=session_id)
        elif action == "create_inspection_request":
            result = {"request": create_inspection_request(payload.get("request") or {})}
        elif action == "propose_inspection":
            request_id = payload["request_id"]
            resources = await call_partner("resource", "query_resources", {"request_id": request_id})
            preview = resources["result"]
            if not preview.get("available"):
                raise DomainError("；".join(preview.get("reasons") or ["没有可执行资源"]))
            result = {"plan": create_plan(request_id, preview=preview)}
        elif action == "get_timeline":
            request_id = payload["request_id"]
            result = {"request": get_request(request_id), "events": list_events(request_id)}
        elif action == "list_work_orders":
            result = {"work_orders": list_work_orders()}
        else:
            raise DomainError("Leader AIP 不支持此 action。")

        response = {"simulated": True, "ok": True, "action": action, "result": result}
        record("stage3_leader", "aip_result", {"task_id": command.taskId, "action": action, "response": response})
        return result_with_payload(command, LEADER_AIC, response)
    except (DomainError, PartnerCallError, KeyError, TypeError, ValueError) as exc:
        response = failure_payload(exc)
        record("stage3_leader", "aip_error", {"task_id": command.taskId, "response": response})
        return result_with_payload(command, LEADER_AIC, response, state=TaskState.Failed)


async def handle_complete(command: TaskCommand, task: TaskResult) -> TaskResult:
    return await complete_with_identity(command, task, LEADER_AIC)


LEADER_HANDLERS = CommandHandlers(on_start=handle_start, on_complete=handle_complete)


async def _handle_external_text(command: TaskCommand, text: str, *, session_id: str | None = None) -> dict[str, Any]:
    if not text:
        raise DomainError("外部 Leader 请求缺少 text。")
    result = handle_conversation_message(session_id or command.sessionId or "", text, message_id=command.id)
    if result["status"] == "awaiting_input":
        return {"state": "awaiting_input", "task_id": result["task_id"], "missing_fields": result["missing_fields"], "question": result["question"]}
    return {"state": "awaiting_completion", "task_id": result["task_id"], "request": result["request"], "next_action": "discover_and_plan"}

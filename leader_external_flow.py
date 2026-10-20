"""External Leader Inbox orchestration for the official MQ process.

This module is deliberately separate from the browser API.  It consumes the
same durable conversation/domain functions, but every Partner call uses the
external session/task IDs supplied by the MQ command and the strict online
discovery path.  No local RPC fallback is permitted here.
"""
from __future__ import annotations

import json
import re
import hashlib
from contextvars import ContextVar
from typing import Any

from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem

from agentic_core import handle_conversation_message
from local_log import record
from mq_group_transport import _env_any
from partner_resolver import PartnerResolver
from plan_continuation import adopt_reference, adopt_unreserved_cancellation, bound_current_answer, explicit_reference, issue_reference, latest_human_text, owns_protocol_task, withdraw_reference
from stage2_aip import PartnerCallError, call_partner
from stage2_db import connect_db, transaction, upsert_agent_subtask
from stage2_domain import (
    DomainError,
    cancel_work_order,
    create_plan,
    get_plan,
    get_plan_for_request,
    get_request,
    now_utc,
)

cancellation_requested: ContextVar[Any] = ContextVar("leader_cancellation_requested", default=lambda: False)
register_compensation: ContextVar[Any] = ContextVar("leader_register_compensation", default=lambda plan_id: None)


class ExternalCommandCancelled(Exception):
    """The RPC dispatcher queued cancellation between two business actions."""


def _check_cancellation() -> None:
    if cancellation_requested.get()():
        raise ExternalCommandCancelled()


def _payload(command: TaskCommand) -> dict[str, Any]:
    values = [item.text for item in command.dataItems or [] if isinstance(item, TextDataItem)]
    if not values:
        return {}
    raw = values[0].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}
    if isinstance(parsed, dict):
        return parsed
    return {"text": raw}


def _task(task_id: str) -> dict[str, Any]:
    with connect_db() as connection:
        row = connection.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        raise DomainError("外部任务不存在或已过期。")
    result = dict(row)
    result["context"] = json.loads(result.pop("context_json") or "{}")
    return result


def _question_result(result: dict[str, Any], *, message_id: str) -> dict[str, Any]:
    return {
        "state": "awaiting_input",
        "result": {
            "sessionId": result["session_id"],
            "taskId": result["task_id"],
            "messageId": message_id,
            "missingFields": result["missing_fields"],
            "question": result["question"],
            "parserMode": result["parser_mode"],
            "nextCommand": "continue",
            "continuation": {"sessionId": result["session_id"], "taskId": result["task_id"], "instruction": "收集用户补充后，对此任务发送 continue；不要取消后重新 start。"},
        },
        "question": result["question"],
    }


async def _plan_for_task(command: TaskCommand, result: dict[str, Any]) -> dict[str, Any]:
    _check_cancellation()
    task_id = result["task_id"]
    session_id = result["session_id"]
    request = result["request"]
    discovery_url = _env_any("GONGWEI_DISCOVERY_URL", "DISCOVERY_URL")
    if not discovery_url:
        raise DomainError("正式 MQ 模式缺少 discovery server 地址，未使用本地静态 ACS。")
    discovery = PartnerResolver(discovery_url=discovery_url, strict_online=True).resolve(
        "resource", ["gongwei.resource.query"], task_id=task_id
    )
    if not discovery.get("selected"):
        raise DomainError(discovery.get("error") or "在线发现没有返回可用资源 Partner。")
    # Keep each query stable across crash recovery while giving revisions a new
    # SDK task ID; otherwise the Partner returns its old completed snapshot.
    with connect_db() as connection:
        previous = connection.execute("SELECT external_task_id FROM task_subtasks WHERE parent_task_id=? AND action='query_resources' AND message_id=?", (task_id, command.id)).fetchone()
        has_query = connection.execute("SELECT 1 FROM task_subtasks WHERE parent_task_id=? AND action='query_resources'", (task_id,)).fetchone()
    resource_task_id = previous["external_task_id"] if previous else (f"{task_id}:resource:01" if not has_query else f"{task_id}:resource:query:{hashlib.sha256(command.id.encode()).hexdigest()[:24]}")
    upsert_agent_subtask(task_id, resource_task_id, "resource", "query_resources", message_id=command.id)
    resources = await call_partner(
        "resource",
        "query_resources",
        {"request_id": request["id"]},
        session_id=session_id,
        task_id=resource_task_id,
    )
    _check_cancellation()
    upsert_agent_subtask(task_id, resource_task_id, "resource", "query_resources", message_id=command.id, status="completed", result=resources)
    preview = resources.get("result") or {}
    if not preview.get("available"):
        raise DomainError("；".join(preview.get("reasons") or ["资源冲突，需要重新安排。"]))
    plan = get_plan_for_request(request["id"])
    if plan:
        if plan["status"] != "proposed" or plan.get("work_order"):
            raise DomainError("资源已预留或工单已创建，不能覆盖方案。")
        with transaction() as connection:
            connection.execute("UPDATE plans SET worker_id=?,inventory_json=?,updated_at=? WHERE id=?", (preview["workers"][0]["id"], json.dumps([item["id"] for item in preview["inventory"] if item["id"] in {"tool-inspection-kit", "part-seal-ring"}]), now_utc(), plan["id"]))
        plan = get_plan(plan["id"])
    else:
        plan = create_plan(request["id"], preview=preview)
    with transaction() as connection:
        connection.execute("UPDATE agent_tasks SET plan_id=?,status='proposed',updated_at=? WHERE task_id=?", (plan["id"], now_utc(), task_id))
    worker_name = (plan.get("worker") or {}).get("name") or plan["worker_id"]
    inventory_names = "、".join(item["name"] for item in plan.get("inventory", [])) or "无"
    reference = issue_reference(task_id, plan) if owns_protocol_task.get()(task_id) else None
    confirmation_prompt = (f"方案编号：{reference}。确认请回复“确认方案 {reference} 并创建工单。”，"
                           if reference else "确认请回复“确认这个方案并创建工单。”，")
    # Human consent is additional input. AwaitingCompletion is the protocol
    # acknowledgement of a finished result, not permission for new side effects.
    return {
        "state": "awaiting_input",
        "question": (f"待确认检查方案：设备 {request['pump_id']}；{request['work_date']} "
                     f"{request['start_time']} 开始，预计 {request['duration_minutes']} 分钟；"
                     f"人员：{worker_name}；工具/配件：{inventory_names}。"
                     f"当前尚未预留资源或创建工单。{confirmation_prompt}"
                     "也可以补充修改要求或回复“取消任务”。请对当前任务发送 continue。"),
        "result": {
            "sessionId": session_id,
            "taskId": task_id,
            "messageId": command.id,
            "status": "awaiting_user_confirmation",
            "requiresConfirmation": True,
            **({"confirmationReference": reference} if reference else {}),
            "nextCommand": "continue",
            "request": get_request(request["id"]),
            "plan": plan,
            "discovery": discovery,
        },
    }


async def _release_resources(command: TaskCommand, plan_id: str) -> None:
    # A failed SDK task is terminal, so another cleanup attempt needs a fresh
    # subtask ID. Releasing a plan is itself idempotent in the business layer.
    with connect_db() as connection:
        count = connection.execute("SELECT COUNT(*) FROM task_subtasks WHERE parent_task_id=? AND action='release_resources'", (command.taskId,)).fetchone()[0]
    release_id = f"{command.taskId}:resource:release:{count + 1:02d}"
    upsert_agent_subtask(command.taskId, release_id, "resource", "release_resources", message_id=command.id)
    try:
        await call_partner("resource", "release_resources", {"plan_id": plan_id}, session_id=command.sessionId, task_id=release_id)
    except Exception:
        upsert_agent_subtask(command.taskId, release_id, "resource", "release_resources", message_id=command.id, status="failed")
        raise
    upsert_agent_subtask(command.taskId, release_id, "resource", "release_resources", message_id=command.id, status="completed")


async def compensate_external_failure(command: TaskCommand, plan_id: str) -> dict[str, Any]:
    recovered = _reconcile_work_order(command, plan_id)
    if recovered:
        return recovered
    try:
        await _release_resources(command, plan_id)
    except Exception:
        recovered = _reconcile_work_order(command, plan_id)
        if recovered:
            return recovered
        raise
    recovered = _reconcile_work_order(command, plan_id)
    if recovered:
        return recovered
    with transaction() as connection:
        connection.execute("UPDATE agent_tasks SET status='failed',updated_at=? WHERE task_id=?", (now_utc(), command.taskId))
    return {"state": "failed", "result": {"sessionId": command.sessionId, "taskId": command.taskId, "messageId": command.id, "status": "failed", "compensation": "completed"}, "error": "工单未创建，已释放预留资源。"}


def _record_completion(task_id: str, plan_id: str) -> None:
    with transaction() as connection:
        connection.execute("UPDATE agent_tasks SET status='completed',updated_at=? WHERE task_id=?", (now_utc(), task_id))
        connection.execute("INSERT OR IGNORE INTO user_confirmations(confirmation_id,task_id,action,decision,payload_json,created_at) VALUES(?,?,?,?,?,?)", (f"confirmation-{task_id}", task_id, "create_work_order", "confirmed", json.dumps({"plan_id": plan_id}), now_utc()))


def _reconcile_work_order(command: TaskCommand, plan_id: str) -> dict[str, Any] | None:
    plan = get_plan(plan_id)
    order = plan.get("work_order")
    if not order:
        return None
    _check_cancellation()
    if order["status"] == "cancelled":
        with transaction() as connection:
            connection.execute("UPDATE agent_tasks SET status='cancelled',updated_at=? WHERE task_id=?", (now_utc(), command.taskId))
        return {"state": "canceled", "result": {"sessionId": command.sessionId, "taskId": command.taskId, "messageId": command.id, "status": "cancelled", "plan": plan, "workOrder": order, "idempotent": True}}
    _record_completion(command.taskId, plan_id)
    return {"state": "completed", "result": {"sessionId": command.sessionId, "taskId": command.taskId, "messageId": command.id, "status": "completed", "plan": plan, "workOrder": order, "idempotent": True}}


async def _confirm(command: TaskCommand, task: dict[str, Any]) -> dict[str, Any]:
    _check_cancellation()
    if not task.get("request_id"):
        raise DomainError("确认前仍缺少检查信息。")
    plan = get_plan_for_request(task["request_id"])
    if not plan:
        raise DomainError("当前任务没有待确认方案。")
    if plan.get("work_order"):
        return _reconcile_work_order(command, plan["id"])
    session_id = task["session_id"]
    task_id = task["task_id"]
    discovery_url = _env_any("GONGWEI_DISCOVERY_URL", "DISCOVERY_URL")
    if not discovery_url:
        raise DomainError("正式 MQ 模式缺少 discovery server 地址，未使用本地静态 ACS。")
    workorder_discovery = PartnerResolver(discovery_url=discovery_url, strict_online=True).resolve(
        "workorder", ["gongwei.work-order.create"], task_id=task_id
    )
    if not workorder_discovery.get("selected"):
        raise DomainError(workorder_discovery.get("error") or "在线发现没有返回可用工单 Partner。")
    reserve_id = f"{task_id}:resource:02"
    upsert_agent_subtask(task_id, reserve_id, "resource", "reserve_resources", message_id=command.id)
    try:
        await call_partner("resource", "reserve_resources", {"plan_id": plan["id"]}, session_id=session_id, task_id=reserve_id)
        upsert_agent_subtask(task_id, reserve_id, "resource", "reserve_resources", message_id=command.id, status="completed")
        _check_cancellation()
        order_id = f"{task_id}:workorder:01"
        upsert_agent_subtask(task_id, order_id, "workorder", "create_work_order", message_id=command.id)
        order_result = await call_partner(
            "workorder",
            "create_work_order",
            {"plan_id": plan["id"], "idempotency_key": f"dingdang-plan-{plan['id']}"},
            session_id=session_id,
            task_id=order_id,
        )
        _check_cancellation()
        upsert_agent_subtask(task_id, order_id, "workorder", "create_work_order", message_id=command.id, status="completed", result=order_result)
    except Exception:
        recovered = _reconcile_work_order(command, plan["id"])
        if recovered:
            return recovered
        # The RPC runtime persists this intent before any cleanup network
        # request, closing the crash window between failure and rollback.
        register_compensation.get()(plan["id"])
        try:
            await _release_resources(command, plan["id"])
        except Exception:
            record("leader_inbox", "compensation_failed", {"session_id": session_id, "task_id": task_id, "message_id": command.id})
        recovered = _reconcile_work_order(command, plan["id"])
        if recovered:
            return recovered
        raise
    _record_completion(task_id, plan["id"])
    final_plan = get_plan(plan["id"])
    return {"state": "completed", "result": {"sessionId": session_id, "taskId": task_id, "messageId": command.id, "status": "completed", "plan": final_plan, "workOrder": (order_result.get("result") or {}).get("work_order"), "idempotent": False}}


def is_explicit_confirmation(command: TaskCommand) -> bool:
    payload = _payload(command)
    text = latest_human_text(str(payload.get("text") or payload.get("message") or ""))
    if any(word in text for word in ("不", "别", "取消", "暂缓", "?", "？")):
        return False
    return payload.get("action") == "confirm_plan" or bool(explicit_reference(text)) or bool(re.fullmatch(r"(?:请)?确认(?:这个|此|该)?方案(?:并(?:创建|生成)工单)?[。！!]?|(?:请)?确认(?:创建|生成)工单[。！!]?", text))


def is_explicit_cancellation(command: TaskCommand) -> bool:
    if command.command == TaskCommandType.Cancel:
        return True
    return _has_user_cancellation(command)


def _has_user_cancellation(command: TaskCommand) -> bool:
    payload = _payload(command)
    text = str(payload.get("text") or payload.get("message") or "").strip()
    if latest_human_text(text) != text:
        try:
            text = bound_current_answer(text, command.taskId)
        except DomainError:
            return False
    return bool(re.fullmatch(r"(?:请)?取消(?:(?:这个|当前|此|该)?(?:任务|方案|工单))?[。！!]?", text))


def _cancellation_result(command: TaskCommand, task: dict[str, Any], *, idempotent: bool = False) -> dict[str, Any]:
    plan = get_plan_for_request(task["request_id"]) if task.get("request_id") else None
    continuation = task["context"].get("cancellation_continuation")
    result = {"sessionId": command.sessionId, "taskId": command.taskId, "messageId": command.id,
              "status": "cancelled", "plan": plan, "workOrder": plan.get("work_order") if plan else None,
              "idempotent": idempotent}
    if continuation:
        result["cancellationContinuation"] = continuation
    if (continuation and continuation.get("command_type") == TaskCommandType.Start.value
            and not task["context"].get("cancellation_protocol_canceled")
            and (command.command != TaskCommandType.Cancel or idempotent)):
        # This new protocol task completed an owned cancellation operation.
        # Keep the canceled business state and the source protocol task intact.
        if (continuation.get("session_id") != command.sessionId
                or str(continuation.get("sender_id", "")).strip().upper() != command.senderId.strip().upper()
                or not plan or plan["id"] != continuation.get("plan_id")
                or plan["status"] != "cancelled" or plan["request"]["status"] != "cancelled"
                or plan.get("work_order")):
            raise DomainError("业务取消状态尚未确认，不能报告操作完成。")
        with connect_db() as connection:
            if connection.execute("SELECT 1 FROM reservations WHERE plan_id=? AND status='active'", (plan["id"],)).fetchone():
                raise DomainError("业务取消仍有活动预留，不能报告操作完成。")
        summary = f"已取消待确认方案 {continuation['reference']}；未预留资源，未创建工单。"
        result.update(operation="cancel_plan", summary=summary)
        return {"state": "completed", "summary": summary, "result": result}
    return {"state": "canceled", "result": result}


async def handle_external_command(command: TaskCommand) -> dict[str, Any]:
    payload = _payload(command)
    text = str(payload.get("text") or payload.get("message") or "").strip()
    task_id = command.taskId or ""
    task = _task(task_id)
    if task["session_id"] != command.sessionId:
        raise DomainError("任务不属于此会话。")
    if task["status"] in {"completed", "cancelled"}:
        if task["status"] == "cancelled":
            return _cancellation_result(command, task, idempotent=True)
        plan = get_plan_for_request(task["request_id"]) if task.get("request_id") else None
        return {"state": "completed", "result": {"sessionId": command.sessionId, "taskId": task_id, "messageId": command.id, "status": task["status"], "plan": plan, "workOrder": plan.get("work_order") if plan else None, "idempotent": True}}
    # Adoption atomically commits the business cancellation and its context.
    # A crash before the final task/RPC snapshot resumes that durable operation.
    cancellation_continuation = task["context"].get("cancellation_continuation")
    if not cancellation_continuation and command.command != TaskCommandType.Cancel:
        cancellation_continuation = adopt_unreserved_cancellation(command, text)
    explicit_cancellation = is_explicit_cancellation(command)
    if (not cancellation_continuation and not explicit_cancellation
            and latest_human_text(text) != text
            and re.fullmatch(r"(?:请)?取消(?:(?:这个|当前|此|该)?(?:任务|方案|工单))?[。！!]?", latest_human_text(text))):
        # A canceled/changed/unowned history must never become a fresh request.
        raise DomainError("未找到当前会话中可取消的待确认方案；可能已经取消或进入确认，请查询当前状态。")
    if explicit_cancellation or cancellation_continuation:
        user_cancel = _has_user_cancellation(command) or bool(cancellation_continuation)
        if user_cancel:
            withdraw_reference(task_id)
        if task_id:
            task = _task(task_id)
            if task.get("request_id"):
                plan = get_plan_for_request(task["request_id"])
                if plan and plan.get("work_order"):
                    # A source proposal's protocol cancellation must not undo
                    # another task's order. The task executing reservation /
                    # creation still owns cancellation compensation, including
                    # a committed order whose MQ reply has not yet returned.
                    with connect_db() as connection:
                        attempted = connection.execute("SELECT 1 FROM task_subtasks WHERE parent_task_id=? AND action IN ('reserve_resources','create_work_order')", (task_id,)).fetchone()
                    if user_cancel or attempted:
                        cancel_work_order(plan["work_order"]["id"])
                elif plan:
                    with connect_db() as connection:
                        reserved = connection.execute("SELECT 1 FROM reservations WHERE plan_id=? AND status='active'", (plan["id"],)).fetchone()
                        attempted = connection.execute("SELECT 1 FROM task_subtasks WHERE parent_task_id=? AND action='reserve_resources'", (task_id,)).fetchone()
                    # A proposal query has no reservation side effect. Do not
                    # turn its cancellation into an unnecessary MQ round trip.
                    # Any reservation attempt (even without a reply) still needs
                    # compensation, including after a crash or connection loss.
                    if (plan["status"] != "proposed" and not cancellation_continuation) or reserved or attempted:
                        await _release_resources(command, plan["id"])
                    else:
                        record("leader_inbox", "cancel_unreserved_proposal", {"session_id": command.sessionId, "task_id": task_id, "message_id": command.id, "plan_id": plan["id"]})
            with transaction() as connection:
                connection.execute("UPDATE agent_tasks SET status='cancelled',updated_at=? WHERE task_id=?", (now_utc(), task_id))
        return _cancellation_result(command, _task(task_id))
    if is_explicit_confirmation(command):
        reference = explicit_reference(text)
        if not reference and latest_human_text(text) != text:
            raise DomainError("带有历史上下文的确认需包含明确方案编号，请使用当前方案的确认句。")
        continuation = adopt_reference(command, reference, text) if reference else None
        result = await _confirm(command, _task(task_id) if continuation else task)
        if continuation:
            result['result']['planContinuation'] = continuation
        return result
    if task.get("request_id"):
        shared_plan = get_plan_for_request(task["request_id"])
        if shared_plan and (shared_plan.get("work_order") or shared_plan["status"] in {"confirming", "confirmed", "cancelled"}):
            raise DomainError("方案已进入确认或终态，不能通过旧任务覆盖；请使用工单变更或取消流程。")
    # The existing conversation table has a global message PK. External callers
    # may independently choose the same message ID, so scope that storage key;
    # protocol receipts/history and outgoing results retain the original ID.
    stored_message_id = "external-message-" + hashlib.sha256(json.dumps([command.senderId.upper(), command.sessionId, task_id, command.id]).encode()).hexdigest()
    result = handle_conversation_message(command.sessionId or "", text, message_id=stored_message_id, task_id=task_id)
    if result["status"] == "awaiting_input":
        return _question_result(result, message_id=command.id)
    return await _plan_for_task(command, result)

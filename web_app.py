"""Leader web/API application for stage two."""
from __future__ import annotations

import json
import hashlib
import uuid
import os
from typing import Any
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from acps_sdk.aip.aip_rpc_server import add_aip_rpc_router

from stage2_aip import PartnerCallError, call_partner
from audio_service import confirm_audio_analysis, get_audio_analysis, link_audio_analysis
from platform_runtime import external_runtime_errors, runtime_mode
from stage2_db import connect_db, database_path, initialize_database, transaction, upsert_agent_subtask
from stage2_domain import (
    DomainError,
    cancel_work_order,
    create_inspection_request,
    create_plan,
    adjust_inventory_quantity,
    get_plan,
    get_request,
    get_plan_for_request,
    list_events,
    list_inventory,
    list_pumps,
    list_work_orders,
    list_workers,
    recover_interrupted_state,
    release_plan_resources,
    replan_request,
    now_utc,
)
from agentic_core import create_conversation, get_conversation, handle_conversation_message
from partner_resolver import PartnerResolver
from stage3_leader_aip import LEADER_AIC, LEADER_HANDLERS
from transport_mode import get_transport_mode, https_configuration_status, mq_configuration_status

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    # A process restart may interrupt the reserve -> work-order window.  The
    # recovery pass is idempotent and records its compensation in the audit.
    recover_interrupted_state()
    yield


app = FastAPI(title="工维联阶段二核心业务系统 V1", lifespan=lifespan)

# Stage three exposes the Leader through the same official AIP RPC contract as
# both Partners.  Platform-issued AIC and mTLS remain pending until review.
add_aip_rpc_router(app, "/rpc", LEADER_HANDLERS, local_aic=LEADER_AIC, identity_binding_enabled=False)


def error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, PartnerCallError):
        return HTTPException(status_code=503, detail={"code": "partner_unavailable", "message": str(exc), "partner": exc.partner, "action": exc.action})
    return HTTPException(status_code=400, detail={"code": "business_error", "message": str(exc)})


@app.get("/health")
async def health() -> dict[str, Any]:
    initialize_database()
    errors = external_runtime_errors()
    mode = runtime_mode()
    transport = get_transport_mode()
    mq_status = mq_configuration_status()
    https_status = https_configuration_status()
    status_errors = list(errors)
    if transport == "platform_mq_inbox" and not mq_status["configured"]:
        status_errors.append("platform_mq_inbox 缺少官方 MQ 配置")
    if transport == "platform_https_rpc" and not https_status["configured"]:
        status_errors.append("platform_https_rpc 缺少正式 HTTPS、AIC 或证书配置")
    return {
        "status": "ok" if not status_errors else "pending",
        "service": "stage2-leader",
        "database": str(database_path()),
        "mode": "local_simulation_only" if mode == "local" else "external",
        "runtime_mode": mode,
        "transport_mode": transport,
        "mq_configuration": mq_status,
        "https_configuration": https_status,
        "external_ready": not status_errors,
        "configuration_errors": status_errors,
        "platform_verified": False,
    }


@app.get("/api/bootstrap")
async def bootstrap() -> dict[str, Any]:
    return {
        "simulated_data": True,
        "platform_verified": False,
        "pumps": list_pumps(), "workers": list_workers(), "inventory": list_inventory(),
        "work_orders": list_work_orders(),
        "labels": {"data_boundary": "模拟业务数据", "stage": "本地智能体化重构", "parser": "无 LLM 时使用确定性回退"},
    }


@app.post("/api/conversations", status_code=201)
async def conversations() -> dict[str, Any]:
    return create_conversation()


@app.post("/api/conversations/{session_id}/messages")
async def conversation_message(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        text = payload.get("text")
        result = handle_conversation_message(session_id, text, message_id=payload.get("message_id"))
        if result["status"] == "ready_for_plan" and result.get("request"):
            discovery_url = os.environ.get("GONGWEI_DISCOVERY_URL")
            discovery = PartnerResolver(discovery_url=discovery_url, strict_online=get_transport_mode() == "platform_mq_inbox").resolve("resource", ["gongwei.resource.query"], task_id=result["task_id"])
            result["discovery"] = discovery
            if discovery["source"] == "discovery_failed" or (get_transport_mode() == "platform_mq_inbox" and not discovery.get("selected")):
                result["status"] = "discovery_failed"
                result["question"] = discovery.get("error") or "没有找到可用资源 Partner。"
                return result
            resource_task_id = f"{result['task_id']}:resource:query:{hashlib.sha256(result['message_id'].encode()).hexdigest()[:24]}"
            upsert_agent_subtask(result["task_id"], resource_task_id, "resource", "query_resources", message_id=result["message_id"])
            resources = await call_partner("resource", "query_resources", {"request_id": result["request"]["id"]}, session_id=result["session_id"], task_id=resource_task_id)
            upsert_agent_subtask(result["task_id"], resource_task_id, "resource", "query_resources", message_id=result["message_id"], status="completed", result=resources)
            if resources["result"].get("available"):
                request_id = result["request"]["id"]
                if get_plan_for_request(request_id):
                    result["plan"] = replan_request(request_id, preview=resources["result"])
                else:
                    result["plan"] = create_plan(request_id, preview=resources["result"])
                result["request"] = get_request(request_id)
                with transaction() as conn:
                    conn.execute("UPDATE agent_tasks SET plan_id=?,status='proposed',updated_at=? WHERE task_id=?", (result["plan"]["id"], now_utc(), result["task_id"]))
            else:
                result["status"] = "replan_required"
                result["conflict"] = resources["result"].get("reasons") or ["资源发生冲突"]
        return result
    except (DomainError, PartnerCallError, ValueError, TypeError) as exc:
        raise error_response(exc)


@app.get("/api/conversations/{session_id}")
async def conversation(session_id: str) -> dict[str, Any]:
    try:
        return get_conversation(session_id)
    except ValueError as exc:
        raise error_response(exc)


def _agent_task(task_id: str) -> dict[str, Any]:
    with connect_db() as conn:
        row = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        raise DomainError("智能体任务不存在。")
    result = dict(row)
    result["context"] = json.loads(result.pop("context_json") or "{}")
    return result


@app.post("/api/tasks/{task_id}/confirm")
async def confirm_task(task_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
    task = _agent_task(task_id)
    if task["status"] in {"cancelled", "failed"}:
        raise error_response(DomainError("任务已结束，不能确认创建工单。"))
    if not task.get("request_id"):
        raise error_response(DomainError("请先补充检查信息。"))
    plan = get_plan_for_request(task["request_id"])
    if not plan:
        resources = await call_partner(
            "resource",
            "query_resources",
            {"request_id": task["request_id"]},
            session_id=task["session_id"],
            task_id=f"{task_id}:resource:02",
        )
        if not resources["result"].get("available"):
            raise error_response(DomainError("；".join(resources["result"].get("reasons") or ["资源发生变化，请重新安排"])))
        plan = create_plan(task["request_id"], preview=resources["result"])
    result = await confirm(
        plan["id"],
        idempotency_key or f"agentic-{task_id}",
        session_id=task["session_id"],
        task_id=task_id,
    )
    with transaction() as conn:
        current = conn.execute("SELECT status FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        if current["status"] == "cancelled":
            raise error_response(DomainError("任务已取消，不能覆盖取消结果。"))
        conn.execute("UPDATE agent_tasks SET status='completed',plan_id=?,updated_at=? WHERE task_id=?", (plan["id"], now_utc(), task_id))
        conn.execute("INSERT INTO user_confirmations(confirmation_id,task_id,action,decision,payload_json,created_at) VALUES(?,?,?,?,?,?)", (f"confirmation-{uuid.uuid4()}", task_id, "create_work_order", "confirmed", json.dumps({"plan_id": plan["id"]}, ensure_ascii=False), now_utc()))
    return {"task_id": task_id, "status": "completed", **result}


@app.post("/api/tasks/{task_id}/revise")
async def revise_task(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = _agent_task(task_id)
    return await conversation_message(task["session_id"], {"text": payload.get("text", "")})


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, Any]:
    task = _agent_task(task_id)
    try:
        plan = get_plan_for_request(task["request_id"]) if task.get("request_id") else None
        if plan and plan.get("work_order"):
            cancel_work_order(plan["work_order"]["id"])
        elif plan:
            # The domain release also fences delayed reservation/order writes.
            release_plan_resources(plan["id"])
    except DomainError as exc:
        raise error_response(exc)
    with transaction() as conn:
        conn.execute("UPDATE agent_tasks SET status='cancelled',updated_at=? WHERE task_id=?", (now_utc(), task_id))
        conn.execute("INSERT INTO user_confirmations(confirmation_id,task_id,action,decision,payload_json,created_at) VALUES(?,?,?,?,?,?)", (f"confirmation-{uuid.uuid4()}", task_id, "task", "cancelled", "{}", now_utc()))
    return {"task_id": task_id, "status": "cancelled"}


@app.get("/api/tasks/{task_id}/trace")
async def task_trace(task_id: str) -> dict[str, Any]:
    task = _agent_task(task_id)
    return {"task": task, "timeline": list_events(task["request_id"]) if task.get("request_id") else [], "conversation": get_conversation(task["session_id"])}


@app.get("/api/discovery/{task_id}")
async def discovery(task_id: str) -> list[dict[str, Any]]:
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM partner_discovery_snapshots WHERE task_id=? ORDER BY created_at", (task_id,)).fetchall()
    return [{**dict(row), "query": json.loads(row["query_json"]), "candidates": json.loads(row["candidates_json"])} for row in rows]


@app.get("/api/platform/status")
async def platform_status() -> dict[str, Any]:
    mq = mq_configuration_status()
    configured = bool(mq.get("configured"))
    checks = {"registration": False, "aic": False, "certificate": False, "mq": configured, "discovery": False, "external_call": False, "background_access": False}
    return {"platform_verified": all(checks.values()), "checks": checks, "transport_mode": get_transport_mode(), "mq": mq, "reason": "平台发现、外部调用和后台访问仍无完整可核验回执"}


@app.get("/api/agents/status")
async def agents_status() -> list[dict[str, Any]]:
    return [{"name": "工维联核心业务 Leader", "role": "Leader", "aic": "", "status": "本机运行", "transport": get_transport_mode()}, {"name": "工维联资源协调 Partner", "role": "Partner", "aic": "", "status": "可发现候选 / 本地回退", "transport": get_transport_mode()}, {"name": "工维联工单处理 Partner", "role": "Partner", "aic": "", "status": "可发现候选 / 本地回退", "transport": get_transport_mode()}]


@app.post("/api/inspection-requests", status_code=201)
async def create_request(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return create_inspection_request(payload)
    except DomainError as exc:
        raise error_response(exc)


@app.post("/api/audio/analyze")
async def analyze_audio(payload: dict[str, Any]) -> dict[str, Any]:
    """Send an uploaded WAV to the real local Sound Analysis Partner."""
    try:
        result = await call_partner("audio", "analyze_audio", payload)
        return result["result"]
    except PartnerCallError as exc:
        raise error_response(exc)


@app.post("/api/audio/confirm")
async def confirm_audio(payload: dict[str, Any]) -> dict[str, Any]:
    """Require explicit user confirmation before creating a request and plan."""
    try:
        analysis_id = str(payload.get("analysis_id") or "")
        analysis = get_audio_analysis(analysis_id)
        if analysis.get("request_id"):
            request = get_request(analysis["request_id"])
            return {"analysis": analysis, "request": request, "plan": request.get("plan")}
        request_payload = {
            "pump_id": payload.get("pump_id"),
            "work_date": payload.get("work_date"),
            "start_time": payload.get("start_time"),
            "duration_minutes": payload.get("duration_minutes"),
            "description": payload.get("description") or f"声音分析 {analysis_id}：{analysis['verdict']}",
        }
        required = ("pump_id", "work_date", "start_time", "duration_minutes", "description")
        if any(request_payload.get(field) in (None, "", 0) for field in required):
            raise DomainError("请补充水泵、日期、时间、时长和检查说明后再确认声音结果。")
        analysis = confirm_audio_analysis(analysis_id)
        request = create_inspection_request(request_payload)
        if request["status"] == "awaiting_input":
            raise DomainError("请补充水泵、日期、时间、时长和检查说明。")
        link_audio_analysis(analysis_id, request["id"])
        resources = await call_partner("resource", "query_resources", {"request_id": request["id"]})
        preview = resources["result"]
        if not preview.get("available"):
            raise DomainError("；".join(preview.get("reasons") or ["没有可执行资源"]))
        plan = create_plan(request["id"], preview=preview)
        return {"analysis": get_audio_analysis(analysis_id), "request": get_request(request["id"]), "plan": plan}
    except (DomainError, PartnerCallError, ValueError, KeyError) as exc:
        raise error_response(exc)


@app.post("/api/inspection-requests/{request_id}/propose")
async def propose(request_id: str) -> dict[str, Any]:
    try:
        resources = await call_partner("resource", "query_resources", {"request_id": request_id})
        result = resources["result"]
        if not result.get("available"):
            raise DomainError("；".join(result.get("reasons") or ["没有可执行资源"]))
        return create_plan(request_id, preview=result)
    except (DomainError, PartnerCallError) as exc:
        raise error_response(exc)


@app.post("/api/inspection-requests/{request_id}/replan")
async def replan(request_id: str) -> dict[str, Any]:
    """Refresh one proposed plan after a resource change."""
    try:
        resources = await call_partner("resource", "query_resources", {"request_id": request_id})
        result = resources["result"]
        # Let the domain layer record an unavailable preview as replan_failed;
        # returning early here would roll back that audit event.
        return replan_request(request_id, preview=result)
    except (DomainError, PartnerCallError) as exc:
        raise error_response(exc)


@app.post("/api/plans/{plan_id}/confirm")
async def confirm(
    plan_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    *,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    key = idempotency_key or f"browser-{plan_id}"
    try:
        plan = get_plan(plan_id)
        existing_order = plan.get("work_order")
        if existing_order:
            return {"simulated": True, "ok": True, "plan": plan, "work_order": existing_order, "idempotent": True}
        resource_kwargs = {"session_id": session_id, "task_id": f"{task_id}:resource:03"} if session_id and task_id else {}
        await call_partner("resource", "reserve_resources", {"plan_id": plan_id}, **resource_kwargs)
        try:
            workorder_kwargs = {"session_id": session_id, "task_id": f"{task_id}:workorder:01"} if session_id and task_id else {}
            work_order_result = await call_partner("workorder", "create_work_order", {"plan_id": plan_id, "idempotency_key": key}, **workorder_kwargs)
        except PartnerCallError:
            # The Partner may have committed the order before its response was
            # lost.  Re-read the database before compensating resources.
            recovered = get_plan(plan_id)
            if recovered.get("work_order") and recovered.get("status") == "confirmed":
                return {"simulated": True, "ok": True, "plan": recovered, "work_order": recovered["work_order"], "idempotent": True, "recovered_after_partner_error": True}
            try:
                release_kwargs = {"session_id": session_id, "task_id": f"{task_id}:resource:04"} if session_id and task_id else {}
                await call_partner("resource", "release_resources", {"plan_id": plan_id}, **release_kwargs)
            except PartnerCallError:
                pass
            raise
        return {"simulated": True, "ok": True, "plan": get_plan(plan_id), "work_order": work_order_result["result"]["work_order"], "idempotent": False}
    except (DomainError, PartnerCallError) as exc:
        raise error_response(exc)


@app.get("/api/work-orders")
async def work_orders() -> list[dict[str, Any]]:
    return list_work_orders()


@app.post("/api/resources/inventory/{item_id}/adjust")
async def adjust_inventory(item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        delta = payload.get("delta")
        if delta is None:
            raise DomainError("请提供 delta 数量调整值。")
        item = adjust_inventory_quantity(item_id, delta, actor="operator")
        return {"item": item, "delta": int(delta)}
    except (DomainError, TypeError, ValueError) as exc:
        raise error_response(exc)


@app.post("/api/work-orders/{work_order_id}/cancel")
async def cancel(work_order_id: str) -> dict[str, Any]:
    try:
        result = await call_partner("workorder", "cancel_work_order", {"work_order_id": work_order_id})
        work_order = result["result"]["work_order"]
        await call_partner("resource", "release_resources", {"plan_id": work_order["plan_id"]})
        return work_order
    except (DomainError, PartnerCallError) as exc:
        raise error_response(exc)


@app.post("/api/work-orders/{work_order_id}/status")
async def update_status(work_order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await call_partner("workorder", "update_work_order", {"work_order_id": work_order_id, "status": payload.get("status")})
        return result["result"]["work_order"]
    except (DomainError, PartnerCallError) as exc:
        raise error_response(exc)


@app.get("/api/inspection-requests/{request_id}/timeline")
async def timeline(request_id: str) -> dict[str, Any]:
    try:
        return {"request": get_request(request_id), "events": list_events(request_id)}
    except DomainError as exc:
        raise error_response(exc)


@app.get("/api/audit")
async def audit(request_id: str) -> dict[str, Any]:
    """Stable audit alias used by stage five integrations."""
    return await timeline(request_id)


@app.get("/api/aip-calls")
async def aip_calls() -> list[dict[str, Any]]:
    import local_log
    from collections import deque
    log_path = local_log.LOG_DIR / "stage2_leader.jsonl"
    if not log_path.exists():
        return []
    rows = []
    with log_path.open(encoding="utf-8") as stream:
        recent_lines = deque(stream, maxlen=80)
    for line in recent_lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

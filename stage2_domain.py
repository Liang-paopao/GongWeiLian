"""Business rules for inspection requests, resources, plans and work orders."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from stage2_db import connect_db, database_path, initialize_database, row_to_dict, transaction

REQUIRED_INVENTORY = ("tool-inspection-kit", "part-seal-ring")
REQUIRED_SKILL = "pump_inspection"
TERMINAL_WORK_ORDER_STATES = {"completed", "cancelled", "failed"}


class DomainError(ValueError):
    """A user-facing business validation or resource conflict."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _parse_date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise DomainError("日期格式应为 YYYY-MM-DD。") from exc


def _parse_time(value: Any) -> time:
    try:
        return time.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise DomainError("开始时间格式应为 HH:MM。") from exc


def _validated_schedule(payload: dict[str, Any]) -> tuple[str, str, int, str]:
    work_date = _parse_date(payload.get("work_date"))
    start = _parse_time(payload.get("start_time"))
    try:
        duration = int(payload.get("duration_minutes"))
    except (TypeError, ValueError) as exc:
        raise DomainError("预计时长必须是整数分钟。") from exc
    if duration < 15 or duration > 480:
        raise DomainError("预计时长必须在 15 至 480 分钟之间。")
    start_dt = datetime.combine(work_date, start)
    end_dt = start_dt + timedelta(minutes=duration)
    if end_dt.date() != work_date:
        raise DomainError("结束时间不能跨日，请缩短预计时长。")
    return work_date.isoformat(), start.strftime("%H:%M"), duration, end_dt.strftime("%H:%M")


def _missing(payload: dict[str, Any]) -> list[str]:
    fields = ("pump_id", "work_date", "start_time", "duration_minutes", "description")
    return [field for field in fields if payload.get(field) in (None, "", [])]


def normalize_request_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize text/structured request aliases into the core business contract.

    Audio is an optional aid. The Leader accepts a direct text or structured
    request and keeps only the fields needed by the existing scheduling flow.
    Extra context such as urgency, skills, and tools remains available to the
    caller without introducing a second persistence schema.
    """
    normalized = dict(payload or {})
    aliases = {
        "device_id": "pump_id",
        "anomaly_description": "description",
        "preferred_time": "start_time",
        "duration": "duration_minutes",
    }
    for source, target in aliases.items():
        if normalized.get(target) in (None, "", []) and normalized.get(source) not in (None, "", []):
            normalized[target] = normalized[source]
    return normalized


def _event(connection: sqlite3.Connection, *, event_type: str, actor: str,
           request_id: str | None = None, work_order_id: str | None = None,
           details: dict[str, Any] | None = None) -> None:
    connection.execute(
        "INSERT INTO task_events(request_id,work_order_id,event_type,actor,details_json,created_at) VALUES(?,?,?,?,?,?)",
        (request_id, work_order_id, event_type, actor,
         json.dumps(details or {}, ensure_ascii=False), now_utc()),
    )


def _request(connection: sqlite3.Connection, request_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM inspection_requests WHERE id=?", (request_id,)).fetchone()
    if row is None:
        raise DomainError("检查任务不存在。")
    return row


def _plan(connection: sqlite3.Connection, plan_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if row is None:
        raise DomainError("待确认方案不存在。")
    return row


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in ("missing_fields", "inventory_json", "details_json"):
        if key in result and isinstance(result[key], str):
            try:
                result[key] = json.loads(result[key])
            except json.JSONDecodeError:
                pass
    return result


def create_inspection_request(payload: dict[str, Any], db_path: str | Path | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    payload = normalize_request_payload(payload)
    missing = _missing(payload)
    request_id = _id("req")
    created = now_utc()
    if missing:
        work_date = start_time = end_time = None
        duration = None
        status = "awaiting_input"
    else:
        work_date, start_time, duration, end_time = _validated_schedule(payload)
        status = "draft"
    with transaction(db_path) as connection:
        if payload.get("pump_id") and connection.execute("SELECT 1 FROM pumps WHERE id=?", (payload["pump_id"],)).fetchone() is None:
            raise DomainError("水泵不在模拟业务数据中。")
        connection.execute(
            "INSERT INTO inspection_requests(id,pump_id,work_date,start_time,duration_minutes,end_time,description,required_skill,status,missing_fields,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (request_id, payload.get("pump_id"), work_date, start_time, duration, end_time,
             payload.get("description"), payload.get("required_skill"), status, json.dumps(missing, ensure_ascii=False), created, created),
        )
        _event(connection, event_type="request_created", actor="leader", request_id=request_id,
               details={"missing_fields": missing, "simulated": True})
    return get_request(request_id, db_path)


def update_inspection_request(request_id: str, payload: dict[str, Any], db_path: str | Path | None = None) -> dict[str, Any]:
    """Merge a later user turn into an awaiting-input request."""
    initialize_database(db_path)
    payload = normalize_request_payload(payload)
    with transaction(db_path) as connection:
        current = _request(connection, request_id)
        if current["status"] in {"confirming", "confirmed", "cancelled"} or connection.execute(
            "SELECT 1 FROM work_orders WHERE request_id=?", (request_id,)
        ).fetchone():
            raise DomainError("检查请求已进入确认或终态，不能覆盖原工单；请使用变更或取消流程。")
        values = {key: current[key] for key in ("pump_id", "work_date", "start_time", "duration_minutes", "description", "required_skill")}
        values.update({key: value for key, value in payload.items() if key in values and value not in (None, "")})
        missing = _missing(values)
        if missing:
            status, work_date, start_time, duration, end_time = "awaiting_input", values.get("work_date"), values.get("start_time"), values.get("duration_minutes"), None
        else:
            work_date, start_time, duration, end_time = _validated_schedule(values)
            status = "draft"
        connection.execute("UPDATE inspection_requests SET pump_id=?,work_date=?,start_time=?,duration_minutes=?,end_time=?,description=?,required_skill=?,status=?,missing_fields=?,updated_at=? WHERE id=?", (values.get("pump_id"), work_date, start_time, duration, end_time, values.get("description"), values.get("required_skill"), status, json.dumps(missing, ensure_ascii=False), now_utc(), request_id))
        _event(connection, event_type="request_updated", actor="leader", request_id=request_id, details={"missing_fields": missing})
    return get_request(request_id, db_path)


def _resource_preview(connection: sqlite3.Connection, request: sqlite3.Row, *, ignore_reservations: bool = False) -> dict[str, Any]:
    if request["status"] == "awaiting_input":
        raise DomainError("请先补充：" + "、".join(json.loads(request["missing_fields"])))
    start_at = f"{request['work_date']}T{request['start_time']}:00"
    end_at = f"{request['work_date']}T{request['end_time']}:00"
    requested_skill = str(request["required_skill"] or REQUIRED_SKILL).strip()
    required_skill = {"泵体检查": "pump_inspection", "电气检查": "electrical_inspection"}.get(requested_skill, requested_skill)
    workers = connection.execute(
        "SELECT w.id,w.name,w.role FROM workers w JOIN worker_skills s ON s.worker_id=w.id "
        "WHERE s.skill=? AND EXISTS (SELECT 1 FROM worker_availability a WHERE a.worker_id=w.id AND (a.work_date='*' OR a.work_date=?) AND a.start_time<=? AND a.end_time>=?) "
        "AND w.id NOT IN (SELECT resource_id FROM reservations WHERE resource_type='worker' AND status='active' AND start_at < ? AND end_at > ?) ORDER BY w.id",
        (required_skill, request["work_date"], request["start_time"], request["end_time"], end_at, start_at),
    ).fetchall()
    inventory_rows = connection.execute(
        "SELECT id,name,category,available_qty,unit FROM inventory_items WHERE id IN (?,?) ORDER BY id",
        REQUIRED_INVENTORY,
    ).fetchall()
    inventory = [dict(row) for row in inventory_rows]
    unavailable_items = [item for item in inventory if item["available_qty"] < 1]
    reasons: list[str] = []
    if not workers:
        reasons.append("没有可用人员")
    if unavailable_items:
        reasons.append("库存不足：" + "、".join(item["name"] for item in unavailable_items))
    return {
        "simulated": True,
        "request_id": request["id"],
        "workers": [dict(row) for row in workers],
        "inventory": inventory,
        "required_skill": required_skill,
        "required_inventory": list(REQUIRED_INVENTORY),
        "available": bool(workers) and not unavailable_items,
        "reasons": reasons,
        "start_at": start_at,
        "end_at": end_at,
    }


def preview_resources(request_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        return _resource_preview(connection, _request(connection, request_id))


def create_plan(request_id: str, db_path: str | Path | None = None, preview: dict[str, Any] | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    plan_id = _id("plan")
    failure_reason: str | None = None
    with transaction(db_path) as connection:
        request = _request(connection, request_id)
        existing = connection.execute("SELECT * FROM plans WHERE request_id=?", (request_id,)).fetchone()
        if existing is not None:
            plan_id = existing["id"]
        else:
            resource_preview = preview or _resource_preview(connection, request)
            if not resource_preview.get("available"):
                reason = "；".join(resource_preview.get("reasons") or ["当前没有可执行资源"])
                connection.execute("UPDATE inspection_requests SET status='failed',updated_at=? WHERE id=?", (now_utc(), request_id))
                _event(connection, event_type="plan_failed", actor="leader", request_id=request_id,
                       details={"reason": reason})
                failure_reason = reason
            else:
                worker_id = resource_preview["workers"][0]["id"]
                inventory_json = json.dumps([item["id"] for item in resource_preview["inventory"] if item["id"] in REQUIRED_INVENTORY], ensure_ascii=False)
                timestamp = now_utc()
                connection.execute(
                    "INSERT INTO plans(id,request_id,status,worker_id,inventory_json,reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (plan_id, request_id, "proposed", worker_id, inventory_json,
                     "按技能、时段和库存生成的模拟方案", timestamp, timestamp),
                )
                connection.execute("UPDATE inspection_requests SET status='proposed',updated_at=? WHERE id=?", (timestamp, request_id))
                _event(connection, event_type="plan_generated", actor="leader", request_id=request_id,
                       details={"plan_id": plan_id, "worker_id": worker_id, "inventory": json.loads(inventory_json)})
    if failure_reason:
        raise DomainError(failure_reason)
    return get_plan(plan_id, db_path)


def reserve_plan_resources(plan_id: str, db_path: str | Path | None = None, actor: str = "resource_partner") -> list[dict[str, Any]]:
    initialize_database(db_path)
    failure_reason: str | None = None
    reservation_rows: list[dict[str, Any]] = []
    with transaction(db_path) as connection:
        plan = _plan(connection, plan_id)
        if plan["status"] in {"cancelled", "completed"}:
            raise DomainError("方案已结束，不能接受延迟到达的资源预留。")
        order = connection.execute("SELECT status FROM work_orders WHERE plan_id=? LIMIT 1", (plan_id,)).fetchone()
        if order and order["status"] in {"completed", "failed", "cancelled"}:
            raise DomainError("工单已结束，不能接受延迟到达的资源预留。")
        request = _request(connection, plan["request_id"])
        if plan["status"] in {"confirmed", "confirming", "in_progress"}:
            rows = connection.execute(
                "SELECT * FROM reservations WHERE plan_id=? AND status='active'", (plan_id,)
            ).fetchall()
            # A duplicate confirmation may arrive while the first request is
            # between reserve and work-order creation.  Preserve the first
            # reservation set instead of marking the plan as conflicted.
            if rows or plan["status"] in {"confirmed", "in_progress"}:
                return [_row_payload(row) for row in rows]
        preview = _resource_preview(connection, request)
        if not preview["available"]:
            reason = "；".join(preview["reasons"] or ["资源已发生变化"])
            connection.execute("UPDATE plans SET status='failed',reason=?,updated_at=? WHERE id=?", (reason, now_utc(), plan_id))
            connection.execute("UPDATE inspection_requests SET status='failed',updated_at=? WHERE id=?", (now_utc(), request["id"]))
            _event(connection, event_type="resource_conflict", actor=actor, request_id=request["id"], details={"plan_id": plan_id, "reason": reason})
            failure_reason = reason
        else:
            selected_worker = plan["worker_id"]
            if selected_worker not in {worker["id"] for worker in preview["workers"]}:
                raise DomainError("原方案人员已经不可用，请重新生成方案。")
            inventory_ids = json.loads(plan["inventory_json"])
            inventory_map = {item["id"]: item for item in preview["inventory"]}
            if any(inventory_map.get(item_id, {}).get("available_qty", 0) < 1 for item_id in inventory_ids):
                raise DomainError("确认前库存已经变化，请重新生成方案。")
            start_at = f"{request['work_date']}T{request['start_time']}:00"
            end_at = f"{request['work_date']}T{request['end_time']}:00"
            created = now_utc()
            selected = [("worker", selected_worker, 1)] + [("inventory", item_id, 1) for item_id in inventory_ids]
            for resource_type, resource_id, quantity in selected:
                reservation_id = _id("reservation")
                connection.execute(
                    "INSERT INTO reservations(id,plan_id,request_id,resource_type,resource_id,quantity,status,start_at,end_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (reservation_id, plan_id, request["id"], resource_type, resource_id, quantity, "active", start_at, end_at, created),
                )
                if resource_type == "inventory":
                    connection.execute("UPDATE inventory_items SET available_qty=available_qty-? WHERE id=?", (quantity, resource_id))
                reservation_rows.append({"id": reservation_id, "resource_type": resource_type, "resource_id": resource_id, "quantity": quantity})
            connection.execute("UPDATE plans SET status='confirming',updated_at=? WHERE id=?", (created, plan_id))
            connection.execute("UPDATE inspection_requests SET status='confirming',updated_at=? WHERE id=?", (created, request["id"]))
            _event(connection, event_type="resource_reserved", actor=actor, request_id=request["id"], details={"plan_id": plan_id, "reservations": reservation_rows})
    if failure_reason:
        raise DomainError(failure_reason)
    return reservation_rows


def release_plan_resources(plan_id: str, db_path: str | Path | None = None, actor: str = "resource_partner") -> list[str]:
    initialize_database(db_path)
    released: list[str] = []
    with transaction(db_path) as connection:
        plan = _plan(connection, plan_id)
        # This check shares the write transaction with release and competes
        # atomically with work-order creation. A committed order keeps its
        # resources until the explicit cancel_work_order transaction cancels it.
        order = connection.execute("SELECT id FROM work_orders WHERE plan_id=? AND status!='cancelled' LIMIT 1", (plan_id,)).fetchone()
        if order is not None:
            raise DomainError("方案已有有效工单，须取消工单后才能释放资源。")
        rows = connection.execute("SELECT * FROM reservations WHERE plan_id=? AND status='active'", (plan_id,)).fetchall()
        for row in rows:
            connection.execute("UPDATE reservations SET status='released',released_at=? WHERE id=?", (now_utc(), row["id"]))
            if row["resource_type"] == "inventory":
                connection.execute("UPDATE inventory_items SET available_qty=available_qty+? WHERE id=?", (row["quantity"], row["resource_id"]))
            released.append(row["id"])
        # Fence late reserve/create messages even if their reservation has not
        # arrived yet. Both operations must observe the cancelled plan.
        if released or plan["status"] != "cancelled":
            connection.execute("UPDATE plans SET status='cancelled',updated_at=? WHERE id=?", (now_utc(), plan_id))
            connection.execute("UPDATE inspection_requests SET status='cancelled',updated_at=? WHERE id=?", (now_utc(), plan["request_id"]))
            _event(connection, event_type="resource_released", actor=actor, request_id=plan["request_id"], details={"plan_id": plan_id, "reservation_ids": released})
    return released


def create_work_order_for_plan(plan_id: str, idempotency_key: str, db_path: str | Path | None = None, actor: str = "work_order_partner", force_failure: bool = False) -> dict[str, Any]:
    initialize_database(db_path)
    if not idempotency_key.strip():
        raise DomainError("缺少幂等键。")
    failure_message: str | None = None
    response: dict[str, Any] | None = None
    with transaction(db_path) as connection:
        plan = _plan(connection, plan_id)
        request = _request(connection, plan["request_id"])
        existing_key = connection.execute("SELECT response_json FROM idempotency_keys WHERE key=?", (idempotency_key,)).fetchone()
        if existing_key is not None:
            cached = json.loads(existing_key["response_json"])
            cached_order = cached.get("work_order") or {}
            if cached_order.get("plan_id") not in (None, plan_id):
                raise DomainError("幂等键已经用于其他方案，不能跨任务复用。")
            return cached
        if plan["status"] not in {"confirming", "confirmed"}:
            raise DomainError("方案还没有完成资源预留。")
        if force_failure:
            _event(connection, event_type="work_order_failed", actor=actor, request_id=request["id"], details={"reason": "测试注入的工单 Partner 失败"})
            failure_message = "工单 Partner 创建失败（测试注入）。"
        else:
            existing_order = connection.execute("SELECT * FROM work_orders WHERE plan_id=?", (plan_id,)).fetchone()
            if existing_order is not None:
                response = {"simulated": True, "work_order": _row_payload(existing_order)}
                connection.execute("INSERT INTO idempotency_keys(key,operation,response_json,created_at) VALUES(?,?,?,?)", (idempotency_key, "create_work_order", json.dumps(response, ensure_ascii=False), now_utc()))
            else:
                work_order_id = _id("wo")
                number = "WO-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6].upper()
                created = now_utc()
                connection.execute("INSERT INTO work_orders(id,number,request_id,plan_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (work_order_id, number, request["id"], plan_id, "confirmed", created, created))
                connection.execute("UPDATE plans SET status='confirmed',work_order_id=?,updated_at=? WHERE id=?", (work_order_id, created, plan_id))
                connection.execute("UPDATE inspection_requests SET status='confirmed',updated_at=? WHERE id=?", (created, request["id"]))
                _event(connection, event_type="work_order_created", actor=actor, request_id=request["id"], work_order_id=work_order_id, details={"plan_id": plan_id, "number": number})
                response = {"simulated": True, "work_order": _row_payload(connection.execute("SELECT * FROM work_orders WHERE id=?", (work_order_id,)).fetchone())}
                connection.execute("INSERT INTO idempotency_keys(key,operation,response_json,created_at) VALUES(?,?,?,?)", (idempotency_key, "create_work_order", json.dumps(response, ensure_ascii=False), created))
    if failure_message:
        raise DomainError(failure_message)
    if response is None:
        raise DomainError("工单 Partner 没有生成结果。")
    return response


def update_work_order_status(work_order_id: str, status: str, db_path: str | Path | None = None, actor: str = "work_order_partner") -> dict[str, Any]:
    allowed = {"in_progress", "completed", "failed"}
    if status not in allowed:
        raise DomainError("不支持的工单状态。")
    initialize_database(db_path)
    with transaction(db_path) as connection:
        row = connection.execute("SELECT * FROM work_orders WHERE id=?", (work_order_id,)).fetchone()
        if row is None:
            raise DomainError("工单不存在。")
        if row["status"] == "cancelled":
            raise DomainError("已取消工单不能继续更新。")
        if row["status"] in {"completed", "failed"} and status != row["status"]:
            raise DomainError("已结束工单不能回退状态。")
        timestamp = now_utc()
        # Only active rows can be settled. BEGIN IMMEDIATE makes concurrent
        # completion/retry unable to return inventory more than once. This also
        # repairs an old completed order whose reservations remained active.
        if status in {"completed", "failed"}:
            reservations = connection.execute(
                "SELECT * FROM reservations WHERE plan_id=? AND status='active'", (row["plan_id"],)
            ).fetchall()
            released, consumed = [], []
            for reservation in reservations:
                item = None
                if reservation["resource_type"] == "inventory":
                    item = connection.execute("SELECT category FROM inventory_items WHERE id=?", (reservation["resource_id"],)).fetchone()
                    if item is None or item["category"] not in {"tool", "part"}:
                        raise DomainError("物品分类缺失，无法安全结算资源。")
                elif reservation["resource_type"] != "worker":
                    raise DomainError("未知资源类型，无法安全结算资源。")
                # Demo inventory is reusable for both tools and parts. A
                # completed or failed order must return every reserved item;
                # otherwise a normal demo run permanently makes the next plan
                # look short of stock (for example, the seal ring disappears).
                # Keep the consumed list in the event shape for compatibility,
                # but no longer consume inventory on closeout.
                connection.execute("UPDATE reservations SET status='released',released_at=? WHERE id=?", (timestamp, reservation["id"]))
                if item is not None:
                    connection.execute("UPDATE inventory_items SET available_qty=available_qty+? WHERE id=?", (reservation["quantity"], reservation["resource_id"]))
                released.append(reservation["id"])
            if reservations:
                _event(connection, event_type="work_order_resources_closed", actor=actor,
                       request_id=row["request_id"], work_order_id=work_order_id,
                       details={"status": status, "released_reservations": released, "consumed_reservations": consumed})
        connection.execute("UPDATE plans SET status=?,updated_at=? WHERE id=?", (status, timestamp, row["plan_id"]))
        connection.execute("UPDATE inspection_requests SET status=?,updated_at=? WHERE id=?", (status, timestamp, row["request_id"]))
        if row["status"] != status:
            connection.execute("UPDATE work_orders SET status=?,updated_at=? WHERE id=?", (status, timestamp, work_order_id))
            _event(connection, event_type="work_order_status_updated", actor=actor, request_id=row["request_id"], work_order_id=work_order_id, details={"status": status})
        return _row_payload(connection.execute("SELECT * FROM work_orders WHERE id=?", (work_order_id,)).fetchone())


def cancel_work_order(work_order_id: str, db_path: str | Path | None = None, actor: str = "leader") -> dict[str, Any]:
    initialize_database(db_path)
    with transaction(db_path) as connection:
        row = connection.execute("SELECT * FROM work_orders WHERE id=?", (work_order_id,)).fetchone()
        if row is None:
            raise DomainError("工单不存在。")
        if row["status"] == "cancelled":
            return _row_payload(row)
        if row["status"] == "completed":
            raise DomainError("已完成工单不能取消。")
        timestamp = now_utc()
        reservations = connection.execute("SELECT * FROM reservations WHERE plan_id=? AND status='active'", (row["plan_id"],)).fetchall()
        for reservation in reservations:
            connection.execute("UPDATE reservations SET status='released',released_at=? WHERE id=?", (timestamp, reservation["id"]))
            if reservation["resource_type"] == "inventory":
                connection.execute("UPDATE inventory_items SET available_qty=available_qty+? WHERE id=?", (reservation["quantity"], reservation["resource_id"]))
        connection.execute("UPDATE work_orders SET status='cancelled',updated_at=? WHERE id=?", (timestamp, work_order_id))
        connection.execute("UPDATE plans SET status='cancelled',updated_at=? WHERE id=?", (timestamp, row["plan_id"]))
        connection.execute("UPDATE inspection_requests SET status='cancelled',updated_at=? WHERE id=?", (timestamp, row["request_id"]))
        _event(connection, event_type="work_order_cancelled", actor=actor, request_id=row["request_id"], work_order_id=work_order_id, details={"released_reservations": [r["id"] for r in reservations]})
        return _row_payload(connection.execute("SELECT * FROM work_orders WHERE id=?", (work_order_id,)).fetchone())


def confirm_plan(plan_id: str, idempotency_key: str, db_path: str | Path | None = None,
                 *, force_failure: bool = False) -> dict[str, Any]:
    """Synchronous domain path used by unit tests; the web path delegates each step via AIP."""
    existing = None
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        row = connection.execute("SELECT response_json FROM idempotency_keys WHERE key=?", (idempotency_key,)).fetchone()
        existing = json.loads(row["response_json"]) if row else None
    if existing is not None:
        cached_order = existing.get("work_order") or {}
        if cached_order.get("plan_id") not in (None, get_plan(plan_id, db_path)["id"]):
            raise DomainError("幂等键已经用于其他方案，不能跨任务复用。")
        return existing
    reserve_plan_resources(plan_id, db_path)
    try:
        return create_work_order_for_plan(plan_id, idempotency_key, db_path, force_failure=force_failure)
    except Exception:
        release_plan_resources(plan_id, db_path)
        raise


def replan_request(request_id: str, db_path: str | Path | None = None,
                   actor: str = "leader", *, preview: dict[str, Any] | None = None) -> dict[str, Any]:
    """Regenerate only the affected plan after resources change.

    A confirmed or in-progress request is immutable.  Proposed/failed plans
    keep their identity while their version and selected worker are updated,
    so callers can safely refresh one request without duplicating work orders.
    """
    initialize_database(db_path)
    plan_id: str | None = None
    failure_reason: str | None = None
    with transaction(db_path) as connection:
        request = _request(connection, request_id)
        if connection.execute("SELECT 1 FROM work_orders WHERE request_id=?", (request_id,)).fetchone():
            raise DomainError("任务已有工单，不能覆盖原方案重新安排。")
        if request["status"] in {"confirmed", "in_progress", "completed", "cancelled"}:
            raise DomainError("当前任务状态不允许重新安排。")
        current = connection.execute("SELECT * FROM plans WHERE request_id=?", (request_id,)).fetchone()
        if current is not None and current["status"] not in {"proposed", "failed"}:
            raise DomainError("方案正在确认或已完成，不能重复重新安排。")
        preview = preview if preview is not None else _resource_preview(connection, request)
        if not preview.get("available"):
            reason = "；".join(preview.get("reasons") or ["当前没有可执行资源"])
            timestamp = now_utc()
            connection.execute("UPDATE inspection_requests SET status='failed',updated_at=? WHERE id=?", (timestamp, request_id))
            _event(connection, event_type="replan_failed", actor=actor, request_id=request_id,
                   details={"reason": reason})
            failure_reason = reason
        else:
            worker_id = preview["workers"][0]["id"]
            inventory_json = json.dumps(
                [item["id"] for item in preview["inventory"] if item["id"] in REQUIRED_INVENTORY],
                ensure_ascii=False,
            )
            timestamp = now_utc()
            if current is None:
                plan_id = _id("plan")
                version = 1
                connection.execute(
                    "INSERT INTO plans(id,request_id,status,version,worker_id,inventory_json,reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (plan_id, request_id, "proposed", version, worker_id, inventory_json,
                     "资源变化后生成的模拟方案", timestamp, timestamp),
                )
                event_type = "plan_generated"
            else:
                plan_id = current["id"]
                version = int(current["version"]) + 1
                connection.execute(
                    "UPDATE plans SET status='proposed',version=?,worker_id=?,inventory_json=?,reason=?,updated_at=? WHERE id=?",
                    (version, worker_id, inventory_json, "资源变化后重新生成的模拟方案", timestamp, plan_id),
                )
                event_type = "plan_replanned"
            connection.execute("UPDATE inspection_requests SET status='proposed',updated_at=? WHERE id=?", (timestamp, request_id))
            _event(connection, event_type=event_type, actor=actor, request_id=request_id,
                   details={"plan_id": plan_id, "version": version, "worker_id": worker_id,
                            "inventory": json.loads(inventory_json)})
    if failure_reason:
        raise DomainError(failure_reason)
    return get_plan(plan_id, db_path)


def recover_interrupted_state(db_path: str | Path | None = None,
                              actor: str = "recovery") -> dict[str, int]:
    """Reconcile interrupted plans and legacy terminal inventory closeouts."""
    initialize_database(db_path)
    compensated = 0
    reconciled = 0
    inventory_reconciled = 0
    with transaction(db_path) as connection:
        rows = connection.execute("SELECT * FROM plans WHERE status='confirming'").fetchall()
        for plan in rows:
            request_id = plan["request_id"]
            active = connection.execute(
                "SELECT * FROM reservations WHERE plan_id=? AND status='active'", (plan["id"],)
            ).fetchall()
            if plan["work_order_id"]:
                connection.execute("UPDATE plans SET status='confirmed',updated_at=? WHERE id=?", (now_utc(), plan["id"]))
                connection.execute("UPDATE inspection_requests SET status='confirmed',updated_at=? WHERE id=?", (now_utc(), request_id))
                _event(connection, event_type="recovery_reconciled", actor=actor, request_id=request_id,
                       work_order_id=plan["work_order_id"], details={"plan_id": plan["id"]})
                reconciled += 1
                continue
            released_ids: list[str] = []
            timestamp = now_utc()
            for reservation in active:
                connection.execute("UPDATE reservations SET status='released',released_at=? WHERE id=?", (timestamp, reservation["id"]))
                if reservation["resource_type"] == "inventory":
                    connection.execute("UPDATE inventory_items SET available_qty=available_qty+? WHERE id=?", (reservation["quantity"], reservation["resource_id"]))
                released_ids.append(reservation["id"])
            connection.execute("UPDATE plans SET status='cancelled',updated_at=? WHERE id=?", (timestamp, plan["id"]))
            connection.execute("UPDATE inspection_requests SET status='cancelled',updated_at=? WHERE id=?", (timestamp, request_id))
            _event(connection, event_type="recovery_compensated", actor=actor, request_id=request_id,
                   details={"plan_id": plan["id"], "reservation_ids": released_ids})
            compensated += 1
        # Older releases marked parts as ``consumed`` on completion. Demo
        # inventory is reusable, so repair only terminal orders and only once;
        # the reservation status is the idempotency fence for this migration.
        legacy_rows = connection.execute(
            "SELECT r.*, w.status AS work_order_status, w.id AS work_order_id "
            "FROM reservations r JOIN work_orders w ON w.plan_id=r.plan_id "
            "WHERE r.status='consumed' AND w.status IN ('completed','failed','cancelled')"
        ).fetchall()
        for reservation in legacy_rows:
            if reservation["resource_type"] != "inventory":
                raise DomainError("历史资源记录类型异常，无法安全恢复库存。")
            item = connection.execute(
                "SELECT category FROM inventory_items WHERE id=?", (reservation["resource_id"],)
            ).fetchone()
            if item is None or item["category"] not in {"tool", "part"}:
                raise DomainError("历史库存物品分类缺失，无法安全恢复库存。")
            timestamp = now_utc()
            connection.execute(
                "UPDATE reservations SET status='released',released_at=? WHERE id=? AND status='consumed'",
                (timestamp, reservation["id"]),
            )
            connection.execute(
                "UPDATE inventory_items SET available_qty=available_qty+? WHERE id=?",
                (reservation["quantity"], reservation["resource_id"]),
            )
            _event(
                connection,
                event_type="inventory_closeout_reconciled",
                actor=actor,
                request_id=reservation["request_id"],
                work_order_id=reservation["work_order_id"],
                details={"reservation_id": reservation["id"], "resource_id": reservation["resource_id"], "quantity": reservation["quantity"]},
            )
            inventory_reconciled += 1
    return {"compensated": compensated, "reconciled": reconciled, "inventory_reconciled": inventory_reconciled}


def get_request(request_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        row = _request(connection, request_id)
        result = _row_payload(row)
        result["pump"] = row_to_dict(connection.execute("SELECT * FROM pumps WHERE id=?", (row["pump_id"],)).fetchone())
        result["plan"] = get_plan_for_request(request_id, db_path)
        return result


def get_plan(plan_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        row = _plan(connection, plan_id)
        result = _row_payload(row)
        result["request"] = _row_payload(_request(connection, row["request_id"]))
        result["worker"] = row_to_dict(connection.execute("SELECT id,name,role FROM workers WHERE id=?", (row["worker_id"],)).fetchone())
        result["inventory"] = [dict(item) for item in connection.execute("SELECT id,name,category,unit FROM inventory_items WHERE id IN (?,?) ORDER BY id", tuple(json.loads(row["inventory_json"]))).fetchall()]
        result["work_order"] = get_work_order(row["work_order_id"], db_path) if row["work_order_id"] else None
        return result


def get_plan_for_request(request_id: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        row = connection.execute("SELECT id FROM plans WHERE request_id=?", (request_id,)).fetchone()
    return get_plan(row["id"], db_path) if row else None


def get_work_order(work_order_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        row = connection.execute("SELECT * FROM work_orders WHERE id=?", (work_order_id,)).fetchone()
        if row is None:
            raise DomainError("工单不存在。")
        result = _row_payload(row)
        result["request"] = _row_payload(_request(connection, row["request_id"]))
        result["reservations"] = [_row_payload(item) for item in connection.execute("SELECT * FROM reservations WHERE plan_id=? ORDER BY created_at", (row["plan_id"],)).fetchall()]
        return result


def list_pumps(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM pumps ORDER BY id").fetchall()]


def list_workers(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        return [dict(row) for row in connection.execute("SELECT w.*, group_concat(s.skill, ',') skills FROM workers w LEFT JOIN worker_skills s ON s.worker_id=w.id GROUP BY w.id ORDER BY w.id").fetchall()]


def list_inventory(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM inventory_items ORDER BY id").fetchall()]


def adjust_inventory_quantity(item_id: str, delta: int, db_path: str | Path | None = None,
                              *, actor: str = "operator") -> dict[str, Any]:
    """Adjust demo inventory by a signed quantity and record an audit event.

    The adjustment applies to available stock and the total stock together.
    Active reservations are never changed, and available stock cannot become
    negative.  This keeps the resource preview and reservation checks aligned
    with the number shown in the resource page.
    """
    initialize_database(db_path)
    if isinstance(delta, bool):
        raise DomainError("数量调整必须是整数。")
    try:
        delta = int(delta)
    except (TypeError, ValueError) as exc:
        raise DomainError("数量调整必须是整数。") from exc
    if delta == 0:
        raise DomainError("数量调整不能为 0。")
    with transaction(db_path) as connection:
        item = connection.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone()
        if item is None:
            raise DomainError("库存物品不存在。")
        active = connection.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM reservations WHERE resource_type='inventory' AND resource_id=? AND status='active'",
            (item_id,),
        ).fetchone()[0]
        available = int(item["available_qty"]) + delta
        total = int(item["total_qty"]) + delta
        if available < 0 or total < 0:
            raise DomainError("可用数量不能低于 0。")
        if total < int(active) + available:
            raise DomainError("不能减少已被活动预留占用的库存数量。")
        timestamp = now_utc()
        connection.execute(
            "UPDATE inventory_items SET total_qty=?,available_qty=? WHERE id=?",
            (total, available, item_id),
        )
        _event(
            connection,
            event_type="inventory_adjusted",
            actor=actor,
            details={"item_id": item_id, "delta": delta, "available_qty": available, "total_qty": total, "active_reserved": int(active)},
        )
        return dict(connection.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone())


def list_work_orders(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        rows = connection.execute("SELECT * FROM work_orders ORDER BY created_at DESC").fetchall()
    return [get_work_order(row["id"], db_path) for row in rows]


def list_events(request_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        rows = connection.execute("SELECT * FROM task_events WHERE request_id=? ORDER BY id", (request_id,)).fetchall()
        result = []
        for row in rows:
            item = _row_payload(row)
            item["details"] = item.pop("details_json", {})
            result.append(item)
        return result


def reset_database(db_path: str | Path | None = None) -> Path:
    path = database_path(db_path)
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    return initialize_database(path)

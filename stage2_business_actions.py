"""Shared business action dispatcher used by RPC and official MQ transports."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from stage2_domain import (
    DomainError,
    cancel_work_order,
    create_work_order_for_plan,
    get_work_order,
    preview_resources,
    release_plan_resources,
    reserve_plan_resources,
    update_work_order_status,
)


def dispatch_business_action(
    partner: str,
    action: str,
    payload: dict[str, Any],
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        if partner == "resource":
            if action == "query_resources":
                result = preview_resources(payload["request_id"], db_path)
            elif action == "reserve_resources":
                result = {"reservations": reserve_plan_resources(payload["plan_id"], db_path)}
            elif action == "release_resources":
                result = {"released_reservation_ids": release_plan_resources(payload["plan_id"], db_path)}
            else:
                raise DomainError("资源 Partner 不支持此 action。")
        elif partner == "workorder":
            if action == "create_work_order":
                result = create_work_order_for_plan(
                    payload["plan_id"], payload["idempotency_key"], db_path,
                    force_failure=bool(payload.get("force_failure", False)),
                )
            elif action == "get_work_order":
                result = {"work_order": get_work_order(payload["work_order_id"], db_path)}
            elif action == "update_work_order":
                result = {"work_order": update_work_order_status(payload["work_order_id"], payload["status"], db_path)}
            elif action == "cancel_work_order":
                result = {"work_order": cancel_work_order(payload["work_order_id"], db_path, actor="work_order_partner")}
            else:
                raise DomainError("工单 Partner 不支持此 action。")
        else:
            raise DomainError(f"未知业务 Partner：{partner}。")
        return {"simulated": True, "ok": True, "partner": partner, "action": action, "result": result}
    except (DomainError, KeyError, TypeError, ValueError) as exc:
        return {"simulated": True, "ok": False, "partner": partner, "action": action, "error": str(exc)}

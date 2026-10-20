"""Single source of truth for business and AIP task state translation."""
from __future__ import annotations

BUSINESS_TO_AIP = {
    "created": "accepted",
    "awaiting_input": "awaiting_input",
    "planned": "awaiting_completion",
    "awaiting_confirmation": "awaiting_completion",
    "confirming": "working",
    "reserved": "working",
    "work_order_created": "completed",
    "in_progress": "working",
    "completed": "completed",
    "cancelled": "cancelled",
    "failed": "failed",
    "compensating": "working",
    "recovery_required": "working",
}
AIP_TO_BUSINESS = {
    "accepted": "created",
    "working": "in_progress",
    "awaiting_input": "awaiting_input",
    "awaiting_completion": "awaiting_confirmation",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "rejected": "failed",
}


def map_business_to_aip(state: str) -> str:
    try:
        return BUSINESS_TO_AIP[str(state)]
    except KeyError as exc:
        raise ValueError(f"未知业务状态：{state}") from exc


def map_aip_to_business(state: str) -> str:
    try:
        return AIP_TO_BUSINESS[str(state)]
    except KeyError as exc:
        raise ValueError(f"未知 AIP 状态：{state}") from exc

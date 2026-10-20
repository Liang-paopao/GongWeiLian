"""Shared loopback and AIP response helpers for stage two Partners."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from acps_sdk.aip import Product, TaskCommand, TaskResult, TaskState, TextDataItem
from acps_sdk.aip.aip_rpc_server import DefaultHandlers, TaskManager

from local_log import record


def loopback_only(request: Request) -> bool:
    return request.client is not None and request.client.host in {"127.0.0.1", "::1"}


async def reject_non_loopback(request: Request, call_next):
    if not loopback_only(request):
        return JSONResponse({"error": "阶段二服务只允许本机回环访问。"}, status_code=403)
    return await call_next(request)


def extract_payload(command: TaskCommand) -> dict[str, Any]:
    texts = [item.text for item in command.dataItems or [] if isinstance(item, TextDataItem)]
    if len(texts) != 1:
        raise ValueError("AIP 请求必须包含一条 JSON 文本消息。")
    payload = json.loads(texts[0])
    if not isinstance(payload, dict):
        raise ValueError("AIP 请求 JSON 必须是对象。")
    return payload


def result_with_payload(command: TaskCommand, partner_id: str, payload: dict[str, Any], *, state: TaskState = TaskState.AwaitingCompletion) -> TaskResult:
    task = TaskManager.get_task(command.taskId) if command.taskId else None
    if task is None:
        task = TaskManager.create_task(command, initial_state=state)
    task.senderId = partner_id
    TaskManager.set_products(task.taskId, [Product(
        id=f"stage2-{task.taskId}", name="stage2_business_result",
        dataItems=[TextDataItem(text=json.dumps(payload, ensure_ascii=False))],
    )])
    return task


async def complete_with_identity(command: TaskCommand, task: TaskResult, partner_id: str) -> TaskResult:
    result = await DefaultHandlers.complete(command, task)
    result.senderId = partner_id
    return result


def failure_payload(exc: Exception) -> dict[str, Any]:
    return {"simulated": True, "ok": False, "error": str(exc)}


def record_partner(actor: str, event: str, command: TaskCommand, details: dict[str, Any]) -> None:
    record(actor, event, {"task_id": command.taskId, "session_id": command.sessionId, **details})

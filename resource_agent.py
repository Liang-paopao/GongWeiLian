"""First-step Partner, restricted to loopback; NO real AIC, certificates or discovery."""
from __future__ import annotations
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from acps_sdk.aip import Product, TaskCommand, TaskResult, TaskState, TextDataItem
from acps_sdk.aip.aip_rpc_server import CommandHandlers, TaskManager, add_aip_rpc_router
from business import lookup_staff
from local_log import record

LOCAL_RESOURCE_ID = "local-demo-gongwei-resource"
app = FastAPI(title="Gongwei local-only resource-query exercise")


@app.middleware("http")
async def loopback_only(request: Request, call_next):
    # This exercise intentionally lacks mTLS. Never expose it to a LAN or Internet.
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        return JSONResponse({"error": "Local-loopback exercise only."}, status_code=403)
    return await call_next(request)


def identify(task: TaskResult) -> TaskResult:
    task.senderId = LOCAL_RESOURCE_ID
    return task


async def handle_start(command: TaskCommand, previous: TaskResult | None) -> TaskResult:
    if previous is not None:
        return identify(previous)
    try:
        texts = [item.text for item in command.dataItems or [] if isinstance(item, TextDataItem)]
        if len(texts) != 1:
            raise ValueError("请提供一条包含查询字段的消息。")
        result = lookup_staff(json.loads(texts[0]))
    except (ValueError, KeyError, TypeError) as exc:
        task = TaskManager.create_task(command, initial_state=TaskState.Rejected,
                                      data_items=[TextDataItem(text=str(exc))])
        record("resource", "rejected", {"task_id": command.taskId, "reason": str(exc)})
        return identify(task)
    task = TaskManager.create_task(command, initial_state=TaskState.AwaitingCompletion)
    TaskManager.set_products(task.taskId, [Product(
        id=f"lookup-{task.taskId}", name="simulated_staff_lookup",
        dataItems=[TextDataItem(text=json.dumps(result, ensure_ascii=False))],
    )])
    record("resource", "lookup_returned", {"task_id": task.taskId, "result": result})
    return identify(task)


# v2.2.0 enables certificate identity binding by default. Only this LOOPBACK
# exercise turns it off; public/platform deployment MUST implement real identity,
# certificate verification, authorization and reachable endpoints separately.
add_aip_rpc_router(app, "/rpc", CommandHandlers(on_start=handle_start),
                   local_aic=LOCAL_RESOURCE_ID, identity_binding_enabled=False)


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", "mode": "local_simulation_only", "platform_verified": False}

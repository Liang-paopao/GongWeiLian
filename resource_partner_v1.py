"""Stage two Resource Partner: real SQLite resource queries and reservations."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from acps_sdk.aip import TaskCommand, TaskResult, TaskState
from acps_sdk.aip.aip_rpc_server import CommandHandlers, add_aip_rpc_router

from stage2_business_actions import dispatch_business_action
from platform_runtime import external_runtime_errors, runtime_mode
from stage2_partner_common import (
    complete_with_identity,
    extract_payload,
    failure_payload,
    record_partner,
    reject_non_loopback,
    result_with_payload,
)

RESOURCE_PARTNER_ID = "stage2-gongwei-resource"
app = FastAPI(title="工维联阶段二资源 Partner")
app.middleware("http")(reject_non_loopback)


async def handle_start(command: TaskCommand, previous: TaskResult | None) -> TaskResult:
    if previous is not None:
        previous.senderId = RESOURCE_PARTNER_ID
        return previous
    try:
        payload = extract_payload(command)
        action = payload.get("action")
        response = dispatch_business_action("resource", action, payload)
        if not response["ok"]:
            raise ValueError(response["error"])
        record_partner("resource_v1", "aip_result", command, {"action": action, "response": response})
        return result_with_payload(command, RESOURCE_PARTNER_ID, response)
    except (KeyError, TypeError, ValueError) as exc:
        response = failure_payload(exc)
        record_partner("resource_v1", "aip_error", command, {"response": response})
        return result_with_payload(command, RESOURCE_PARTNER_ID, response, state=TaskState.Failed)


async def handle_complete(command: TaskCommand, task: TaskResult) -> TaskResult:
    return await complete_with_identity(command, task, RESOURCE_PARTNER_ID)


add_aip_rpc_router(
    app, "/rpc", CommandHandlers(on_start=handle_start, on_complete=handle_complete),
    local_aic=RESOURCE_PARTNER_ID, identity_binding_enabled=False,
)


@app.get("/health")
async def health() -> dict[str, object]:
    errors = external_runtime_errors()
    mode = runtime_mode()
    return {"status": "ok" if not errors else "pending", "partner": RESOURCE_PARTNER_ID, "mode": "local_simulation_only" if mode == "local" else "external", "runtime_mode": mode, "external_ready": not errors, "configuration_errors": errors, "platform_verified": False}

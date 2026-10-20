"""Stage four Sound Analysis Partner using the official ACPs SDK/AIP router."""
from __future__ import annotations

from fastapi import FastAPI
from acps_sdk.aip import TaskCommand, TaskResult, TaskState
from acps_sdk.aip.aip_rpc_server import CommandHandlers, add_aip_rpc_router

from audio_service import analyze_audio_payload, audio_enabled
from platform_runtime import external_runtime_errors, runtime_mode
from stage2_partner_common import complete_with_identity, extract_payload, failure_payload, record_partner, reject_non_loopback, result_with_payload

AUDIO_PARTNER_ID = "stage2-gongwei-audio"
app = FastAPI(title="工维联阶段四声音分析 Partner")
app.middleware("http")(reject_non_loopback)


async def handle_start(command: TaskCommand, previous: TaskResult | None) -> TaskResult:
    if previous is not None:
        previous.senderId = AUDIO_PARTNER_ID
        return previous
    try:
        payload = extract_payload(command)
        if payload.get("action") != "analyze_audio":
            raise ValueError("声音分析 Partner 不支持此 action。")
        result = analyze_audio_payload(payload)
        response = {"simulated": True, "ok": True, "action": "analyze_audio", "result": result}
        record_partner("audio_v1", "aip_result", command, {"action": "analyze_audio", "response": response})
        return result_with_payload(command, AUDIO_PARTNER_ID, response)
    except (ValueError, TypeError, KeyError) as exc:
        response = failure_payload(exc)
        record_partner("audio_v1", "aip_error", command, {"response": response})
        return result_with_payload(command, AUDIO_PARTNER_ID, response, state=TaskState.Failed)


async def handle_complete(command: TaskCommand, task: TaskResult) -> TaskResult:
    return await complete_with_identity(command, task, AUDIO_PARTNER_ID)


add_aip_rpc_router(app, "/rpc", CommandHandlers(on_start=handle_start, on_complete=handle_complete), local_aic=AUDIO_PARTNER_ID, identity_binding_enabled=False)


@app.get("/health")
async def health() -> dict[str, object]:
    from audio_service import get_audio_detector, get_detector_backend_name
    detector = get_audio_detector()
    errors = external_runtime_errors()
    mode = runtime_mode()
    return {
        "status": "ok" if not errors else "pending", "partner": AUDIO_PARTNER_ID,
        "detector_backend": get_detector_backend_name(),
        "audio_enabled": audio_enabled(),
        "model_version": detector.model_version,
        "model_role": "auxiliary_smoke_baseline",
        "verdicts": ["未发现明显异常", "疑似异常"],
        "mode": "local_simulation_only" if mode == "local" else "external",
        "runtime_mode": mode, "external_ready": not errors, "configuration_errors": errors,
        "platform_verified": False,
    }

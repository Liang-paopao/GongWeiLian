"""Leader-side AIP clients for the stage two Partners."""
from __future__ import annotations

import json
import os
import ssl
import time
import uuid
from typing import Any

from acps_sdk.aip import AipRpcClient, TaskState, TextDataItem

from local_log import record
from platform_runtime import external_rpc_url, runtime_mode
from transport_mode import get_transport_mode, require_https_configuration

LEADER_ID = "stage2-gongwei-leader"
RESOURCE_PARTNER_ID = "stage2-gongwei-resource"
WORK_ORDER_PARTNER_ID = "stage2-gongwei-work-order"
AUDIO_PARTNER_ID = "stage2-gongwei-audio"


class PartnerCallError(RuntimeError):
    def __init__(self, partner: str, action: str, message: str):
        super().__init__(message)
        self.partner = partner
        self.action = action


def partner_url(kind: str) -> str:
    if get_transport_mode() == "platform_https_rpc" and kind in {"resource", "workorder"}:
        config = require_https_configuration()
        key = {"resource": "resource_rpc_url", "workorder": "workorder_rpc_url"}.get(kind)
        if key is None:
            raise ValueError(f"未知 Partner 类型：{kind}")
        return config[key]
    if runtime_mode() == "external":
        env_name = {
            "resource": "GONGWEI_EXTERNAL_RESOURCE_RPC_URL",
            "audio": "GONGWEI_EXTERNAL_AUDIO_RPC_URL",
            "workorder": "GONGWEI_EXTERNAL_WORKORDER_RPC_URL",
        }.get(kind)
        if env_name is None:
            raise ValueError(f"未知 Partner 类型：{kind}")
        configured = os.environ.get(env_name)
        if not configured:
            raise ValueError(f"外部运行模式缺少 {env_name}。")
        return external_rpc_url(configured)
    if kind == "resource":
        port = os.environ.get("GONGWEI_STAGE2_RESOURCE_PORT", "18012")
    elif kind == "audio":
        port = os.environ.get("GONGWEI_STAGE2_AUDIO_PORT", "18014")
    else:
        port = os.environ.get("GONGWEI_STAGE2_WORKORDER_PORT", "18013")
    return f"http://127.0.0.1:{port}/rpc"


def _https_ssl_context() -> ssl.SSLContext:
    config = require_https_configuration()
    context = ssl.create_default_context(cafile=config["trust_bundle_file"])
    context.load_cert_chain(config["client_cert_file"], config["private_key_file"])
    return context


def _payload(task: Any) -> dict[str, Any]:
    values = [item.text for product in task.products or [] for item in product.dataItems or [] if isinstance(item, TextDataItem)]
    if len(values) != 1:
        raise PartnerCallError("unknown", "unknown", "Partner 没有返回唯一业务结果。")
    try:
        return json.loads(values[0])
    except json.JSONDecodeError as exc:
        raise PartnerCallError("unknown", "unknown", "Partner 返回内容不是有效 JSON。") from exc


_MQ_COORDINATOR: Any | None = None


async def _call_partner_local_rpc(kind: str, action: str, payload: dict[str, Any], *, session_id: str | None = None, task_id: str | None = None) -> dict[str, Any]:
    partner_id = {"resource": RESOURCE_PARTNER_ID, "workorder": WORK_ORDER_PARTNER_ID, "audio": AUDIO_PARTNER_ID}.get(kind)
    if partner_id is None:
        raise PartnerCallError(kind, action, "未知 Partner 类型。")
    started = time.perf_counter()
    task_id = task_id or f"stage2-{kind}-{uuid.uuid4()}"
    session_id = session_id or f"stage2-session-{uuid.uuid4()}"
    formal_https = get_transport_mode() == "platform_https_rpc" and kind in {"resource", "workorder"}
    https_config = require_https_configuration() if formal_https else None
    client = AipRpcClient(
        partner_url=partner_url(kind),
        leader_id=https_config["leader_aic"] if https_config else LEADER_ID,
        ssl_context=_https_ssl_context() if formal_https else None,
        expected_partner_aic=https_config.get({"resource": "resource_aic", "workorder": "workorder_aic", "audio": "resource_aic"}[kind], partner_id) if https_config else partner_id,
        callee_aic=https_config.get({"resource": "resource_aic", "workorder": "workorder_aic", "audio": "resource_aic"}[kind], "") if https_config else "",
        identity_binding_enabled=formal_https,
    )
    request_details = {"partner": kind, "partner_id": partner_id, "action": action, "payload": payload, "task_id": task_id}
    record("stage2_leader", "aip_request", request_details)
    try:
        task = await client.start_task(session_id=session_id, task_id=task_id, user_input=json.dumps({"action": action, **payload}, ensure_ascii=False))
        result = _payload(task)
        if task.status.state == TaskState.Failed or not result.get("ok", False):
            message = result.get("error", "Partner 返回失败。")
            raise PartnerCallError(kind, action, message)
        final = await client.complete_task(task_id=task_id, session_id=session_id)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        record("stage2_leader", "aip_response", {**request_details, "duration_ms": duration_ms, "status": final.status.state.value, "result": result})
        return result
    except PartnerCallError:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        record("stage2_leader", "aip_error", {**request_details, "duration_ms": duration_ms, "error": "Partner 业务调用失败"})
        raise
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        record("stage2_leader", "aip_error", {**request_details, "duration_ms": duration_ms, "error": type(exc).__name__})
        raise PartnerCallError(kind, action, "Partner 暂时不可用，请检查服务窗口。") from exc
    finally:
        await client.close()


def _mq_coordinator() -> Any:
    global _MQ_COORDINATOR
    if _MQ_COORDINATOR is None:
        from mq_group_transport import MqBusinessCoordinator

        _MQ_COORDINATOR = MqBusinessCoordinator()
    return _MQ_COORDINATOR


async def call_partner(kind: str, action: str, payload: dict[str, Any], *, session_id: str | None = None, task_id: str | None = None) -> dict[str, Any]:
    """Call a Partner through the selected transport.

    The business payload and response contract stay identical.  Audio remains
    a local pluggable helper while the resource and work-order Partners use
    the official Group/Inbox route when that mode is selected.
    """
    mode = get_transport_mode()
    if mode == "platform_mq_inbox" and kind in {"resource", "workorder"}:
        started = time.perf_counter()
        task_id = task_id or f"gongwei-mq-{kind}-{uuid.uuid4()}"
        details = {"partner": kind, "action": action, "payload": payload, "task_id": task_id, "transport": mode}
        record("stage2_leader", "mq_request", details)
        try:
            result = await _mq_coordinator().call(
                kind,
                action,
                payload,
                session_id=session_id or f"session-{task_id}",
                task_id=task_id,
            )
            record(
                "stage2_leader",
                "mq_response",
                {**details, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "result": result},
            )
            if not result.get("ok", False):
                raise PartnerCallError(kind, action, result.get("error", "MQ Partner 返回失败。"))
            return result
        except PartnerCallError:
            raise
        except Exception as exc:
            record(
                "stage2_leader",
                "mq_error",
                {**details, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "error": type(exc).__name__},
            )
            raise PartnerCallError(kind, action, "MQ Partner 暂时不可用，请检查官方 Inbox 配置和服务窗口。") from exc
    return await _call_partner_local_rpc(kind, action, payload, session_id=session_id, task_id=task_id)

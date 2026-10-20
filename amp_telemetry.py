"""Opt-in local AMP protocol metadata using official SDK 2.2.0 emitters.

No Kafka client or network uploader is present. Business dataItems, products,
headers, exception text and arbitrary attributes are never stored. The caller
must attach the RPC wrapper after SDK peer identity verification and bind MQ
messages only from the SDK's validated TaskCommand/TaskResult callback.

SDK MQ taps currently use sessionId as correlation_id and omit taskId from
receive bodies. Buffer only sanitized receive metadata until that callback
binds the actual taskId; never invent it or substitute sessionId. Each delivery
uses its receive trace/span and the SDK callback's task-local context. ACK/NACK
must match that trace and parent span; missing tracing never falls back to an
old messageId. Delivery caches are bounded and expire. Files are separate from heartbeat files
and are excluded by the heartbeat-only Forwarder's existing whitelist.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import re
from time import monotonic
from typing import Any, Awaitable, Callable

from acps_sdk.aip import TaskCommand, TaskResult
from acps_sdk.aip.access_status import status_from_rpc_response
from acps_sdk.aip.aip_rpc_model import RpcRequest, RpcResponse
from acps_sdk.amp import (
    AccessBody, AccessEmitter, AccessParticipant, AccessRequest, AccessResponse,
    ErrorInfo, MessageBody, MessageDestination, MessageEmitter, MessageSettlement,
)
from acps_sdk.amp.trace_context import TraceContext, new_span_id, parse_traceparent

logger = logging.getLogger(__name__)
_incoming_trace_context: ContextVar[TraceContext | None] = ContextVar(
    "gongwei_incoming_trace_context", default=None
)
_PROTOCOL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_MSG_TYPES = frozenset({"task-command", "task-result"})
_OPERATIONS = {"send": "publish", "receive": "deliver", "ack": "basic.ack",
               "nack": "basic.nack", "reject": "basic.reject", "timeout": "basic.timeout",
               "dead_letter": "basic.dead_letter"}


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and _PROTOCOL_ID.fullmatch(value) is not None


def _tracing(values: dict[str, Any]) -> dict[str, str]:
    result = {}
    for key, size in (("trace_id", 32), ("span_id", 16), ("parent_span_id", 16)):
        value = values.get(key)
        if isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{size}}}", value) and int(value, 16):
            result[key] = value
    return result


@dataclass
class _PendingReceive:
    body: MessageBody
    group_id: str
    sender_id: str
    trace: dict[str, str]
    created_at: float


@dataclass
class _TaskBinding:
    task_id: str
    group_id: str
    sender_id: str
    created_at: float


@dataclass(frozen=True)
class _DeliveryKey:
    exchange: str
    message_id: str
    trace_id: str | None
    receive_span_id: str | None
    # Missing tracing may still produce a validated receive, but never a
    # settlement binding. This opaque local token is never written to AMP.
    local_token: object | None = None


class TaskMessageEmitter:
    """Duck-typed SDK emitter preserving real wire events and task identity."""

    max_pending = 256
    max_bindings = 4096
    retention_seconds = 120

    def __init__(self, emitter: MessageEmitter):
        self._emitter = emitter
        self._pending: OrderedDict[_DeliveryKey, _PendingReceive] = OrderedDict()
        self._bindings: OrderedDict[_DeliveryKey, _TaskBinding] = OrderedDict()
        self._current_delivery: ContextVar[_DeliveryKey | None] = ContextVar("amp_current_delivery", default=None)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def _prune(self) -> None:
        now = monotonic()
        for store, limit in ((self._pending, self.max_pending), (self._bindings, self.max_bindings)):
            for key in [key for key, value in store.items() if now - value.created_at > self.retention_seconds]:
                store.pop(key, None)
            while len(store) > limit:
                store.popitem(last=False)

    @staticmethod
    def _safe_body(body: MessageBody) -> MessageBody:
        attributes = {}
        msg_type = (body.attributes or {}).get("msgType")
        if msg_type in _MSG_TYPES:
            attributes["msgType"] = msg_type
        settlement = None
        if body.settlement is not None and body.settlement.latency_ms is not None:
            settlement = MessageSettlement(latency_ms=body.settlement.latency_ms)
        return MessageBody(
            event_type=body.event_type, operation_name=_OPERATIONS[body.event_type],
            system=body.system, destination=MessageDestination(
                name=body.destination.name, kind=body.destination.kind,
                virtual_host=body.destination.virtual_host),
            subscription_name=body.subscription_name,
            message_id=body.message_id, payload_size_bytes=body.payload_size_bytes,
            delivery_attempt=body.delivery_attempt, settlement=settlement,
            attributes=attributes or None,
        )

    async def _write(self, body: MessageBody, task_id: str, trace: dict[str, str]) -> None:
        body.attributes = {**(body.attributes or {}), "taskId": task_id}
        try:
            await self._emitter.emit(body, correlation_id=task_id, **trace)
        except Exception as exc:
            # Do not echo exception strings, which may contain transport secrets.
            logger.warning("event=amp_metadata_write_failed error_type=%s", type(exc).__name__)

    async def emit(self, body: MessageBody, **trace_kwargs: Any) -> None:
        self._prune()
        if isinstance(body, MessageBody) and body.event_type == "receive":
            self._current_delivery.set(None)
        if not isinstance(body, MessageBody) or body.system != "rabbitmq" or not _valid_id(body.message_id):
            return
        # These are SDK exchange/queue names, never a credential-bearing URL.
        if not _valid_id(body.destination.name) or (body.subscription_name is not None and not _valid_id(body.subscription_name)):
            return
        attributes = body.attributes or {}
        safe = self._safe_body(body)
        trace = _tracing(trace_kwargs)
        if body.event_type == "send":
            task_id = attributes.get("taskId")
            if _valid_id(task_id) and attributes.get("msgType") in _MSG_TYPES:
                await self._write(safe, task_id, trace)
        elif body.event_type == "receive":
            complete_trace = "trace_id" in trace and "span_id" in trace
            key = _DeliveryKey(body.destination.name, body.message_id, trace.get("trace_id"),
                               trace.get("span_id"), None if complete_trace else object())
            # Even repeated trace/span input starts a new validation attempt;
            # an invalid new model must never inherit a previous settlement.
            self._bindings.pop(key, None)
            group_id, sender_id = attributes.get("groupId"), attributes.get("senderId")
            if _valid_id(group_id) and _valid_id(sender_id) and attributes.get("msgType") in _MSG_TYPES:
                self._current_delivery.set(key)
                self._pending[key] = _PendingReceive(safe, group_id, sender_id, trace, monotonic())
                self._pending.move_to_end(key)
                self._prune()
        else:
            # SDK settlement span is a child of the exact receive span. ID-only
            # fallback cannot identify a delivery and is deliberately omitted.
            if "trace_id" not in trace or "parent_span_id" not in trace:
                return
            key = _DeliveryKey(body.destination.name, body.message_id, trace["trace_id"], trace["parent_span_id"])
            self._pending.pop(key, None)  # A model-validation failure has no binding.
            binding = self._bindings.pop(key, None)
            if self._current_delivery.get() == key:
                self._current_delivery.set(None)
            if binding is not None:
                await self._write(safe, binding.task_id, trace)

    async def bind_incoming(self, message: TaskCommand | TaskResult) -> None:
        """Called after SDK mTLS identity binding and message-model validation."""
        self._prune()
        key = self._current_delivery.get()
        self._current_delivery.set(None)
        if not isinstance(message, (TaskCommand, TaskResult)):
            return
        if not all(_valid_id(value) for value in (message.id, message.taskId, message.groupId, message.senderId)):
            return
        pending = self._pending.get(key) if key is not None else None
        if pending is None or key.message_id != message.id or pending.group_id != message.groupId or pending.sender_id != message.senderId:
            return
        self._pending.pop(key, None)
        if key.trace_id is not None and key.receive_span_id is not None and key.local_token is None:
            self._bindings[key] = _TaskBinding(message.taskId, message.groupId, message.senderId, monotonic())
            self._bindings.move_to_end(key)
            self._prune()
        await self._write(pending.body, message.taskId, pending.trace)


class AmpTelemetry:
    """Local-only metadata collectors for one already validated agent identity."""

    def __init__(self, *, role: str, aic: str, log_dir: Path):
        if not _valid_id(aic) or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", role):
            raise ValueError("AMP metadata requires a validated identity and service role")
        self.aic, self.role = aic, role
        identity = hashlib.sha256(aic.encode("utf-8")).hexdigest()
        self.access_file = Path(log_dir) / f"amp_access_{role}_{identity}.jsonl"
        self.message_file = Path(log_dir) / f"amp_message_{role}_{identity}.jsonl"
        self._access = AccessEmitter(self.access_file, aic=aic)
        self.message_emitter = TaskMessageEmitter(MessageEmitter(self.message_file, aic=aic))

    async def bind_incoming(self, message: TaskCommand | TaskResult) -> None:
        await self.message_emitter.bind_incoming(message)

    def wrap_rpc_dispatch(self, dispatch: Callable[[RpcRequest], Awaitable[RpcResponse]]):
        """Wrap dispatch_request passed to authenticated SDK handle_rpc_request.

        This is a callee Access event. It cannot create the remote caller's
        Access event; the platform caller must supply its own matching record.
        """
        async def observed(request: RpcRequest) -> RpcResponse:
            command = request.params.command
            started = monotonic()
            # The official RPC client sends W3C traceparent when its Access
            # emitter is enabled. Preserve that trace and make this callee a
            # child span; without this, a valid caller/callee pair loses its
            # distributed-trace link at the ASGI boundary.
            incoming = _incoming_trace_context.get()
            trace = {"trace_id": incoming.trace_id,
                     "span_id": new_span_id(),
                     "parent_span_id": incoming.span_id} if incoming else {}
            response, status, error_code = None, 500, "DISPATCH_EXCEPTION"
            try:
                response = await dispatch(request)
                status = status_from_rpc_response(response)
                error_code = response.error.code if response.error is not None else None
                return response
            except asyncio.CancelledError:
                status, error_code = 499, "DISPATCH_CANCELED"
                raise
            finally:
                task_id = command.taskId or (response.result.taskId if response and response.result else None)
                if _valid_id(task_id) and _valid_id(command.senderId):
                    body = AccessBody(
                        duration_ms=max(0.0, (monotonic() - started) * 1000),
                        request=AccessRequest(method=command.command.value, url="/rpc", route="/rpc"),
                        response=AccessResponse(statusCode=status),
                        caller=AccessParticipant(aic=command.senderId),
                        callee=AccessParticipant(aic=self.aic, serviceName=f"gongwei-{self.role}"),
                        error=ErrorInfo(code=error_code) if error_code is not None else None,
                    )
                    try:
                        await self._access.emit(body, correlation_id=task_id, **trace)
                    except Exception as exc:
                        logger.warning("event=amp_metadata_write_failed error_type=%s", type(exc).__name__)
        return observed


def set_incoming_traceparent(value: str | None):
    """Set the request-local trace context and return a reset token.

    This tiny adapter keeps Starlette/ASGI concerns out of the telemetry
    collector while allowing the authenticated RPC route to preserve the
    official SDK's traceparent header.
    """
    return _incoming_trace_context.set(parse_traceparent(value))


def reset_incoming_traceparent(token) -> None:
    _incoming_trace_context.reset(token)


def telemetry_from_environment(*, role: str, aic: str) -> AmpTelemetry | None:
    """Enable only local collection; this setting never enables transmission."""
    if os.environ.get("GONGWEI_AMP_METADATA_ENABLED") != "1":
        return None
    from amp_runtime import runtime_log_dir
    directory = Path(os.environ.get("GONGWEI_AMP_LOG_DIR") or runtime_log_dir() / "amp")
    return AmpTelemetry(role=role, aic=aic, log_dir=directory)

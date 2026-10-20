"""Official ACPs v2.2.0 Group/Inbox transport adapter.

Only the SDK owns the AMQP wire format.  This module binds the existing
SQLite business actions to SDK callbacks and keeps a small in-memory replay
guard for a running process; the durable work-order/idempotency tables remain
the source of truth across restarts.
"""
from __future__ import annotations

import json
import logging
import asyncio
import os
import ssl
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any, Awaitable, Callable

from acps_sdk.aip import (
    ACSObject,
    GroupLeader,
    GroupPartnerMqClient,
    InboxGroupInvitation,
    Product,
    TaskCommand,
    TaskCommandType,
    TextDataItem,
    TaskState,
)

from stage2_business_actions import dispatch_business_action
from transport_mode import require_mq_configuration
from mq_partner_runtime import OfficialMqPartnerRuntime
from amp_telemetry import AmpTelemetry, telemetry_from_environment
logger = logging.getLogger(__name__)


def _amqp_endpoint(value: str) -> dict[str, str]:
    return {"url": value, "transport": "AMQP"}


def _env_any(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


class OfficialMqGroupLeaderAdapter:
    """Thin wrapper around the official high-level ``GroupLeader``."""

    def __init__(self, *, leader_aic: str, rabbitmq_config: dict[str, Any] | None = None,
                 telemetry: AmpTelemetry | None = None):
        self.leader_aic = leader_aic
        self.rabbitmq_config = dict(rabbitmq_config or {})
        ssl_context = self.rabbitmq_config.pop("ssl_context", None)
        self.telemetry = telemetry or telemetry_from_environment(role="leader_mq", aic=leader_aic)
        amp_kwargs = {"message_emitter": self.telemetry.message_emitter} if self.telemetry else {}
        self.group_leader = GroupLeader(
            leader_aic=leader_aic,
            rabbitmq_config=self.rabbitmq_config,
            ssl_context=ssl_context,
            **amp_kwargs,
        )

    async def create_group_and_invite(
        self, *, session_id: str, partners: list[dict[str, Any]]
    ) -> dict[str, Any]:
        initial = [ACSObject(aic=item["aic"]) for item in partners]
        await self.group_leader.create_group_session(session_id=session_id, initial_partners=initial)
        if self.telemetry is not None:
            # SDK's tap runs after peer binding but before typed parsing. The
            # original high-level callback then receives the validated model.
            # Bind its real taskId before continuing unchanged SDK processing.
            session_client = self.group_leader.group_sessions[session_id].leader_mq_client
            dispatch = self.group_leader._handle_group_message  # pinned SDK 2.2.0

            async def observed(message):
                await self.telemetry.bind_incoming(message)
                await dispatch(message)

            session_client.set_message_handler(observed)
        invited: list[str] = []
        for item in partners:
            partner_data = {
                "endPoints": [_amqp_endpoint(item["amqp_endpoint"])],
                "auth_service_url": item.get("auth_service_url") or self.rabbitmq_config.get("auth_service_url"),
            }
            await self.group_leader.invite_partner(
                session_id=session_id,
                partner_acs=ACSObject(aic=item["aic"]),
                partner_rpc_url=None,
                partner_acs_data=partner_data,
            )
            invited.append(item["aic"])
        return {"session_id": session_id, "group_id": self.group_leader.group_sessions[session_id].group_id, "invited": invited}

    async def start_task(self, *, session_id: str, task_content: str, target_partners: list[str], task_id: str | None = None) -> str:
        return await self.group_leader.start_task(
            session_id=session_id,
            task_content=task_content,
            target_partners=target_partners,
            task_id=task_id,
        )

    async def close(self) -> None:
        await self.group_leader.close()


class OfficialMqPartnerHandler:
    """Map SDK TaskCommand callbacks to the unchanged SQLite action layer."""

    def __init__(self, partner: str, client: Any, *, db_path: str | Path | None = None):
        self.partner = partner
        self.client = client
        self.db_path = db_path
        self._processed: dict[tuple[str, str, str], dict[str, Any]] = {}

    @staticmethod
    def _payload(command: TaskCommand) -> dict[str, Any]:
        items = getattr(command, "dataItems", None) or []
        # The official SDK may attach protocol text and the business JSON as
        # separate DataItems.  Consume the single object-shaped JSON item and
        # leave protocol text untouched; do not rely on item ordering.
        for item in items:
            value = getattr(item, "text", None)
            if not isinstance(value, str):
                continue
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise ValueError("MQ task command 必须包含一条 JSON 对象数据。")

    async def handle(self, command: TaskCommand, is_mentioned: bool = True) -> dict[str, Any]:
        if not is_mentioned:
            return {"ok": True, "ignored": True, "task_id": command.taskId, "message_id": command.id}
        task_id = command.taskId or ""
        group_id = command.groupId or ""
        message_id = command.id
        session_id = command.sessionId or ""
        key = (group_id, task_id, message_id)
        if key in self._processed:
            logger.info("event=mq_duplicate_message_ignored group_id=%s task_id=%s message_id=%s", group_id, task_id, message_id)
            return self._processed[key]
        command_type = getattr(command, "command", None)
        if command_type in {TaskCommandType.Complete, TaskCommandType.Complete.value, "complete"}:
            await self.client.complete_task(task_id, session_id)
            response = {
                "ok": True,
                "partner": self.partner,
                "action": "complete_task",
                "task_id": task_id,
                "message_id": message_id,
                "group_id": group_id,
                "states": ["completed"],
            }
            self._processed[key] = response
            logger.info("event=mq_task_completed group_id=%s task_id=%s message_id=%s", group_id, task_id, message_id)
            return response
        payload = self._payload(command)
        result = dispatch_business_action(self.partner, payload.get("action", ""), payload, db_path=self.db_path)
        if result["ok"]:
            await self.client.accept_task(task_id, session_id)
            await self.client.start_working(task_id, session_id)
            await self.client.submit_for_completion(
                task_id,
                session_id,
                [Product(
                    id=f"product-{task_id}",
                    name="gongwei-business-result",
                    dataItems=[TextDataItem(text=json.dumps(result, ensure_ascii=False))],
                )],
            )
        else:
            await self.client.fail_task(task_id, session_id, result.get("error", "业务动作失败。"))
        response = {**result, "task_id": task_id, "message_id": message_id, "group_id": group_id, "states": ["accepted", "working", "awaiting_completion"] if result["ok"] else ["failed"]}
        self._processed[key] = response
        logger.info("event=mq_task_processed group_id=%s task_id=%s message_id=%s action=%s ok=%s", group_id, task_id, message_id, payload.get("action"), result["ok"])
        return response


def _runtime_rabbitmq_config() -> dict[str, Any]:
    value = _env_any("GONGWEI_MQ_BROKER_URL", "MQ_BROKER_URL") or ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"amqp", "amqps"} or not parsed.hostname:
        raise ValueError("GONGWEI_MQ_BROKER_URL 必须是完整 AMQP(S) URL。")
    if parsed.scheme == "amqps" and (parsed.username or parsed.password or _env_any("GONGWEI_MQ_USER", "MQ_USER", "GONGWEI_MQ_PASSWORD", "MQ_PASSWORD")):
        raise ValueError("正式 platform_mq_inbox 只允许 mTLS，不能通过 AMQPS URL 或固定用户名密码绕过证书认证。")
    configured_vhost = _env_any("GONGWEI_MQ_VHOST", "MQ_VHOST") or (parsed.path or "/")
    # ACPs endpoint URLs encode the vhost as `/acps`, while the SDK compares
    # the parsed endpoint vhost (`acps`) with its connection config.  Normalize
    # only the internal SDK value; keep the user-facing MQ_VHOST unchanged.
    sdk_vhost = configured_vhost.lstrip("/") or "/"
    config: dict[str, Any] = {
        "host": parsed.hostname,
        "port": parsed.port or (5671 if parsed.scheme == "amqps" else 5672),
        "vhost": sdk_vhost,
        "user": parsed.username or _env_any("GONGWEI_MQ_USER", "MQ_USER"),
        "password": parsed.password or _env_any("GONGWEI_MQ_PASSWORD", "MQ_PASSWORD"),
        "auth_service_url": _env_any("GONGWEI_MQ_AUTH_SERVICE_URL", "MQ_AUTH_SERVICE_URL"),
    }
    if parsed.scheme == "amqps" and not (config["user"] and config["password"]):
        ca_file = _env_any("GONGWEI_MQ_CA_FILE", "MQ_CA_FILE")
        cert_file = _env_any("GONGWEI_MQ_CERT_FILE", "MQ_CERT_FILE")
        key_file = _env_any("GONGWEI_MQ_KEY_FILE", "MQ_KEY_FILE")
        if not (ca_file and cert_file and key_file):
            raise ValueError("AMQPS EXTERNAL 认证需要 MQ_CA_FILE/MQ_CERT_FILE/MQ_KEY_FILE（或对应 GONGWEI_ 变量）。")
        # The broker's client-auth chain is delivered in the official MQ trust
        # bundle, while the HTTPS mq-auth endpoint uses the public CA chain.
        # Keep both roots in one context so GroupAclClient can use the same
        # mTLS context without weakening verification or falling back to RPC.
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=ca_file)
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        config["ssl_context"] = context
        config["user"] = None
        config["password"] = None
    return config


class MqBusinessCoordinator:
    """Leader-side MQ coordinator used by the platform transport mode."""

    def __init__(self):
        require_mq_configuration()
        config = _runtime_rabbitmq_config()
        self.adapter = OfficialMqGroupLeaderAdapter(
            leader_aic=_env_any("GONGWEI_MQ_LEADER_AIC", "MQ_LEADER_AIC") or "",
            rabbitmq_config=config,
        )
        if not self.adapter.leader_aic:
            raise ValueError("缺少 GONGWEI_MQ_LEADER_AIC。")
        self._ready_sessions: set[str] = set()
        # SDK 2.2.0 keys pending invitations by Partner AIC across sessions.
        # Only group admission is serialized; running business tasks are not.
        self._group_lock = asyncio.Lock()
        self._initializing_task: asyncio.Task | None = None
        self._closed = False
        self._partners = {
            "resource": {
                "aic": _env_any("GONGWEI_MQ_RESOURCE_AIC", "MQ_RESOURCE_AIC") or "",
                "amqp_endpoint": _env_any("GONGWEI_MQ_RESOURCE_INBOX_ENDPOINT", "MQ_RESOURCE_INBOX_ENDPOINT", "GONGWEI_MQ_INBOX_ENDPOINT", "MQ_INBOX_ENDPOINT") or "",
            },
            "workorder": {
                "aic": _env_any("GONGWEI_MQ_WORKORDER_AIC", "MQ_WORKORDER_AIC") or "",
                "amqp_endpoint": _env_any("GONGWEI_MQ_WORKORDER_INBOX_ENDPOINT", "MQ_WORKORDER_INBOX_ENDPOINT", "GONGWEI_MQ_INBOX_ENDPOINT", "MQ_INBOX_ENDPOINT") or "",
            },
        }
        for item in self._partners.values():
            item["amqp_endpoint"] = item["amqp_endpoint"].replace("{AIC}", item["aic"]).replace("{aic}", item["aic"])
        for item in self._partners.values():
            if not item["aic"] or not item["amqp_endpoint"]:
                raise ValueError("缺少 MQ Partner AIC 或 Inbox endpoint。")

    async def _ensure_group(self, session_id: str) -> None:
        if self._closed:
            raise RuntimeError("MQ coordinator is closed")
        if session_id in self._ready_sessions and session_id in self.adapter.group_leader.group_sessions:
            return
        async with self._group_lock:
            if self._closed:
                raise RuntimeError("MQ coordinator is closed")
            # The SDK removes idle sessions after one hour. A local readiness
            # marker must not survive the actual SDK session it describes.
            self._ready_sessions.intersection_update(self.adapter.group_leader.group_sessions)
            if session_id in self._ready_sessions:
                return
            self._initializing_task = asyncio.current_task()
            try:
                result = await self.adapter.create_group_and_invite(
                    session_id=session_id,
                    partners=[{**item, "auth_service_url": self.adapter.rabbitmq_config.get("auth_service_url")} for item in self._partners.values()],
                )
            except BaseException:
                # Includes caller cancellation while an invitation is pending.
                # Use SDK cleanup so retries cannot overwrite a live consumer.
                try:
                    await self.adapter.group_leader.dissolve_group_session(session_id)
                except Exception as exc:
                    logger.warning("event=mq_group_cleanup_failed session_id=%s error_type=%s", session_id, type(exc).__name__)
                raise
            finally:
                self._initializing_task = None
            logger.info("event=mq_group_ready session_id=%s group_id=%s partners=%s", session_id, result["group_id"], result["invited"])
            self._ready_sessions.add(session_id)

    async def call(self, kind: str, action: str, payload: dict[str, Any], *, session_id: str | None = None, task_id: str | None = None) -> dict[str, Any]:
        session_id = session_id or f"session-{os.urandom(8).hex()}"
        await self._ensure_group(session_id)
        partner_aic = self._partners[kind]["aic"]
        task_id = task_id or f"gongwei-mq-{kind}-{os.urandom(8).hex()}"
        session = self.adapter.group_leader.group_sessions[session_id]
        await self.adapter.start_task(
            session_id=session_id,
            task_content=json.dumps({"action": action, **payload}, ensure_ascii=False),
            target_partners=[partner_aic],
            task_id=task_id,
        )
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            snapshot = session.get_partner_task_snapshot(task_id, partner_aic)
            if snapshot and snapshot["state"] == TaskState.AwaitingCompletion:
                await self.adapter.group_leader.complete_task(session_id, task_id, partner_aic)
            if snapshot and snapshot["state"] in {TaskState.Completed, TaskState.Failed, TaskState.Rejected}:
                break
            await asyncio.sleep(0.05)
        summary = session.get_task_summary(task_id)
        state = summary["states"].get(partner_aic)
        products = summary["products"].get(partner_aic)
        logger.info("event=mq_task_finished group_id=%s task_id=%s partner=%s state=%s", session.group_id, task_id, partner_aic, state)
        if state != TaskState.Completed or not products:
            raise RuntimeError(f"MQ Partner 未完成任务：{state}")
        return json.loads(products)

    async def close(self) -> None:
        self._closed = True
        initializing = self._initializing_task
        if initializing is not None and initializing is not asyncio.current_task():
            # Do not wait for the SDK's 300-second invitation timeout during
            # service shutdown. Drain cancellation before closing its channels.
            initializing.cancel()
            await asyncio.gather(initializing, return_exceptions=True)
        async with self._group_lock:
            try:
                await self.adapter.close()
            finally:
                self._ready_sessions.clear()

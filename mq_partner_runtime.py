"""Keep each official single-group Partner client separate from its Inbox."""
from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from acps_sdk.aip import GroupPartnerMqClient, InboxGroupInvitation, TaskCommand
from amp_telemetry import AmpTelemetry, telemetry_from_environment

logger = logging.getLogger(__name__)
SDK_CLOSE_TIMEOUT = 5.0


async def _close_sdk_client(client: GroupPartnerMqClient) -> None:
    """Bound SDK cleanup when auto-delete has already closed its channel.

    SDK 2.2.0 can wait indefinitely deleting an already removed group queue.
    Close this client's dedicated connection before allowing a replacement;
    the Inbox and other group connections are independent.
    """
    try:
        await asyncio.wait_for(client.close(), SDK_CLOSE_TIMEOUT)
    except TimeoutError:
        connection = client.connection
        if connection is not None and not connection.is_closed:
            await asyncio.wait_for(connection.close(), SDK_CLOSE_TIMEOUT)
        # aio-pika close() also succeeds when transport was already removed;
        # in that case is_closed can remain False despite no live transport.
        if connection is not None and not connection.is_closed and getattr(connection, "transport", True) is not None:
            raise RuntimeError("Old Partner connection did not close")
        logger.warning("event=partner_sdk_cleanup_timeout_connection_closed group_id=%s", client.group_id)


class _ClientDispatch:
    """Preserve runtime.client calls while routing replies by callback context.

    The Inbox client remains the default for health and queue operations. Each
    group callback selects its own SDK client using task-local context, including
    across awaits; concurrent handlers never mutate a shared active client.
    """

    def __init__(self, inbox: GroupPartnerMqClient):
        self._inbox = inbox
        self._current: ContextVar[GroupPartnerMqClient | None] = ContextVar("gongwei_partner_client", default=None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._current.get() or self._inbox, name)


class OfficialMqPartnerRuntime:
    def __init__(self, *, partner_aic: str, rabbitmq_config: dict[str, Any] | None = None,
                 telemetry: AmpTelemetry | None = None):
        self.partner_aic = partner_aic
        self.rabbitmq_config = dict(rabbitmq_config or {})
        self.telemetry = telemetry or telemetry_from_environment(role="partner_mq", aic=partner_aic)
        self._inbox_client = self._new_client()
        self.client = _ClientDispatch(self._inbox_client)
        self._command_handler = None
        self._invitation_handler = None
        self._groups: dict[str, GroupPartnerMqClient] = {}
        self._identities: dict[str, tuple[str, str]] = {}
        self._joining: dict[str, asyncio.Task] = {}
        self._waiters: set[asyncio.Task] = set()
        self._closed = False
        self._close_task: asyncio.Task | None = None

    def _new_client(self) -> GroupPartnerMqClient:
        amp_kwargs = {"message_emitter": self.telemetry.message_emitter} if self.telemetry else {}
        return GroupPartnerMqClient(
            partner_aic=self.partner_aic,
            rabbitmq_host=self.rabbitmq_config.get("host", "localhost"),
            rabbitmq_port=int(self.rabbitmq_config.get("port", 5672)),
            rabbitmq_vhost=self.rabbitmq_config.get("vhost", "/"),
            rabbitmq_user=self.rabbitmq_config.get("user"),
            rabbitmq_password=self.rabbitmq_config.get("password"),
            ssl_context=self.rabbitmq_config.get("ssl_context"),
            identity_binding_enabled=self.rabbitmq_config.get("identity_binding_enabled", True),
            **amp_kwargs,
        )

    async def start_inbox(self, invitation_handler: Callable[[InboxGroupInvitation], Awaitable[bool | None]]) -> None:
        if self._closed:
            raise RuntimeError("Partner runtime is closed")
        self._invitation_handler = invitation_handler
        await self._inbox_client.start_inbox_consuming(self._receive_invitation)

    def set_command_handler(self, handler: Callable[[TaskCommand, bool], Awaitable[Any]]) -> None:
        self._command_handler = handler

    async def _accept_invitation(self, invitation: InboxGroupInvitation, callback: Callable) -> bool:
        return await callback(invitation) is not False

    async def _receive_invitation(self, invitation: InboxGroupInvitation) -> bool:
        if self._closed:
            raise RuntimeError("Partner runtime is closed")
        group_id = invitation.group.groupId
        identity = (invitation.group.leader.aic, invitation.amqp.exchange)
        if not group_id or invitation.groupId != group_id:
            raise ValueError("Invitation group identity does not match")
        previous_identity = self._identities.get(group_id)
        if previous_identity is not None and previous_identity != identity:
            raise ValueError("Existing group identity cannot be replaced")
        waiter = asyncio.current_task()
        self._waiters.add(waiter)
        try:
            existing = self._groups.get(group_id)
            if existing is not None and existing.is_joined:
                return True
            task = self._joining.get(group_id)
            if task is None:
                self._identities[group_id] = identity
                task = asyncio.create_task(self._join_group(group_id, invitation))
                self._joining[group_id] = task

                def completed(finished):
                    if self._joining.get(group_id) is finished:
                        self._joining.pop(group_id, None)
                    if not finished.cancelled():
                        finished.exception()  # Consume failures if its Inbox waiter was cancelled.
                task.add_done_callback(completed)
            return await asyncio.shield(task)
        finally:
            self._waiters.discard(waiter)

    async def _join_group(self, group_id: str, invitation: InboxGroupInvitation) -> bool:
        previous = self._groups.pop(group_id, None)
        if previous is not None:
            await _close_sdk_client(previous)
        child = self._new_client()
        self._groups[group_id] = child

        async def on_command(command: TaskCommand, is_mentioned: bool = True):
            if self._closed:
                raise RuntimeError("Partner runtime is closed")
            if command.groupId != group_id:
                raise ValueError("Command group identity does not match its client")
            if self._command_handler is None:
                raise RuntimeError("Partner command handler is not configured")
            if self.telemetry is not None:
                await self.telemetry.bind_incoming(command)
            token = self.client._current.set(child)
            try:
                return await self._command_handler(command, is_mentioned)
            finally:
                self.client._current.reset(token)

        def disconnected(client, disconnected_group):
            if self._groups.get(disconnected_group) is client:
                self._groups.pop(disconnected_group, None)
                self._identities.pop(disconnected_group, None)

        child.set_command_handler(on_command)
        child.set_disconnect_handler(disconnected)
        child.set_invitation_handler(lambda message: self._accept_invitation(message, self._invitation_handler))
        accepted = False
        try:
            # The official SDK retains expiration, admission policy, queue setup,
            # identity checks and admission acknowledgements for this child.
            accepted = await child.join_group_from_invitation(invitation)
            return accepted
        finally:
            if not accepted:
                if self._groups.get(group_id) is child:
                    self._groups.pop(group_id, None)
                    self._identities.pop(group_id, None)
                await _close_sdk_client(child)

    async def _close(self) -> None:
        self._closed = True
        pending = set(self._joining.values()) | self._waiters
        pending.discard(asyncio.current_task())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        clients = [self._inbox_client, *self._groups.values()]
        self._groups.clear()
        self._identities.clear()
        self._joining.clear()
        self._waiters.clear()
        outcomes = await asyncio.gather(*(_close_sdk_client(client) for client in clients), return_exceptions=True)
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        if failures:
            raise RuntimeError("Failed to close one or more Partner SDK clients") from failures[0]

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

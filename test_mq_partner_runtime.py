"""Offline reproduction of the SDK's single-group client state boundary."""
from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from mq_group_transport import OfficialMqPartnerRuntime


def invitation(group_id, leader="leader-a", **extra):
    return SimpleNamespace(groupId=group_id,
                           group=SimpleNamespace(groupId=group_id, leader=SimpleNamespace(aic=leader)),
                           amqp=SimpleNamespace(exchange=f"exchange-{leader}-{group_id}"), **extra)


class SingleGroupClient:
    clients = []
    consumers = []
    gate = None
    joining = None

    def __init__(self, **kwargs):
        self.clients.append(self)
        self.group_id = None
        self.is_joined = False
        self.closed = False
        self.inbox_started = False
        self.commands = None
        self.policy = None
        self.disconnect = None
        self.results = []
        self.join_calls = 0
        self.close_calls = 0

    def set_command_handler(self, handler):
        self.commands = handler

    def set_invitation_handler(self, handler):
        self.policy = handler

    def set_disconnect_handler(self, handler):
        self.disconnect = handler

    async def start_inbox_consuming(self, callback):
        self.inbox_started = True
        self.invitations = callback

    async def join_group_from_invitation(self, message):
        self.join_calls += 1
        if self.policy and not await self.policy(message):
            return False
        if self.joining:
            self.joining.set()
        if self.gate:
            await self.gate.wait()
        if getattr(message, "fail_join", False):
            return False
        # Mirrors SDK mutable fields: a second join overwrites the first group.
        self.group_id = message.group.groupId
        self.is_joined = True
        self.consumers.append((self.group_id, self.commands))
        return True

    async def send_task_result(self, task_id, session_id, state):
        await asyncio.sleep(0)
        self.results.append((self.group_id, task_id, session_id, state))

    async def close(self):
        self.close_calls += 1
        self.closed = True
        self.inbox_started = False
        self.is_joined = False


class PartnerGroupIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        SingleGroupClient.clients = []
        SingleGroupClient.consumers = []
        SingleGroupClient.gate = None
        SingleGroupClient.joining = None
        module = importlib.import_module(OfficialMqPartnerRuntime.__module__)
        self.patcher = patch.object(module, "GroupPartnerMqClient", SingleGroupClient)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.runtime = OfficialMqPartnerRuntime(partner_aic="partner-test")
        self.addAsyncCleanup(self.runtime.close)
        self.policy = AsyncMock(return_value=True)

        async def command_handler(command, is_mentioned=True):
            await asyncio.sleep(0)
            await self.runtime.client.send_task_result(command.taskId, command.sessionId, "completed")
        self.runtime.set_command_handler(command_handler)
        await self.runtime.start_inbox(self.policy)
        self.inbox = SingleGroupClient.clients[0]

    async def test_inbox_stays_separate_and_concurrent_results_keep_their_group(self):
        await self.inbox.invitations(invitation("group-a"))
        await self.inbox.invitations(invitation("group-b"))
        await asyncio.gather(*(callback(SimpleNamespace(groupId=group, taskId="same-task", sessionId=group), True)
                               for group, callback in SingleGroupClient.consumers))
        results = [row for client in SingleGroupClient.clients for row in client.results]
        self.assertEqual(sorted((row[0], row[2]) for row in results), [("group-a", "group-a"), ("group-b", "group-b")])
        self.assertEqual(len(SingleGroupClient.clients), 3)
        self.assertIsNone(self.inbox.group_id)
        self.assertTrue(self.inbox.inbox_started)

    async def test_duplicate_invitations_join_once_even_when_concurrent(self):
        await asyncio.gather(self.inbox.invitations(invitation("group-a")), self.inbox.invitations(invitation("group-a")))
        self.assertEqual(sum(client.join_calls for client in SingleGroupClient.clients), 1)
        self.assertEqual(len(SingleGroupClient.clients), 2)

    async def test_close_releases_all_group_clients_and_inbox(self):
        await self.inbox.invitations(invitation("group-a"))
        await self.inbox.invitations(invitation("group-b"))
        await self.runtime.close()
        self.assertEqual(len(SingleGroupClient.clients), 3)
        self.assertTrue(all(client.closed for client in SingleGroupClient.clients))
        await self.runtime.close()
        self.assertTrue(all(client.close_calls == 1 for client in SingleGroupClient.clients))

    async def test_failed_join_releases_child_and_keeps_inbox_listening(self):
        self.assertFalse(await self.inbox.invitations(invitation("group-a", fail_join=True)))
        self.assertEqual(len(SingleGroupClient.clients), 2)
        self.assertTrue(SingleGroupClient.clients[1].closed)
        self.assertTrue(self.inbox.inbox_started)
        self.assertFalse(self.inbox.closed)
        self.assertTrue(await self.inbox.invitations(invitation("group-a")))

    async def test_same_group_id_cannot_be_rebound_to_another_leader(self):
        await self.inbox.invitations(invitation("group-a", leader="leader-a"))
        with self.assertRaisesRegex(ValueError, "identity"):
            await self.inbox.invitations(invitation("group-a", leader="leader-b"))
        self.assertEqual(len(SingleGroupClient.clients), 2)

    async def test_disconnected_group_can_rejoin_without_stopping_inbox(self):
        await self.inbox.invitations(invitation("group-a"))
        child = SingleGroupClient.clients[1]
        await child.close()
        child.disconnect(child, "group-a")
        self.assertTrue(self.inbox.inbox_started)
        await self.inbox.invitations(invitation("group-a"))
        self.assertEqual(len(SingleGroupClient.clients), 3)
        self.assertTrue(SingleGroupClient.clients[2].is_joined)

    async def test_reinvite_recovers_when_old_sdk_queue_cleanup_hangs(self):
        await self.inbox.invitations(invitation("group-a"))
        old = SingleGroupClient.clients[1]
        old.is_joined = False
        old.connection = SimpleNamespace(is_closed=False)
        async def close_connection():
            old.connection.is_closed = True
        old.connection.close = AsyncMock(side_effect=close_connection)
        old.close = AsyncMock(side_effect=asyncio.Event().wait)
        module = importlib.import_module(OfficialMqPartnerRuntime.__module__)
        with patch.object(module, "SDK_CLOSE_TIMEOUT", 0.02, create=True):
            accepted = await asyncio.wait_for(self.inbox.invitations(invitation("group-a")), 0.5)
        self.assertTrue(accepted)
        old.connection.close.assert_awaited_once()
        self.assertTrue(old.connection.is_closed)
        self.assertTrue(self.inbox.inbox_started)
        self.assertTrue(SingleGroupClient.clients[2].is_joined)

    async def test_policy_rejection_does_not_close_inbox(self):
        self.policy.return_value = False
        self.assertFalse(await self.inbox.invitations(invitation("group-a")))
        self.assertTrue(self.inbox.inbox_started)
        self.assertTrue(SingleGroupClient.clients[1].closed)

    async def test_handler_failure_resets_reply_context(self):
        async def fail(command, is_mentioned):
            raise RuntimeError("business failed")
        self.runtime.set_command_handler(fail)
        await self.inbox.invitations(invitation("group-a"))
        callback = SingleGroupClient.consumers[0][1]
        with self.assertRaisesRegex(RuntimeError, "business failed"):
            await callback(SimpleNamespace(groupId="group-a"), True)
        self.assertIsNone(self.runtime.client.group_id)

    async def test_close_cancels_pending_join_and_closes_created_clients(self):
        SingleGroupClient.joining = asyncio.Event()
        SingleGroupClient.gate = asyncio.Event()
        joining = asyncio.create_task(self.inbox.invitations(invitation("group-a")))
        await asyncio.wait_for(SingleGroupClient.joining.wait(), 1)
        try:
            await asyncio.wait_for(self.runtime.close(), 1)
            self.assertTrue(joining.done())
            self.assertTrue(all(client.closed for client in SingleGroupClient.clients))
        finally:
            joining.cancel()
            await asyncio.gather(joining, return_exceptions=True)


class OfficialSdkResultRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_stalled_queue_delete_closes_dedicated_connection(self):
        from acps_sdk.aip import GroupPartnerMqClient
        from acps_sdk.aip.aip_group_partner import PartnerGroupState
        import mq_partner_runtime
        client = GroupPartnerMqClient(partner_aic="partner-test")
        client._state = PartnerGroupState.LEAVING
        client._group_id = "group-restart"
        client._channel = SimpleNamespace(is_closed=True)
        async def stalled_delete(**kwargs):
            await asyncio.Event().wait()
        queue = SimpleNamespace(name="old-auto-delete-queue", delete=AsyncMock(side_effect=stalled_delete))
        client._queue = queue
        connection = SimpleNamespace(is_closed=False)
        async def close_connection():
            connection.is_closed = True
        connection.close = AsyncMock(side_effect=close_connection)
        client._connection = connection
        with patch.object(mq_partner_runtime, "SDK_CLOSE_TIMEOUT", 0.02):
            await asyncio.wait_for(mq_partner_runtime._close_sdk_client(client), 0.5)
        queue.delete.assert_awaited_once()
        connection.close.assert_awaited_once()
        self.assertTrue(connection.is_closed)

    async def test_cleanup_fails_if_connection_cannot_be_closed(self):
        import mq_partner_runtime
        connection = SimpleNamespace(is_closed=False, close=AsyncMock())
        client = SimpleNamespace(close=AsyncMock(side_effect=asyncio.Event().wait), connection=connection)
        with patch.object(mq_partner_runtime, "SDK_CLOSE_TIMEOUT", 0.02):
            with self.assertRaisesRegex(RuntimeError, "did not close"):
                await mq_partner_runtime._close_sdk_client(client)

    async def test_real_aio_pika_close_with_transport_already_removed(self):
        from aio_pika import RobustConnection
        from yarl import URL
        import mq_partner_runtime
        # aio-pika close() returns successfully if transport is already None,
        # without setting its _closed future. No socket is opened by this test.
        connection = RobustConnection(URL('amqps://example.invalid'))
        client = SimpleNamespace(close=AsyncMock(side_effect=asyncio.Event().wait),
                                 connection=connection, group_id='closed-channel')
        with patch.object(mq_partner_runtime, 'SDK_CLOSE_TIMEOUT', 0.02):
            await mq_partner_runtime._close_sdk_client(client)
        self.assertIsNone(connection.transport)
        self.assertTrue(connection._close_called)

    async def test_real_sdk_builds_results_and_task_states_for_each_client(self):
        from acps_sdk.aip import GroupPartnerMqClient, TaskState
        from acps_sdk.aip.aip_group_partner import PartnerGroupState
        import mq_partner_runtime

        clients = []
        incoming = []

        def client_factory(**kwargs):
            client = GroupPartnerMqClient(**kwargs)
            clients.append(client)

            async def inbox(callback):
                incoming.append(callback)

            async def join(message):
                client._group_id = message.group.groupId
                client._state = PartnerGroupState.JOINED
                client._connection = SimpleNamespace(is_closed=False)
                return True
            client.start_inbox_consuming = inbox
            client.join_group_from_invitation = join
            client._publish_message = AsyncMock()
            client.close = AsyncMock()
            return client

        with patch.object(mq_partner_runtime, "GroupPartnerMqClient", client_factory):
            runtime = OfficialMqPartnerRuntime(partner_aic="partner-test")

            async def handle(command, is_mentioned):
                await asyncio.sleep(0)
                await runtime.client.send_task_result("shared-task-id", command.groupId, command.state)

            runtime.set_command_handler(handle)
            await runtime.start_inbox(AsyncMock(return_value=True))
            try:
                for group in ("group-a", "group-b"):
                    await incoming[0](invitation(group))
                states = (TaskState.Accepted, TaskState.Working)
                await asyncio.gather(*(client._command_handler(SimpleNamespace(groupId=group, state=state), True)
                                       for client, group, state in zip(clients[1:], ("group-a", "group-b"), states)))
                for client, group, state in zip(clients[1:], ("group-a", "group-b"), states):
                    result = client._publish_message.await_args.args[0]
                    self.assertEqual((result.groupId, result.sessionId), (group, group))
                    self.assertEqual(client._task_states["shared-task-id"], state)
                self.assertEqual(clients[0]._task_states, {})
            finally:
                await runtime.close()
            for client in clients:
                client.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

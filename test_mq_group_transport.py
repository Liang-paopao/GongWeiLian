from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from stage2_db import initialize_database
from stage2_domain import create_inspection_request, create_plan


class MqGroupTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_partner_preserves_explicit_invitation_rejection(self):
        from mq_group_transport import OfficialMqPartnerRuntime

        runtime = object.__new__(OfficialMqPartnerRuntime)
        invitation = object()
        for decision, expected in ((False, False), (True, True), (None, True)):
            with self.subTest(decision=decision):
                policy = AsyncMock(return_value=decision)
                self.assertIs(await runtime._accept_invitation(invitation, policy), expected)
                policy.assert_awaited_once_with(invitation)

    async def test_leader_does_not_use_fixed_session_id(self):
        source = Path(__file__).with_name("mq_group_transport.py").read_text(encoding="utf-8")
        self.assertNotIn('self.session_id = "gongwei-mq-session"', source)

    async def test_mq_mode_does_not_silently_fallback_without_mtls_or_aic(self):
        import stage2_aip

        with patch.dict("os.environ", {"GONGWEI_TRANSPORT_MODE": "platform_mq_inbox"}, clear=True), patch.object(stage2_aip, "_MQ_COORDINATOR", None), patch.object(stage2_aip, "_call_partner_local_rpc", AsyncMock()) as local_call:
            with self.assertRaises(stage2_aip.PartnerCallError):
                await stage2_aip.call_partner("resource", "query_resources", {"request_id": "req-guard"})
        local_call.assert_not_awaited()

    async def test_leader_call_partner_uses_shared_mq_coordinator_in_mq_mode(self):
        import stage2_aip

        coordinator = type(
            "Coordinator",
            (),
            {"call": AsyncMock(return_value={"ok": True, "result": {"available": True}})},
        )()
        with patch.dict("os.environ", {"GONGWEI_TRANSPORT_MODE": "platform_mq_inbox"}, clear=False), patch.object(stage2_aip, "_MQ_COORDINATOR", coordinator):
            result = await stage2_aip.call_partner("resource", "query_resources", {"request_id": "req-1"})
        self.assertTrue(result["ok"])
        coordinator.call.assert_awaited_once()
        args, kwargs = coordinator.call.await_args
        self.assertEqual(args[:3], ("resource", "query_resources", {"request_id": "req-1"}))
        self.assertTrue(kwargs["session_id"].startswith("session-"))
        self.assertTrue(kwargs["task_id"].startswith("gongwei-mq-resource-"))

    async def test_adapter_uses_official_group_leader_and_inbox_metadata(self):
        from mq_group_transport import OfficialMqGroupLeaderAdapter

        with patch("mq_group_transport.GroupLeader") as group_leader_cls:
            group_leader = group_leader_cls.return_value
            session = object()
            group_leader.create_group_session = AsyncMock(return_value=session)
            group_leader.invite_partner = AsyncMock(return_value=True)
            adapter = OfficialMqGroupLeaderAdapter(
                leader_aic="leader-aic",
                rabbitmq_config={"host": "localhost", "port": 5672, "vhost": "acps", "user": "admin", "password": "devpass", "auth_service_url": "https://localhost:9007"},
            )
            result = await adapter.create_group_and_invite(
                session_id="session-1",
                partners=[{
                    "aic": "partner-aic",
                    "amqp_endpoint": "amqp://localhost:5672/acps?inbox=aip.inbox.partner-aic",
                    "auth_service_url": "https://localhost:9007",
                }],
            )
        self.assertEqual(result["session_id"], "session-1")
        group_leader.create_group_session.assert_awaited_once()
        group_leader.invite_partner.assert_awaited_once()
        invite_kwargs = group_leader.invite_partner.await_args.kwargs
        self.assertEqual(invite_kwargs["partner_acs_data"]["endPoints"][0]["transport"], "AMQP")
        self.assertEqual(invite_kwargs["partner_rpc_url"], None)

    async def test_partner_handler_emits_sdk_states_and_deduplicates_message(self):
        from mq_group_transport import OfficialMqPartnerHandler

        temp = tempfile.TemporaryDirectory()
        db_path = Path(temp.name) / "stage2.db"
        initialize_database(db_path)
        payload = {
            "pump_id": "pump-001", "work_date": (date.today() + timedelta(days=1)).isoformat(),
            "start_time": "09:00", "duration_minutes": 60, "description": "MQ任务",
        }
        request = create_inspection_request(payload, db_path)
        plan = create_plan(request["id"], db_path)
        client = type("Client", (), {
            "accept_task": AsyncMock(), "start_working": AsyncMock(),
            "complete_task": AsyncMock(), "submit_for_completion": AsyncMock(),
        })()
        handler = OfficialMqPartnerHandler("resource", client, db_path=db_path)
        command = type("Command", (), {
            "taskId": "task-1", "sessionId": "session-1", "groupId": "group-1",
            "id": "message-1", "command": "Start", "dataItems": [],
        })()
        command.dataItems = [type("Item", (), {"text": '{"action":"query_resources","request_id":"' + request["id"] + '"}'})()]
        first = await handler.handle(command, is_mentioned=True)
        second = await handler.handle(command, is_mentioned=True)
        self.assertTrue(first["ok"])
        self.assertEqual(first, second)
        client.accept_task.assert_awaited_once()
        client.start_working.assert_awaited_once()
        client.submit_for_completion.assert_awaited_once()
        self.assertEqual(first["task_id"], "task-1")
        temp.cleanup()


class MqCoordinatorLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def coordinator(self):
        """Exercise real SDK invitation state with only network I/O replaced."""
        from acps_sdk.aip.aip_group_leader import GroupLeaderSession
        from mq_group_transport import MqBusinessCoordinator

        env = {
            "GONGWEI_MQ_LEADER_AIC": "1.2.156.3088.1.TEST.AUDIT.LEADER.1.0000",
            "GONGWEI_MQ_RESOURCE_AIC": "1.2.156.3088.1.TEST.AUDIT.RESOURCE.1.0000",
            "GONGWEI_MQ_WORKORDER_AIC": "1.2.156.3088.1.TEST.AUDIT.WORKORDER.1.0000",
            "GONGWEI_MQ_INBOX_ENDPOINT": "amqps://broker.invalid:5671/acps?inbox=inbox_{AIC}",
        }
        with patch.dict("os.environ", env, clear=True), \
                patch("mq_group_transport.require_mq_configuration"), \
                patch("mq_group_transport._runtime_rabbitmq_config", return_value={
                    "host": "broker.invalid", "port": 5671, "vhost": "acps"}):
            coordinator = MqBusinessCoordinator()
        leader = coordinator.adapter.group_leader
        leader._group_acl_client = SimpleNamespace(add_member=AsyncMock(), remove_member=AsyncMock(),
                                                   delete_group=AsyncMock(), aclose=AsyncMock())
        self.inviting = asyncio.Event()
        self.release_invitation = asyncio.Event()
        self.created = []
        acknowledgements = []

        async def acknowledge(aic):
            await self.release_invitation.wait()
            pending = leader._pending_invitations.get(aic)
            if pending is not None and not pending.future.done():
                pending.future.set_result(None)

        async def invite(**kwargs):
            if not self.inviting.is_set():
                self.inviting.set()
                acknowledgements.append(asyncio.create_task(acknowledge(kwargs["partner_acs"].aic)))
                return
            pending = leader._pending_invitations.get(kwargs["partner_acs"].aic)
            if pending is not None and not pending.future.done():
                pending.future.set_result(None)

        async def create(*, session_id, initial_partners):
            client = SimpleNamespace(invite_via_inbox=invite, _channel=None, _partners={},
                                     broadcast_group_shutdown=AsyncMock(), cleanup_group_resources=AsyncMock())
            session = GroupLeaderSession(session_id, f"group-{session_id}", client)
            leader.group_sessions[session_id] = session
            self.created.append(session)
            return session

        leader.create_group_session = AsyncMock(side_effect=create)
        async def close_acknowledgements():
            for task in acknowledgements:
                task.cancel()
            await asyncio.gather(*acknowledgements, return_exceptions=True)
        self.addAsyncCleanup(close_acknowledgements)
        self.addAsyncCleanup(coordinator.close)
        return coordinator

    async def simultaneous_initialization(self, session_ids):
        coordinator = self.coordinator()
        first = asyncio.create_task(coordinator._ensure_group(session_ids[0]))
        await asyncio.wait_for(self.inviting.wait(), 1)
        second = asyncio.create_task(coordinator._ensure_group(session_ids[1]))
        await asyncio.sleep(0)  # Let the second call reach initialization while ACK is pending.
        self.release_invitation.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertEqual(results, [None, None], f"concurrent SDK invitation results: {results}")
        self.assertEqual(len(self.created), len(set(session_ids)))
        self.assertEqual(set(coordinator.adapter.group_leader.group_sessions), set(session_ids))
        self.assertEqual(coordinator.adapter.group_leader._pending_invitations, {})

    async def test_same_session_initialization_creates_only_one_group(self):
        await self.simultaneous_initialization(["same-session", "same-session"])

    async def test_different_sessions_serialize_shared_partner_invitations(self):
        await self.simultaneous_initialization(["session-a", "session-b"])

    async def test_sdk_expired_session_is_recreated_before_reuse(self):
        coordinator = self.coordinator()
        self.release_invitation.set()
        await coordinator._ensure_group("session-a")
        await coordinator.adapter.group_leader.dissolve_group_session("session-a")
        await coordinator._ensure_group("session-a")
        self.assertIn("session-a", coordinator.adapter.group_leader.group_sessions)
        self.assertEqual(len(self.created), 2)

    async def test_close_cleans_pending_initialization_and_prevents_reopening(self):
        coordinator = self.coordinator()
        initializing = asyncio.create_task(coordinator._ensure_group("session-a"))
        await asyncio.wait_for(self.inviting.wait(), 1)
        await asyncio.wait_for(coordinator.close(), 1)
        outcomes = await asyncio.gather(initializing, return_exceptions=True)
        self.assertIsInstance(outcomes[0], BaseException)
        self.assertEqual(coordinator.adapter.group_leader.group_sessions, {})
        self.assertEqual(coordinator._ready_sessions, set())
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await coordinator._ensure_group("session-b")

    async def test_failed_invitation_cleans_partial_group_before_retry(self):
        coordinator = self.coordinator()
        self.release_invitation.set()
        leader = coordinator.adapter.group_leader
        with patch.object(leader, "invite_partner", side_effect=RuntimeError("admission failed")):
            with self.assertRaisesRegex(RuntimeError, "admission failed"):
                await coordinator._ensure_group("session-a")
        self.assertEqual(leader.group_sessions, {})
        self.assertEqual(coordinator._ready_sessions, set())
        await coordinator._ensure_group("session-a")
        self.assertEqual(set(leader.group_sessions), {"session-a"})

    async def test_cancelled_initialization_cleans_group_and_releases_lock(self):
        coordinator = self.coordinator()
        initializing = asyncio.create_task(coordinator._ensure_group("session-a"))
        await asyncio.wait_for(self.inviting.wait(), 1)
        initializing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await initializing
        self.assertEqual(coordinator.adapter.group_leader.group_sessions, {})
        self.assertEqual(coordinator.adapter.group_leader._pending_invitations, {})
        self.release_invitation.set()
        await asyncio.wait_for(coordinator._ensure_group("session-b"), 1)

    async def test_ready_sessions_execute_business_tasks_concurrently(self):
        from acps_sdk.aip import TaskState

        coordinator = self.coordinator()
        self.release_invitation.set()
        await coordinator._ensure_group("session-a")
        await coordinator._ensure_group("session-b")
        started, release = asyncio.Event(), asyncio.Event()
        active = set()

        async def start_task(*, session_id, task_id, text_content, mentions):
            active.add(task_id)
            if len(active) == 2:
                started.set()
            await release.wait()
            session = coordinator.adapter.group_leader.group_sessions[session_id]
            session.record_task_state(task_id, mentions[0], TaskState.Completed, '{"ok":true}')
            return task_id

        for session in self.created:
            session.leader_mq_client.start_task = start_task
        calls = [asyncio.create_task(coordinator.call("resource", "query_resources", {},
                 session_id=f"session-{suffix}", task_id=f"task-{suffix}")) for suffix in ("a", "b")]
        try:
            await asyncio.wait_for(started.wait(), 1)
        finally:
            release.set()
        self.assertEqual(await asyncio.gather(*calls), [{"ok": True}, {"ok": True}])

    async def test_ready_session_is_not_blocked_by_another_session_invitation(self):
        coordinator = self.coordinator()
        self.release_invitation.set()
        await coordinator._ensure_group("ready-session")
        self.inviting.clear()
        self.release_invitation.clear()
        initializing = asyncio.create_task(coordinator._ensure_group("new-session"))
        await asyncio.wait_for(self.inviting.wait(), 1)
        existing = asyncio.create_task(coordinator._ensure_group("ready-session"))
        try:
            done, _ = await asyncio.wait({existing}, timeout=0.1)
            self.assertIn(existing, done, "ready session waited for an unrelated invitation ACK")
        finally:
            self.release_invitation.set()
            await asyncio.gather(initializing, existing)


if __name__ == "__main__":
    unittest.main()

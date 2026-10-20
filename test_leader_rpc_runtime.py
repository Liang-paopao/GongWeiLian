"""Offline regression tests for the formal Leader RPC and durable ownership."""
import asyncio
import importlib.util
import json
import os
import ssl
import socket
import sys
from datetime import date, datetime, timedelta, timezone
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem
from acps_sdk.aip.aip_rpc_model import RpcRequest, RpcRequestParams

from agentic_core import create_conversation, handle_conversation_message, parse_maintenance_request
from stage2_db import connect_db, transaction


def command(text="水泵001异常", message="m1", task="t1", session="s1", sender="caller", kind="start"):
    return TaskCommand(id=message, sentAt="2026-10-06T00:00:00Z", senderRole="leader", senderId=sender,
                       sessionId=session, taskId=task, command=TaskCommandType(kind),
                       dataItems=[TextDataItem(text=text)] if text else [])


class BusinessRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "business.db"
        self.env = patch.dict(os.environ, {"GONGWEI_STAGE2_DB": str(self.db), "GONGWEI_DISCOVERY_URL": "https://discovery.test", "LLM_BASE_URL": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_chinese_explicit_time_is_not_period_default(self):
        self.assertEqual(parse_maintenance_request("下午两点开始，预计一小时")["fields"].get("start_time"), "14:00")

    def test_same_session_can_have_multiple_explicit_tasks(self):
        create_conversation(session_id="session", task_id="first")
        try:
            create_conversation(session_id="session", task_id="second")
        except sqlite3.IntegrityError:
            self.fail("A session must accept a second task without replacing its first task")
        result = handle_conversation_message("session", "水泵001异常", task_id="first", message_id="turn")
        self.assertEqual(result["task_id"], "first")
        with connect_db() as conn:
            self.assertEqual(json.loads(conn.execute("SELECT context_json FROM agent_tasks WHERE task_id='second'").fetchone()[0]), {})

    def test_replayed_message_retains_original_relative_date(self):
        create_conversation(session_id="s1", task_id="t1")
        text = "水泵001异常，明天下午两点开始，预计一小时"
        first = handle_conversation_message("s1", text, task_id="t1", message_id="same", today=date(2026, 10, 6))
        replay = handle_conversation_message("s1", text, task_id="t1", message_id="same", today=date(2026, 10, 7))
        self.assertEqual(replay["request"]["work_date"], first["request"]["work_date"])

    async def test_revised_resource_query_has_new_subtask_and_updated_plan(self):
        from leader_external_flow import handle_external_command
        create_conversation(session_id="s1", task_id="t1")
        resolver = {"selected": {"aic": "resource"}}
        def preview(worker):
            return {"ok": True, "result": {"available": True, "workers": [{"id": worker}], "inventory": [{"id": "tool-inspection-kit"}, {"id": "part-seal-ring"}]}}
        with patch("leader_external_flow.PartnerResolver.resolve", return_value=resolver), patch("leader_external_flow.call_partner", new=AsyncMock(side_effect=[preview("worker-001"), preview("worker-002")])) as call:
            await handle_external_command(command("水泵001异常，明天下午2点开始，预计一小时"))
            revised = await handle_external_command(command("改到下午3点", message="m2", kind="continue"))
        ids = [item.kwargs["task_id"] for item in call.await_args_list]
        self.assertNotEqual(ids[0], ids[1], "SDK deduplication must not reuse the old query")
        self.assertEqual(revised["result"]["plan"]["worker_id"], "worker-002")
        self.assertEqual(revised["result"]["request"]["start_time"], "15:00")

    async def test_replayed_query_reuses_external_partner_task_id(self):
        from leader_external_flow import handle_external_command
        from stage2_domain import preview_resources
        create_conversation(session_id="s1", task_id="t1")
        async def partner(kind, action, payload, **kwargs):
            return {"ok": True, "result": preview_resources(payload["request_id"])}
        with patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": {"aic": "resource"}}), patch("leader_external_flow.call_partner", new=AsyncMock(side_effect=partner)) as call:
            await handle_external_command(command("水泵001异常，明天下午两点开始，预计一小时"))
            await handle_external_command(command("水泵001异常，明天下午两点开始，预计一小时"))
        self.assertEqual(call.await_args_list[0].kwargs["task_id"], call.await_args_list[1].kwargs["task_id"])

    async def test_cancel_unconfirmed_plan_does_not_wait_for_unneeded_mq_release(self):
        from leader_external_flow import handle_external_command
        from stage2_domain import preview_resources
        create_conversation(session_id='s1', task_id='t1')
        async def partner(kind, action, payload, **kwargs):
            if action != 'query_resources':
                raise RuntimeError('The broker is temporarily unavailable')
            return {'ok': True, 'result': preview_resources(payload['request_id'])}
        with patch('leader_external_flow.PartnerResolver.resolve', return_value={'selected': {'aic': 'resource'}}), patch('leader_external_flow.call_partner', new=AsyncMock(side_effect=partner)) as call:
            await handle_external_command(command('水泵001异常，明天下午两点开始，预计一小时'))
            result = await handle_external_command(command('', message='cancel', kind='cancel'))
        self.assertEqual(result['state'], 'canceled')
        self.assertEqual(call.await_count, 1)
        with connect_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM reservations').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM work_orders').fetchone()[0], 0)

    async def test_negated_cancel_revises_plan_without_releasing(self):
        from leader_external_flow import handle_external_command
        from stage2_domain import preview_resources
        create_conversation(session_id="s1", task_id="t1")
        actions = []
        async def partner(kind, action, payload, **kwargs):
            actions.append(action)
            return {"ok": True, "result": preview_resources(payload["request_id"])} if action == "query_resources" else {"ok": True, "result": {}}
        with patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": {"aic": "resource"}}), patch("leader_external_flow.call_partner", new=partner):
            await handle_external_command(command("水泵001异常，明天下午两点开始，预计一小时"))
            revised = await handle_external_command(command("不要取消，改到下午三点", message="keep", kind="continue"))
        self.assertEqual(revised["state"], "awaiting_input")
        self.assertEqual(revised["result"]["request"]["start_time"], "15:00")
        self.assertEqual(actions, ["query_resources", "query_resources"])

    async def _propose_for_discovery_test(self):
        from leader_external_flow import handle_external_command
        from stage2_domain import preview_resources
        create_conversation(session_id="s1", task_id="t1")
        async def query(kind, action, payload, **kwargs):
            return {"ok": True, "result": preview_resources(payload["request_id"])}
        with patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": {"aic": "resource"}}), patch("leader_external_flow.call_partner", new=query):
            await handle_external_command(command("水泵001异常，明天下午两点开始，预计一小时"))

    async def test_missing_online_workorder_partner_fails_before_reservation(self):
        from leader_external_flow import handle_external_command
        from stage2_domain import DomainError
        await self._propose_for_discovery_test()
        with patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": None, "error": "no approved workorder partner"}), patch("leader_external_flow.call_partner", new=AsyncMock(return_value={"ok": True, "result": {}})) as partner:
            with self.assertRaisesRegex(DomainError, "no approved workorder"):
                await handle_external_command(command("确认这个方案并创建工单。", message="confirm-discovery", kind="continue"))
        partner.assert_not_awaited()

    async def test_confirmation_discovers_workorder_skill_before_business_calls(self):
        from leader_external_flow import handle_external_command
        await self._propose_for_discovery_test()
        with patch("leader_external_flow.PartnerResolver") as resolver, patch("leader_external_flow.call_partner", new=AsyncMock(side_effect=[{"ok": True, "result": {}}, {"ok": True, "result": {"work_order": {"number": "WO-1"}}}])) as partner:
            resolver.return_value.resolve.return_value = {"selected": {"aic": "workorder"}}
            result = await handle_external_command(command("确认这个方案并创建工单。", message="confirm-discovery", kind="continue"))
        resolver.assert_called_once_with(discovery_url="https://discovery.test", strict_online=True)
        resolver.return_value.resolve.assert_called_once_with("workorder", ["gongwei.work-order.create"], task_id="t1")
        self.assertEqual([call.args[1] for call in partner.await_args_list], ["reserve_resources", "create_work_order"])
        self.assertEqual(result["state"], "completed")

    async def test_completed_business_task_cannot_be_overwritten(self):
        from leader_external_flow import handle_external_command
        create_conversation(session_id="s1", task_id="t1")
        with transaction() as conn:
            conn.execute("UPDATE agent_tasks SET status='completed' WHERE task_id='t1'")
        with patch("leader_external_flow.PartnerResolver.resolve", side_effect=AssertionError("terminal task must not discover again")):
            result = await handle_external_command(command("水泵001异常，明天下午2点开始，预计一小时", kind="continue"))
        self.assertEqual(result["state"], "completed")
        with connect_db() as conn:
            self.assertEqual(conn.execute("SELECT status FROM agent_tasks WHERE task_id='t1'").fetchone()[0], "completed")


class RpcRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(importlib.util.find_spec("leader_rpc_runtime"), "durable official RPC runtime is missing")
        from leader_rpc_runtime import LeaderRpcRuntime
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "protocol.db"
        self.env = patch.dict(os.environ, {"GONGWEI_STAGE2_DB": str(Path(self.temp.name) / "business.db")})
        self.env.start()
        self.handler = AsyncMock(return_value={"state": "awaiting_input", "result": {"question": "需要时长"}})
        self.runtime = LeaderRpcRuntime(leader_aic="leader", state_path=self.state, command_handler=self.handler)
        await self.runtime.start()

    async def asyncTearDown(self):
        if hasattr(self, "runtime"):
            await self.runtime.close()
            self.env.stop()
            self.temp.cleanup()

    async def send(self, cmd, runtime=None):
        return await (runtime or self.runtime).dispatch_request(RpcRequest(id=cmd.id, params=RpcRequestParams(command=cmd)))

    async def settle(self):
        await self.runtime.wait_idle()

    def test_cancel_response_wait_requires_finite_positive_timeout(self):
        from leader_rpc_runtime import LeaderRpcRuntime
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite positive"):
                LeaderRpcRuntime(leader_aic="leader", state_path=self.state, cancel_response_timeout_seconds=value)

    async def test_domain_failure_returns_actionable_reason(self):
        from stage2_domain import DomainError
        self.handler.side_effect = DomainError('在线发现没有返回可用工单 Partner。')
        await self.send(command())
        await self.settle()
        result = (await self.send(command('', message='get-error', kind='get'))).result
        self.assertEqual(result.status.state.value, 'failed')
        self.assertIn('在线发现没有返回可用工单 Partner', result.status.dataItems[0].text)

    async def test_unexpected_failure_does_not_echo_secret_exception(self):
        self.handler.side_effect = RuntimeError('Authorization: Bearer do-not-return-this')
        await self.send(command())
        await self.settle()
        result = (await self.send(command('', message='get-error', kind='get'))).result
        self.assertEqual(result.status.state.value, 'failed')
        self.assertNotIn('do-not-return-this', result.model_dump_json())

    async def test_start_get_continue_complete_and_confirmation_gate(self):
        first = await self.send(command())
        self.assertEqual(first.result.status.state.value, "accepted")
        await self.settle()
        get = await self.send(command("", message="get", kind="get"))
        self.assertEqual(get.result.status.state.value, "awaiting-input")
        self.handler.return_value = {"state": "awaiting_completion", "result": {"requiresConfirmation": True}}
        await self.send(command("一小时", message="m2", kind="continue"))
        await self.settle()
        empty_complete = await self.send(command("", message="empty-complete", kind="complete"))
        self.assertEqual(empty_complete.result.status.state.value, "awaiting-completion")
        self.assertEqual(self.handler.await_count, 2)
        self.handler.return_value = {"state": "completed", "result": {"workOrder": {"number": "WO-1"}}}
        await self.send(command("确认这个方案并创建工单。", message="m3", kind="complete"))
        await self.settle()
        final = await self.send(command("", message="get2", kind="get"))
        self.assertEqual(final.result.status.state.value, "completed")
        self.assertEqual([s.state.value for s in final.result.statusHistory][:3], ["accepted", "working", "awaiting-input"])
        await self.send(command("改到明天", message="later", kind="continue"))
        await self.send(command("", message="cancel", kind="cancel"))
        self.assertEqual(self.handler.await_count, 3)

    async def test_restart_preserves_snapshot_owner_and_receipt(self):
        from leader_rpc_runtime import LeaderRpcRuntime
        first = await self.send(command(task=None))
        task_id = first.result.taskId
        self.assertEqual(first.result.sessionId, "s1")
        await self.settle()
        await self.runtime.close()
        self.runtime = LeaderRpcRuntime(leader_aic="leader", state_path=self.state, command_handler=self.handler)
        await self.runtime.start()
        duplicate = await self.send(command(task=None))
        self.assertEqual(duplicate.result.taskId, task_id)
        self.assertEqual(self.handler.await_count, 1)
        attacker = await self.send(command("", message="attacker", task=task_id, sender="other", kind="get"))
        self.assertIsNotNone(attacker.error)
        wrong_session = await self.send(command("", message="wrong", task=task_id, session="other-session", kind="get"))
        self.assertIsNotNone(wrong_session.error)
        hijack = await self.send(command(message="hijack", task="new-task", sender="other"))
        self.assertIsNotNone(hijack.error)

    async def test_duplicate_message_and_changed_payload_are_not_executed(self):
        await self.send(command())
        await self.settle()
        await self.send(command())
        altered = await self.send(command("changed"))
        self.assertEqual(self.handler.await_count, 1)
        self.assertIsNotNone(altered.error)

    async def test_pending_command_recovers_after_shutdown(self):
        from leader_rpc_runtime import LeaderRpcRuntime
        blocked = asyncio.Event()
        entered = asyncio.Event()
        async def slow(cmd):
            entered.set()
            await blocked.wait()
            return {"state": "awaiting_input", "result": {"recovered": True}}
        self.runtime.command_handler = slow
        await self.send(command())
        await entered.wait()
        await self.runtime.close()
        self.runtime = LeaderRpcRuntime(leader_aic="leader", state_path=self.state, command_handler=self.handler)
        await self.runtime.start()
        await self.settle()
        response = await self.send(command("", message="get", kind="get"))
        self.assertEqual(response.result.status.state.value, "awaiting-input")
        self.handler.assert_awaited_once()

    async def test_second_runtime_cannot_open_same_state_database(self):
        from leader_rpc_runtime import LeaderRpcRuntime
        other = LeaderRpcRuntime(leader_aic="leader", state_path=self.state, command_handler=self.handler)
        try:
            with self.assertRaisesRegex(RuntimeError, "already|占用"):
                await other.start()
        finally:
            await other.close()

    async def test_another_process_cannot_open_same_state_database(self):
        script = """
import asyncio, sys
from leader_rpc_runtime import LeaderRpcRuntime
async def check():
    runtime = LeaderRpcRuntime(leader_aic='leader', state_path=sys.argv[1])
    try:
        await runtime.start()
    except RuntimeError:
        print('LOCKED')
        return
    await runtime.close()
    raise SystemExit(2)
asyncio.run(check())
"""
        child = await asyncio.create_subprocess_exec(sys.executable, "-c", script, str(self.state), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(child.communicate(), 10)
        self.assertEqual(child.returncode, 0, stderr.decode(errors="replace"))
        self.assertEqual(stdout.strip(), b"LOCKED")

    async def test_cancel_during_work_is_queued_and_never_runs_in_parallel(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def slow(cmd):
            calls.append(cmd.command.value)
            if cmd.command == TaskCommandType.Start:
                entered.set()
                await release.wait()
            return {"state": "awaiting_completion", "result": {}}
        self.runtime.command_handler = slow
        await self.send(command())
        await entered.wait()
        canceled = await self.send(command("", message="cancel-working", kind="cancel"))
        self.assertIsNone(canceled.error)
        self.assertEqual(calls, ["start"])
        release.set()
        await self.settle()
        final = await self.send(command("", message="final", kind="get"))
        self.assertEqual(calls, ["start", "cancel"])
        self.assertEqual(final.result.status.state.value, "canceled")

    async def test_official_client_idle_cancel_returns_canceled_without_polling(self):
        import httpx
        from acps_sdk.aip.aip_rpc_client import AipRpcClient
        leader = "1.2.156.3088.1.TEST.LEADER.1.1.0000"
        caller = "1.2.156.3088.1.TEST.CALLER.1.1.0000"
        self.runtime.leader_aic = leader
        await self.send(command(sender=caller))
        await self.settle()
        calls = []
        async def delayed_cancel(cmd):
            self.assertEqual(cmd.command, TaskCommandType.Cancel)
            await asyncio.sleep(0.02)
            return {"state": "completed", "result": {"status": "cancelled"}}
        async def transport(request):
            rpc = RpcRequest.model_validate_json(request.content)
            calls.append(rpc.params.command.command)
            response = await self.runtime.dispatch_request(rpc)
            return httpx.Response(200, json=response.model_dump(mode="json"))
        self.runtime.command_handler = delayed_cancel
        client = AipRpcClient("https://leader.test/rpc", caller, transport=httpx.MockTransport(transport), expected_partner_aic=leader)
        try:
            # The local transport has no TLS socket; retain SDK identity checks
            # against this explicit test peer while exercising its real RPC path.
            with patch("acps_sdk.aip.aip_rpc_client.extract_peer_aic_from_httpx_response", return_value=leader):
                result = await client.cancel_task("t1", "s1")
            self.assertEqual(result.status.state.value, "canceled")
            self.assertEqual(calls, [TaskCommandType.Cancel])
            with self.runtime._db() as db:
                row = db.execute("SELECT snapshot_json,pending_json FROM rpc_tasks WHERE task_id='t1'").fetchone()
            self.assertEqual(json.loads(row["snapshot_json"])["status"]["state"], "canceled")
            self.assertIsNone(row["pending_json"])
        finally:
            await client.close()

    async def test_idle_cancel_wait_releases_dispatch_lock_and_preserves_intent(self):
        await self.send(command())
        await self.settle()
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_cancel(cmd):
            entered.set()
            await release.wait()
            return {"state": "completed", "result": {"status": "cancelled"}}
        self.runtime.command_handler = delayed_cancel
        response = asyncio.create_task(self.send(command("", message="cancel-idle", kind="cancel")))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertFalse(response.done(), "Idle cancel must await this task's compensation")
            current = await asyncio.wait_for(self.send(command("", message="get-during-cancel", kind="get")), 0.2)
            self.assertEqual(current.result.status.state.value, "working")
            with self.runtime._db() as db:
                pending = db.execute("SELECT pending_json FROM rpc_tasks WHERE task_id='t1'").fetchone()[0]
            self.assertEqual(json.loads(pending)["command"], "cancel")
            release.set()
            self.assertEqual((await asyncio.wait_for(response, 1)).result.status.state.value, "canceled")
        finally:
            release.set()
            await response

    async def test_idle_cancel_timeout_keeps_compensation_running(self):
        await self.send(command())
        await self.settle()
        self.runtime.cancel_response_timeout_seconds = 0.03
        release = asyncio.Event()
        interrupted = []
        async def delayed_cancel(cmd):
            try:
                await release.wait()
            except asyncio.CancelledError:
                interrupted.append(True)
                raise
            return {"state": "completed", "result": {"status": "cancelled"}}
        self.runtime.command_handler = delayed_cancel
        try:
            response = await asyncio.wait_for(self.send(command("", message="cancel-timeout", kind="cancel")), 0.5)
            self.assertEqual(response.result.status.state.value, "working")
            self.assertEqual(interrupted, [])
            with self.runtime._db() as db:
                self.assertIsNotNone(db.execute("SELECT pending_json FROM rpc_tasks WHERE task_id='t1'").fetchone()[0])
            release.set()
            await self.settle()
            final = await self.send(command("", message="after-timeout", kind="get"))
            self.assertEqual(final.result.status.state.value, "canceled")
            self.assertEqual(interrupted, [])
        finally:
            release.set()

    async def test_canceling_rpc_waiter_does_not_cancel_compensation(self):
        await self.send(command())
        await self.settle()
        entered, release = asyncio.Event(), asyncio.Event()
        interrupted = []
        async def delayed_cancel(cmd):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                interrupted.append(True)
                raise
            return {"state": "completed", "result": {"status": "cancelled"}}
        self.runtime.command_handler = delayed_cancel
        response = asyncio.create_task(self.send(command("", message="cancel-disconnect", kind="cancel")))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertFalse(response.done())
            response.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await response
            self.assertEqual(interrupted, [])
            release.set()
            await self.settle()
            final = await self.send(command("", message="after-disconnect", kind="get"))
            self.assertEqual(final.result.status.state.value, "canceled")
            self.assertEqual(interrupted, [])
        finally:
            release.set()
            await asyncio.gather(response, return_exceptions=True)

    async def test_idle_cancel_failed_resource_release_returns_working_then_recovers(self):
        from leader_external_flow import handle_external_command
        from stage2_domain import preview_resources, reserve_plan_resources, release_plan_resources
        self.runtime.command_handler = handle_external_command
        self.runtime.cancel_response_timeout_seconds = 0.03
        self.runtime.compensation_retry_seconds = 0.01
        allow_release = asyncio.Event()
        actions = []
        async def partner(kind, action, payload, **kwargs):
            actions.append(action)
            if action == "query_resources":
                return {"ok": True, "result": preview_resources(payload["request_id"])}
            self.assertEqual(action, "release_resources")
            if not allow_release.is_set():
                raise RuntimeError("temporary release failure")
            release_plan_resources(payload["plan_id"])
            return {"ok": True, "result": {}}
        with patch.dict(os.environ, {"GONGWEI_DISCOVERY_URL": "https://discovery.test", "LLM_BASE_URL": ""}), patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": {"aic": "resource"}}), patch("leader_external_flow.call_partner", new=partner):
            await self.send(command("水泵001异常，明天下午两点开始，预计一小时"))
            await self.settle()
            with connect_db() as db:
                plan_id = db.execute("SELECT plan_id FROM agent_tasks WHERE task_id='t1'").fetchone()[0]
            reserve_plan_resources(plan_id)
            # This integration case performs real SQLite commits. The guard
            # detects a stuck response; sub-second disk timing on Windows is
            # not the contract (the event-gated unit case checks that wait).
            response = await asyncio.wait_for(self.send(command("", message="cancel-idle-reserved", kind="cancel")), 5)
            self.assertEqual(response.result.status.state.value, "working")
            with connect_db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 3)
            self.assertIn("release_resources", actions)
            allow_release.set()
            await asyncio.wait_for(self.settle(), 1)
        final = await self.send(command("", message="after-idle-release", kind="get"))
        self.assertEqual(final.result.status.state.value, "canceled")
        with connect_db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0], 0)

    async def test_cancel_during_reservation_releases_resources_without_creating_order(self):
        from leader_external_flow import handle_external_command
        from stage2_domain import preview_resources, reserve_plan_resources, release_plan_resources
        self.runtime.command_handler = handle_external_command
        entered, release = asyncio.Event(), asyncio.Event()
        actions = []
        async def partner(kind, action, payload, **kwargs):
            actions.append(action)
            if action == "query_resources":
                return {"ok": True, "result": preview_resources(payload["request_id"])}
            if action == "reserve_resources":
                reserve_plan_resources(payload["plan_id"])
                entered.set()
                await release.wait()
            elif action == "release_resources":
                release_plan_resources(payload["plan_id"])
            else:
                self.fail("Cancel must prevent work-order creation")
            return {"ok": True, "result": {}}
        with patch.dict(os.environ, {"GONGWEI_DISCOVERY_URL": "https://discovery.test", "LLM_BASE_URL": ""}), patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": {"aic": "resource"}}), patch("leader_external_flow.call_partner", new=partner):
            await self.send(command("水泵001异常，明天下午两点开始，预计一小时"))
            await self.settle()
            await self.send(command("确认这个方案并创建工单。", message="confirm", kind="continue"))
            await asyncio.wait_for(entered.wait(), 3)
            await self.send(command("", message="cancel-reserve", kind="cancel"))
            release.set()
            await self.settle()
        final = await self.send(command("", message="final-reserve", kind="get"))
        self.assertEqual(final.result.status.state.value, "canceled")
        self.assertIn("release_resources", actions)
        with connect_db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0], 0)

    async def _exercise_failed_compensation_recovery(self, cancel_requested, restart=True):
        from leader_external_flow import handle_external_command
        from leader_rpc_runtime import LeaderRpcRuntime
        from stage2_domain import preview_resources, reserve_plan_resources, release_plan_resources
        self.runtime.command_handler = handle_external_command
        self.runtime.compensation_retry_seconds = 0.05
        reserved, unblock, failed_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        allow_release = False
        actions = []
        async def partner(kind, action, payload, **kwargs):
            actions.append(action)
            if action == "query_resources":
                return {"ok": True, "result": preview_resources(payload["request_id"])}
            if action == "reserve_resources":
                reserve_plan_resources(payload["plan_id"])
                reserved.set()
                await unblock.wait()
            elif action == "create_work_order":
                raise RuntimeError("temporary order service error")
            elif action == "release_resources":
                if not allow_release:
                    failed_release.set()
                    raise RuntimeError("temporary release service error")
                release_plan_resources(payload["plan_id"])
            return {"ok": True, "result": {}}
        with patch.dict(os.environ, {"GONGWEI_DISCOVERY_URL": "https://discovery.test", "LLM_BASE_URL": ""}), patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": {"aic": "resource"}}), patch("leader_external_flow.call_partner", new=partner):
            await self.send(command("水泵001异常，明天下午两点开始，预计一小时"))
            await self.settle()
            await self.send(command("确认这个方案并创建工单。", message="confirm", kind="continue"))
            await asyncio.wait_for(reserved.wait(), 3)
            if cancel_requested:
                await self.send(command("", message="cancel-release", kind="cancel"))
            unblock.set()
            await asyncio.wait_for(failed_release.wait(), 3)
            await asyncio.sleep(0)
            response = await self.send(command("", message="during-error", kind="get"))
            self.assertEqual(response.result.status.state.value, "working", "unconfirmed compensation must not become terminal")
            with connect_db() as business:
                self.assertEqual(business.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 3)
            if restart:
                await self.runtime.close()
            allow_release = True
            if restart:
                self.runtime = LeaderRpcRuntime(leader_aic="leader", state_path=self.state, command_handler=handle_external_command)
                await self.runtime.start()
            await asyncio.wait_for(self.settle(), 3)
        response = await self.send(command("", message="after-restart", kind="get"))
        self.assertEqual(response.result.status.state.value, "canceled" if cancel_requested else "failed")
        self.assertEqual(actions.count("reserve_resources"), 1)
        self.assertEqual(actions.count("create_work_order"), 0 if cancel_requested else 1)
        with connect_db() as business:
            self.assertEqual(business.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 0)
            self.assertEqual(business.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0], 0)

    async def test_failed_cancel_compensation_survives_restart(self):
        await self._exercise_failed_compensation_recovery(cancel_requested=True)

    async def test_failed_order_compensation_survives_restart(self):
        await self._exercise_failed_compensation_recovery(cancel_requested=False)

    async def test_cancel_compensation_retries_without_process_restart(self):
        await self._exercise_failed_compensation_recovery(cancel_requested=True, restart=False)

    async def test_cancel_arriving_during_rollback_is_preserved(self):
        from leader_external_flow import handle_external_command
        from stage2_domain import preview_resources, reserve_plan_resources, release_plan_resources
        self.runtime.command_handler = handle_external_command
        cleanup_started, unblock = asyncio.Event(), asyncio.Event()
        releases = 0
        async def partner(kind, action, payload, **kwargs):
            nonlocal releases
            if action == "query_resources":
                return {"ok": True, "result": preview_resources(payload["request_id"])}
            if action == "reserve_resources":
                reserve_plan_resources(payload["plan_id"])
            elif action == "create_work_order":
                raise TimeoutError("no order committed")
            elif action == "release_resources":
                releases += 1
                if releases == 1:
                    raise TimeoutError("first cleanup response unavailable")
                if releases == 2:
                    cleanup_started.set()
                    await unblock.wait()
                release_plan_resources(payload["plan_id"])
            return {"ok": True, "result": {}}
        with patch.dict(os.environ, {"GONGWEI_DISCOVERY_URL": "https://discovery.test", "LLM_BASE_URL": ""}), patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": {"aic": "partner"}}), patch("leader_external_flow.call_partner", new=partner):
            await self.send(command("水泵001异常，明天下午两点开始，预计一小时"))
            await self.settle()
            await self.send(command("确认这个方案并创建工单。", message="confirm-late-cancel", kind="continue"))
            await asyncio.wait_for(cleanup_started.wait(), 3)
            accepted = await self.send(command("", message="during-cleanup", kind="cancel"))
            self.assertIsNone(accepted.error)
            unblock.set()
            await asyncio.wait_for(self.settle(), 3)
        response = await self.send(command("", message="after-cleanup", kind="get"))
        self.assertEqual(response.result.status.state.value, "canceled")
        with connect_db() as business:
            self.assertEqual(business.execute("SELECT status FROM agent_tasks WHERE task_id='t1'").fetchone()[0], "cancelled")
            self.assertEqual(business.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 0)

    async def test_text_cancellation_has_canceled_protocol_state(self):
        from leader_external_flow import handle_external_command
        self.runtime.command_handler = handle_external_command
        with patch.dict(os.environ, {"LLM_BASE_URL": ""}):
            await self.send(command())
            await self.settle()
            await self.send(command("取消任务", message="text-cancel", kind="continue"))
            await self.settle()
        final = await self.send(command("", message="text-cancel-get", kind="get"))
        self.assertEqual(final.result.status.state.value, "canceled")

    async def test_start_business_cancellation_keeps_completed_operation_state(self):
        self.handler.return_value = {
            'state': 'completed',
            'summary': '已取消待确认方案；未预留资源，未创建工单。',
            'result': {'status': 'cancelled', 'operation': 'cancel_plan',
                       'cancellationContinuation': {'source_task_id': 'source'}},
        }
        await self.send(command('取消任务', task='cancel-operation', message='cancel-operation'))
        await self.settle()
        final = await self.send(command('', task='cancel-operation', message='get-operation', kind='get'))
        self.assertEqual(final.result.status.state.value, 'completed')
        self.assertIn('已取消待确认方案', final.result.status.dataItems[0].text)
        self.assertEqual(json.loads(final.result.products[0].dataItems[0].text)['status'], 'cancelled')

    async def test_failed_start_cancellation_operation_is_not_completed(self):
        self.handler.return_value = {'state': 'failed', 'error': '取消操作未完成。',
                                     'result': {'status': 'failed'}}
        wrapped = '历史请求\n\n上一轮候选结果：方案\n叮当请求补充：请选择\n用户回答：取消任务'
        await self.send(command(wrapped, task='failed-operation', message='failed-operation'))
        await self.settle()
        final = await self.send(command('', task='failed-operation', message='get-failed-operation', kind='get'))
        self.assertEqual(final.result.status.state.value, 'failed')
        self.assertEqual(json.loads(final.result.products[0].dataItems[0].text)['status'], 'failed')

    async def test_restart_after_order_commit_repairs_business_completion(self):
        from leader_external_flow import handle_external_command
        from leader_rpc_runtime import LeaderRpcRuntime
        from stage2_domain import preview_resources, reserve_plan_resources, create_work_order_for_plan
        self.runtime.command_handler = handle_external_command
        actions = []
        async def partner(kind, action, payload, **kwargs):
            actions.append(action)
            if action == "query_resources":
                return {"ok": True, "result": preview_resources(payload["request_id"])}
            if action == "reserve_resources":
                reserve_plan_resources(payload["plan_id"])
                return {"ok": True, "result": {}}
            if action == "create_work_order":
                create_work_order_for_plan(payload["plan_id"], payload["idempotency_key"])
                raise asyncio.CancelledError()
            self.fail("Committed order must not be compensated")
        with patch.dict(os.environ, {"GONGWEI_DISCOVERY_URL": "https://discovery.test", "LLM_BASE_URL": ""}), patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": {"aic": "resource"}}), patch("leader_external_flow.call_partner", new=partner):
            await self.send(command("水泵001异常，明天下午两点开始，预计一小时"))
            await self.settle()
            await self.send(command("确认这个方案并创建工单。", message="confirm-commit", kind="continue"))
            with self.assertRaises(asyncio.CancelledError):
                await self.settle()
            await self.runtime.close()
            self.runtime = LeaderRpcRuntime(leader_aic="leader", state_path=self.state, command_handler=handle_external_command)
            await self.runtime.start()
            await self.settle()
        response = await self.send(command("", message="after-order-restart", kind="get"))
        self.assertEqual(response.result.status.state.value, "completed")
        self.assertEqual(actions.count("create_work_order"), 1)
        with connect_db() as business:
            self.assertEqual(business.execute("SELECT status FROM agent_tasks WHERE task_id='t1'").fetchone()[0], "completed")
            self.assertEqual(business.execute("SELECT COUNT(*) FROM user_confirmations WHERE task_id='t1'").fetchone()[0], 1)

    async def _exercise_order_timeout_reconciliation(self, commit_at):
        from leader_external_flow import handle_external_command
        from stage2_domain import preview_resources, reserve_plan_resources, release_plan_resources, create_work_order_for_plan
        self.runtime.command_handler = handle_external_command
        actions = []
        async def partner(kind, action, payload, **kwargs):
            actions.append(action)
            if action == "query_resources":
                return {"ok": True, "result": preview_resources(payload["request_id"])}
            if action == "reserve_resources":
                reserve_plan_resources(payload["plan_id"])
            elif action == "create_work_order":
                if commit_at == "create":
                    create_work_order_for_plan(payload["plan_id"], payload["idempotency_key"])
                raise TimeoutError("order response lost")
            elif action == "release_resources":
                if commit_at == "release" and actions.count("release_resources") == 1:
                    create_work_order_for_plan(payload["plan_id"], "dingdang-t1")
                release_plan_resources(payload["plan_id"])
            return {"ok": True, "result": {}}
        with patch.dict(os.environ, {"GONGWEI_DISCOVERY_URL": "https://discovery.test", "LLM_BASE_URL": ""}), patch("leader_external_flow.PartnerResolver.resolve", return_value={"selected": {"aic": "partner"}}), patch("leader_external_flow.call_partner", new=partner):
            await self.send(command("水泵001异常，明天下午两点开始，预计一小时"))
            await self.settle()
            await self.send(command("确认这个方案并创建工单。", message="confirm-timeout", kind="continue"))
            await asyncio.wait_for(self.settle(), 3)
        response = await self.send(command("", message="after-timeout", kind="get"))
        self.assertEqual(response.result.status.state.value, "completed")
        self.assertEqual(actions.count("create_work_order"), 1)
        with connect_db() as business:
            self.assertEqual(business.execute("SELECT status FROM agent_tasks WHERE task_id='t1'").fetchone()[0], "completed")
            self.assertEqual(business.execute("SELECT COUNT(*) FROM user_confirmations WHERE task_id='t1'").fetchone()[0], 1)
            self.assertEqual(business.execute("SELECT COUNT(*) FROM work_orders WHERE status='confirmed'").fetchone()[0], 1)
            self.assertEqual(business.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 3)

    async def test_order_commit_then_timeout_reconciles_completed(self):
        await self._exercise_order_timeout_reconciliation("create")

    async def test_order_committed_before_release_keeps_reserved_resources(self):
        await self._exercise_order_timeout_reconciliation("release")

    async def test_different_senders_can_use_their_own_same_message_id(self):
        from leader_external_flow import handle_external_command
        self.runtime.command_handler = handle_external_command
        with patch.dict(os.environ, {"LLM_BASE_URL": ""}):
            await self.send(command())
            await self.settle()
            await self.send(command(task="other-task", session="other-session", sender="other"))
            await self.settle()
        second = await self.send(command("", message="get-other", task="other-task", session="other-session", sender="other", kind="get"))
        self.assertEqual(second.result.status.state.value, "awaiting-input")

    async def test_failure_and_cancel_are_durable_terminal_states(self):
        self.handler.side_effect = RuntimeError("unavailable")
        await self.send(command())
        await self.settle()
        failed = await self.send(command("", message="get", kind="get"))
        self.assertEqual(failed.result.status.state.value, "failed")
        self.handler.side_effect = None
        self.handler.return_value = {"state": "completed", "result": {"status": "cancelled"}}
        await self.send(command(message="new", task="t2"))
        await self.settle()
        # A separate task can be canceled while still awaiting input.
        self.handler.return_value = {"state": "awaiting_input", "result": {}}
        await self.send(command(message="new3", task="t3"))
        await self.settle()
        await self.send(command("", message="cancel", task="t3", kind="cancel"))
        await self.settle()
        canceled = await self.send(command("", message="getc", task="t3", kind="get"))
        self.assertEqual(canceled.result.status.state.value, "canceled")

    async def test_sdk_http_route_rejects_missing_peer_and_forged_headers(self):
        import httpx
        from leader_rpc_runtime import create_app
        app = create_app(self.runtime)
        body = RpcRequest(id="wire", params=RpcRequestParams(command=command())).model_dump(mode="json")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
            response = await client.post("/rpc", json=body, headers={"X-Forwarded-Client-Cert": "caller", "X-Peer-Aic": "caller"})
        self.assertEqual(response.json()["error"]["code"], -32008)
        self.handler.assert_not_awaited()

    async def test_real_loopback_mtls_binds_sdk_sender_to_peer_certificate(self):
        import httpx
        import uvicorn
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
        from acps_sdk.aip.aip_peer_cert import AipPeerCertH11Protocol
        from leader_rpc_runtime import create_app
        root = Path(self.temp.name)
        leader = "1.2.156.3088.1.TEST.LEADER.1.1.0000"
        caller = "1.2.156.3088.1.TEST.CALLER.1.1.0000"
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "temporary-offline-test-ca")])
        now = datetime.now(timezone.utc)
        def builder(subject, public_key):
            return (x509.CertificateBuilder().subject_name(subject).issuer_name(ca_name).public_key(public_key)
                    .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                    .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
                    .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False))
        ca = builder(ca_name, ca_key.public_key()).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=None, decipher_only=None), critical=True).sign(ca_key, hashes.SHA256())
        (root / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        def issue(stem, aic, eku, dns=None):
            key = ec.generate_private_key(ec.SECP256R1())
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, aic)])
            sans = [x509.UniformResourceIdentifier(f"acps://{aic}")]
            if dns:
                sans.append(x509.DNSName(dns))
            cert = builder(subject, key.public_key()).add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True).add_extension(x509.ExtendedKeyUsage([eku]), critical=False).add_extension(x509.SubjectAlternativeName(sans), critical=False).sign(ca_key, hashes.SHA256())
            (root / f"{stem}.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            (root / f"{stem}.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        issue("server", leader, ExtendedKeyUsageOID.SERVER_AUTH, "localhost")
        issue("client", caller, ExtendedKeyUsageOID.CLIENT_AUTH)
        self.runtime.leader_aic = leader
        telemetry_env = patch.dict(os.environ, {'GONGWEI_AMP_METADATA_ENABLED': '1', 'GONGWEI_AMP_LOG_DIR': str(root / 'amp')})
        telemetry_env.start()
        self.addCleanup(telemetry_env.stop)
        app = create_app(self.runtime)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, http=AipPeerCertH11Protocol, proxy_headers=False,
            ssl_certfile=str(root / "server.pem"), ssl_keyfile=str(root / "server.key"), ssl_ca_certs=str(root / "ca.pem"),
            ssl_cert_reqs=ssl.CERT_REQUIRED, ssl_version=ssl.PROTOCOL_TLS_SERVER, log_level="error", lifespan="on"))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if serving.done():
                        await serving
                    await asyncio.sleep(0.01)
            context = ssl.create_default_context(cafile=str(root / "ca.pem"))
            context.load_cert_chain(str(root / "client.pem"), str(root / "client.key"))
            async with httpx.AsyncClient(verify=context, trust_env=False, base_url=f"https://localhost:{port}") as client:
                forged = RpcRequest(id="forged", params=RpcRequestParams(command=command(sender=leader))).model_dump(mode="json")
                response = await client.post("/rpc", json=forged)
                self.assertEqual(response.json()["error"]["code"], -32009)
                valid = RpcRequest(id="valid", params=RpcRequestParams(command=command(sender=caller))).model_dump(mode="json")
                upstream_trace = "a" * 32
                upstream_span = "b" * 16
                response = await client.post("/rpc", json=valid,
                                             headers={"traceparent": f"00-{upstream_trace}-{upstream_span}-01"})
                self.assertEqual(response.json()["result"]["senderId"], leader)
                self.assertEqual(response.json()["result"]["status"]["state"], "accepted")
            records = [json.loads(line) for path in (root / 'amp').glob('amp_access_*.jsonl') for line in path.read_text().splitlines()]
            self.assertEqual(len(records), 1, 'only SDK-authenticated valid RPC should produce a callee access record')
            self.assertEqual(records[0]['correlation_id'], 't1')
            self.assertEqual(records[0]['body']['caller']['aic'], caller)
            self.assertNotIn('headers', records[0]['body']['request'])
            self.assertEqual(records[0]['trace_id'], upstream_trace)
            self.assertEqual(records[0]['parent_span_id'], upstream_span)
            self.assertNotEqual(records[0]['span_id'], upstream_span)
            no_cert = ssl.create_default_context(cafile=str(root / "ca.pem"))
            async with httpx.AsyncClient(verify=no_cert, trust_env=False, base_url=f"https://localhost:{port}") as client:
                with self.assertRaises(httpx.RequestError):
                    await client.post("/rpc", json=valid)
            await self.settle()
            self.handler.assert_awaited_once()
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, 5)
            listener.close()


class StartupTests(unittest.TestCase):
    def test_entry_exists_and_local_mode_is_rejected_before_configuration(self):
        self.assertIsNotNone(importlib.util.find_spec("run_leader_rpc"), "formal TLS entry is missing")
        import run_leader_rpc
        with patch.dict(os.environ, {"GONGWEI_TRANSPORT_MODE": "local_rpc"}), patch.object(run_leader_rpc, "_load_env_file"), patch.object(run_leader_rpc, "configure_platform_environment") as configure:
            with self.assertRaisesRegex(RuntimeError, "platform_mq_inbox"):
                run_leader_rpc.build_server_config()
        configure.assert_not_called()

    def test_server_config_requires_peer_cert_and_disables_proxy_headers(self):
        self.assertIsNotNone(importlib.util.find_spec("run_leader_rpc"), "formal TLS entry is missing")
        import run_leader_rpc
        from acps_sdk.aip.aip_peer_cert import AipPeerCertH11Protocol
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"GONGWEI_TRANSPORT_MODE": "platform_mq_inbox", "GONGWEI_LEADER_RPC_STATE_DB": str(Path(temp) / "state.db"), "GONGWEI_LEADER_RPC_HOST": "127.0.0.1", "GONGWEI_LEADER_RPC_PORT": "18443"}), patch.object(run_leader_rpc, "_load_env_file"), patch.object(run_leader_rpc, "configure_platform_environment", return_value={"aic": "leader", "cert_file": "client.crt", "key_file": "client.key"}) as configure, patch.object(run_leader_rpc, "require_mq_configuration"), patch.object(run_leader_rpc, "_validate_server_tls", return_value={"certfile": "server.crt", "keyfile": "server.key", "ca_certs": "trust.pem"}):
            config = run_leader_rpc.build_server_config()
        configure.assert_called_once_with("leader")
        self.assertEqual((config.host, config.port), ("127.0.0.1", 18443))
        self.assertFalse(config.proxy_headers)
        self.assertEqual(config.ssl_cert_reqs, ssl.CERT_REQUIRED)
        self.assertEqual(config.ssl_version, ssl.PROTOCOL_TLS_SERVER)
        self.assertIs(config.http, AipPeerCertH11Protocol)
        self.assertEqual(config.ssl_certfile, "server.crt")

    def test_server_certificate_cannot_reuse_client_certificate(self):
        self.assertIsNotNone(importlib.util.find_spec("run_leader_rpc"), "formal TLS entry is missing")
        import run_leader_rpc
        with tempfile.TemporaryDirectory() as temp:
            cert = Path(temp) / "client.crt"
            key = Path(temp) / "client.key"
            cert.touch()
            key.touch()
            with patch.dict(os.environ, {"GONGWEI_LEADER_SERVER_CERT": str(cert), "GONGWEI_LEADER_SERVER_KEY": str(key), "GONGWEI_LEADER_CLIENT_CA": str(cert)}):
                with self.assertRaisesRegex(RuntimeError, "独立"):
                    run_leader_rpc._validate_server_tls({"cert_file": str(cert), "key_file": str(key)})


if __name__ == "__main__":
    unittest.main()

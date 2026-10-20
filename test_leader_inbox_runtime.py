import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch


class LeaderInboxRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"GONGWEI_STAGE2_DB": str(Path(self.temp.name) / "inbox.db"), "LLM_BASE_URL": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    async def test_runtime_uses_official_partner_inbox_and_keeps_external_ids(self):
        from leader_inbox_runtime import LeaderInboxRuntime
        from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem
        with patch("leader_inbox_runtime.OfficialMqPartnerRuntime") as runtime_cls:
            runtime = runtime_cls.return_value
            runtime.start_inbox = AsyncMock()
            runtime.client.send_task_result = AsyncMock()
            handler = AsyncMock(return_value={"state": "awaiting_completion"})
            inbox = LeaderInboxRuntime(leader_aic="leader", rabbitmq_config={}, command_handler=handler)
            await inbox.start()
            runtime.set_command_handler.assert_called_once()
            self.assertTrue(runtime.start_inbox.await_count)
            command = TaskCommand(
                id="message-1", sentAt="2026-10-06T00:00:00Z", senderRole="leader", senderId="dingdang",
                sessionId="session-1", taskId="task-1", command=TaskCommandType.Start,
                dataItems=[TextDataItem(text='{"text":"水泵001异常"}')],
            )
            callback = runtime.set_command_handler.call_args.args[0]
            await callback(command, True)
            handler.assert_awaited_once_with(command)
            self.assertEqual([call.args[2].value for call in runtime.client.send_task_result.await_args_list], ["accepted", "working", "awaiting-completion"])
            self.assertEqual(runtime.client.send_task_result.await_args_list[-1].args[:2], ("task-1", "session-1"))

    async def test_runtime_returns_explicit_failure_reason_through_sdk(self):
        from leader_inbox_runtime import LeaderInboxRuntime
        from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem
        with patch("leader_inbox_runtime.OfficialMqPartnerRuntime") as runtime_cls:
            runtime = runtime_cls.return_value
            runtime.start_inbox = AsyncMock()
            runtime.client.send_task_result = AsyncMock()
            handler = AsyncMock(return_value={"state": "failed", "error": "在线发现 HTTP 404"})
            inbox = LeaderInboxRuntime(leader_aic="leader", rabbitmq_config={}, command_handler=handler)
            await inbox.start()
            command = TaskCommand(id="message-f", sentAt="2026-10-06T00:00:00Z", senderRole="leader", senderId="dingdang", sessionId="session-f", taskId="task-f", command=TaskCommandType.Start, dataItems=[TextDataItem(text="{}")])
            callback = runtime.set_command_handler.call_args.args[0]
            await callback(command, True)
            final = runtime.client.send_task_result.await_args_list[-1]
            self.assertEqual(final.args[2].value, "failed")
            self.assertIn("在线发现 HTTP 404", final.kwargs["status_data_items"][0].text)

    async def test_fresh_inbox_start_initializes_real_business_conversation(self):
        from leader_inbox_runtime import LeaderInboxRuntime
        from leader_external_flow import handle_external_command
        from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem
        from stage2_db import connect_db
        with patch("leader_inbox_runtime.OfficialMqPartnerRuntime") as runtime_cls:
            runtime_cls.return_value.client.send_task_result = AsyncMock()
            inbox = LeaderInboxRuntime(leader_aic="leader", rabbitmq_config={}, command_handler=handle_external_command)
            command = TaskCommand(id="fresh-message", sentAt="2026-10-07T00:00:00Z", senderRole="leader", senderId="caller", sessionId="fresh-session", taskId="fresh-task", command=TaskCommandType.Start, dataItems=[TextDataItem(text="水泵001异常")])
            try:
                await inbox._handle_command(command)
            except Exception as exc:
                self.fail(f"Fresh MQ start must create the conversation before handling it: {exc}")
            final = runtime_cls.return_value.client.send_task_result.await_args_list[-1]
            self.assertEqual(final.args[:2], ("fresh-task", "fresh-session"))
            self.assertEqual(final.args[2].value, "awaiting-input")
            with connect_db() as db:
                self.assertEqual(db.execute("SELECT session_id FROM agent_tasks WHERE task_id='fresh-task'").fetchone()[0], "fresh-session")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM agent_messages").fetchone()[0], 1)

    async def test_inbox_start_refuses_browser_task_or_session_adoption(self):
        from agentic_core import create_conversation
        from leader_inbox_runtime import LeaderInboxRuntime
        from leader_external_flow import handle_external_command
        from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem
        create_conversation(session_id="browser-session", task_id="browser-task")
        with patch("leader_inbox_runtime.OfficialMqPartnerRuntime") as runtime_cls:
            runtime_cls.return_value.client.send_task_result = AsyncMock()
            inbox = LeaderInboxRuntime(leader_aic="leader", rabbitmq_config={}, command_handler=handle_external_command)
            for task_id in ("browser-task", "new-inbox-task"):
                command = TaskCommand(id="adopt-" + task_id, sentAt="2026-10-07T00:00:00Z", senderRole="leader", senderId="caller", sessionId="browser-session", taskId=task_id, command=TaskCommandType.Start, dataItems=[TextDataItem(text="水泵001异常")])
                with self.subTest(task_id=task_id), self.assertRaisesRegex(ValueError, "属于|所有者|owner|entry"):
                    await inbox._handle_command(command)

    async def test_inbox_owner_survives_restart_and_cancel_is_terminal(self):
        from leader_inbox_runtime import LeaderInboxRuntime
        from leader_external_flow import handle_external_command
        from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem
        from stage2_db import connect_db
        command = TaskCommand(id="start", sentAt="2026-10-07T00:00:00Z", senderRole="leader", senderId="caller", sessionId="session", taskId="task", command=TaskCommandType.Start, dataItems=[TextDataItem(text="水泵001异常")])
        with patch("leader_inbox_runtime.OfficialMqPartnerRuntime") as runtime_cls:
            runtime_cls.return_value.client.send_task_result = AsyncMock()
            inbox = LeaderInboxRuntime(leader_aic="leader", rabbitmq_config={}, command_handler=handle_external_command)
            try:
                await inbox._handle_command(command)
            except Exception as exc:
                self.fail(f"Fresh MQ start must succeed before ownership/cancel checks: {exc}")
            restarted = LeaderInboxRuntime(leader_aic="leader", rabbitmq_config={}, command_handler=handle_external_command)
            attacker = command.model_copy(update={"id": "attack", "senderId": "other", "command": TaskCommandType.Continue})
            with self.assertRaisesRegex(ValueError, "属于|所有者|owner|entry"):
                await restarted._handle_command(attacker)
            cancel = command.model_copy(update={"id": "cancel", "command": TaskCommandType.Cancel, "dataItems": []})
            await restarted._handle_command(cancel)
            self.assertEqual(runtime_cls.return_value.client.send_task_result.await_args_list[-1].args[2].value, "canceled")
            retry = command.model_copy(update={"id": "after-cancel", "command": TaskCommandType.Continue})
            before_retry = runtime_cls.return_value.client.send_task_result.await_count
            await restarted._handle_command(retry)
            self.assertEqual([call.args[2].value for call in runtime_cls.return_value.client.send_task_result.await_args_list[before_retry:]], ["canceled"])
            self.assertEqual(runtime_cls.return_value.client.send_task_result.await_args_list[-1].args[2].value, "canceled")
            with connect_db() as db:
                self.assertEqual(db.execute("SELECT status FROM agent_tasks WHERE task_id='task'").fetchone()[0], "cancelled")


if __name__ == "__main__":
    unittest.main()

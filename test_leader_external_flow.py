import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem


class LeaderExternalFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_flow_preserves_ids_and_confirmation_gate(self):
        from agentic_core import create_conversation
        from leader_external_flow import handle_external_command
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "flow.db"
            os.environ["GONGWEI_STAGE2_DB"] = str(db)
            os.environ["GONGWEI_DISCOVERY_URL"] = "https://discovery.test"
            session_id, task_id = "ding-session-1", "ding-task-1"
            create_conversation(session_id=session_id, task_id=task_id)
            resolver = {"selected": {"aic": "resource-aic"}, "source": "discovery_server", "candidates": [], "filtered": [], "error": None}
            def command(text, message_id, task=task_id):
                return TaskCommand(id=message_id, sentAt="2026-10-06T00:00:00Z", senderRole="leader", senderId="dingdang", sessionId=session_id, taskId=task, command=TaskCommandType.Start, dataItems=[TextDataItem(text=text)])
            try:
                first = await handle_external_command(command("水泵001运行异常，帮我安排明天下午检查。", "m-1"))
                self.assertEqual(first["state"], "awaiting_input")
                self.assertEqual(first['result']['nextCommand'], 'continue')
                with patch("leader_external_flow.PartnerResolver.resolve", return_value=resolver), patch("leader_external_flow.call_partner", new=AsyncMock(side_effect=[{"ok": True, "result": {"available": True, "workers": [{"id": "worker-001"}], "inventory": [{"id": "tool-inspection-kit"}, {"id": "part-seal-ring"}]}}])) as call:
                    second = await handle_external_command(command("下午两点开始，预计一小时，需要泵体检查技能。", "m-2"))
                self.assertEqual(second["state"], "awaiting_input")
                self.assertTrue(second["result"]["requiresConfirmation"])
                self.assertIn('确认', second['question'])
                self.assertEqual(second['result']['nextCommand'], 'continue')
                self.assertIn('14:00', second['question'])
                self.assertIn('60', second['question'])
                self.assertEqual(call.await_args.kwargs["session_id"], session_id)
                self.assertEqual(call.await_args.kwargs["task_id"], f"{task_id}:resource:01")
                with patch("leader_external_flow.PartnerResolver.resolve", return_value=resolver), patch("leader_external_flow.call_partner", new=AsyncMock(side_effect=[{"ok": True, "result": {"reserved": True}}, {"ok": True, "result": {"work_order": {"number": "WO-1"}}}])):
                    third = await handle_external_command(command("确认这个方案并创建工单。", "m-3"))
                self.assertEqual(third["state"], "completed")
                self.assertEqual(third["result"]["taskId"], task_id)
            finally:
                os.environ.pop("GONGWEI_STAGE2_DB", None)
                os.environ.pop("GONGWEI_DISCOVERY_URL", None)


if __name__ == "__main__":
    unittest.main()



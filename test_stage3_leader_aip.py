"""Contract checks for the Leader AIP endpoint introduced in stage three."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from stage2_db import initialize_database


def rpc_payload(action: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "rpc",
        "id": str(uuid.uuid4()),
        "params": {"command": {
            "type": "task-command",
            "id": "cmd-" + str(uuid.uuid4()),
            "sentAt": "2026-10-03T00:00:00+00:00",
            "senderRole": "leader",
            "senderId": "stage2-gongwei-leader",
            "sessionId": "session-stage3",
            "command": "start",
            "taskId": "task-" + str(uuid.uuid4()),
            "dataItems": [{"type": "text", "text": json.dumps(action, ensure_ascii=False)}],
        }},
    }


class Stage3LeaderAipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["GONGWEI_STAGE2_DB"] = str(Path(self.temp.name) / "stage3.db")
        initialize_database()
        from web_app import app

        self.client = TestClient(app, client=("127.0.0.1", 50002))

    def tearDown(self):
        os.environ.pop("GONGWEI_STAGE2_DB", None)
        self.temp.cleanup()

    def test_create_request_and_timeline_are_aip_results(self):
        payload = {
            "pump_id": "pump-001",
            "work_date": (date.today() + timedelta(days=1)).isoformat(),
            "start_time": "09:00",
            "duration_minutes": 60,
            "description": "Leader AIP 合同测试",
        }
        created = self.client.post("/rpc", json=rpc_payload({"action": "create_inspection_request", "request": payload}))
        self.assertEqual(created.status_code, 200)
        result = created.json()["result"]
        self.assertEqual(result["senderId"], "stage2-gongwei-leader")
        data = json.loads(result["products"][0]["dataItems"][0]["text"])
        self.assertTrue(data["ok"])
        request_id = data["result"]["request"]["id"]

        timeline = self.client.post("/rpc", json=rpc_payload({"action": "get_timeline", "request_id": request_id}))
        timeline_data = json.loads(timeline.json()["result"]["products"][0]["dataItems"][0]["text"])
        self.assertTrue(timeline_data["ok"])
        self.assertEqual(timeline_data["result"]["request"]["id"], request_id)

    def test_unknown_action_is_failed_task(self):
        response = self.client.post("/rpc", json=rpc_payload({"action": "not_supported"}))
        result = response.json()["result"]
        self.assertEqual(result["status"]["state"], "failed")
        data = json.loads(result["products"][0]["dataItems"][0]["text"])
        self.assertFalse(data["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

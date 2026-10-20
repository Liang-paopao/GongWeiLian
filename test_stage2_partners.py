"""AIP contract tests for both stage two Partners."""
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
from stage2_domain import create_inspection_request, create_plan


def rpc_payload(action: dict, task_id: str | None = None) -> dict:
    task_id = task_id or "task-" + str(uuid.uuid4())
    return {
        "jsonrpc": "2.0", "method": "rpc", "id": str(uuid.uuid4()),
        "params": {"command": {
            "type": "task-command", "id": "cmd-" + str(uuid.uuid4()),
            "sentAt": "2026-10-03T00:00:00+00:00", "senderRole": "leader",
            "senderId": "stage2-gongwei-leader", "sessionId": "session-stage2",
            "command": "start", "taskId": task_id,
            "dataItems": [{"type": "text", "text": json.dumps(action, ensure_ascii=False)}],
        }},
    }


class Stage2PartnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["GONGWEI_STAGE2_DB"] = str(Path(self.temp.name) / "stage2.db")
        initialize_database()
        self.date = (date.today() + timedelta(days=1)).isoformat()
        payload = {"pump_id": "pump-001", "work_date": self.date, "start_time": "09:00", "duration_minutes": 60, "description": "Partner测试"}
        self.request = create_inspection_request(payload)
        self.plan = create_plan(self.request["id"])
        from resource_partner_v1 import app as resource_app
        from work_order_partner_v1 import app as work_order_app
        self.resource = TestClient(resource_app, client=("127.0.0.1", 50000))
        self.work_order = TestClient(work_order_app, client=("127.0.0.1", 50001))

    def tearDown(self):
        os.environ.pop("GONGWEI_STAGE2_DB", None)
        self.temp.cleanup()

    def test_resource_partner_query_and_reserve_are_aip_results(self):
        query = self.resource.post("/rpc", json=rpc_payload({"action": "query_resources", "request_id": self.request["id"]}))
        self.assertEqual(query.status_code, 200)
        query_result = query.json()["result"]
        self.assertEqual(query_result["senderId"], "stage2-gongwei-resource")
        query_data = json.loads(query_result["products"][0]["dataItems"][0]["text"])
        self.assertTrue(query_data["ok"])
        reserve = self.resource.post("/rpc", json=rpc_payload({"action": "reserve_resources", "plan_id": self.plan["id"]}))
        reserve_data = json.loads(reserve.json()["result"]["products"][0]["dataItems"][0]["text"])
        self.assertTrue(reserve_data["ok"])
        self.assertEqual(len(reserve_data["result"]["reservations"]), 3)

    def test_work_order_partner_creates_and_cancels_via_aip(self):
        self.resource.post("/rpc", json=rpc_payload({"action": "reserve_resources", "plan_id": self.plan["id"]}))
        created = self.work_order.post("/rpc", json=rpc_payload({"action": "create_work_order", "plan_id": self.plan["id"], "idempotency_key": "partner-create-001"}))
        created_data = json.loads(created.json()["result"]["products"][0]["dataItems"][0]["text"])
        self.assertTrue(created_data["ok"])
        work_order_id = created_data["result"]["work_order"]["id"]
        cancelled = self.work_order.post("/rpc", json=rpc_payload({"action": "cancel_work_order", "work_order_id": work_order_id}))
        cancelled_data = json.loads(cancelled.json()["result"]["products"][0]["dataItems"][0]["text"])
        self.assertEqual(cancelled_data["result"]["work_order"]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main(verbosity=2)

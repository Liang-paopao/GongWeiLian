from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stage2_db import initialize_database
from stage2_domain import create_inspection_request, create_plan


class BusinessActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "stage2.db"
        initialize_database(self.db_path)
        self.payload = {
            "pump_id": "pump-001",
            "work_date": (date.today() + timedelta(days=1)).isoformat(),
            "start_time": "09:00",
            "duration_minutes": 60,
            "description": "共享动作测试",
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_resource_and_work_order_actions_share_one_dispatch_contract(self):
        from stage2_business_actions import dispatch_business_action

        request = create_inspection_request(self.payload, self.db_path)
        preview = dispatch_business_action("resource", "query_resources", {"request_id": request["id"]}, db_path=self.db_path)
        self.assertTrue(preview["ok"])
        plan = create_plan(request["id"], self.db_path)
        reserved = dispatch_business_action("resource", "reserve_resources", {"plan_id": plan["id"]}, db_path=self.db_path)
        self.assertTrue(reserved["ok"])
        created = dispatch_business_action("workorder", "create_work_order", {"plan_id": plan["id"], "idempotency_key": "shared-action"}, db_path=self.db_path)
        self.assertTrue(created["ok"])
        self.assertEqual(created["result"]["work_order"]["plan_id"], plan["id"])

    def test_unknown_partner_action_is_reported_as_business_failure(self):
        from stage2_business_actions import dispatch_business_action

        result = dispatch_business_action("resource", "invented", {}, db_path=self.db_path)
        self.assertFalse(result["ok"])
        self.assertIn("不支持", result["error"])


if __name__ == "__main__":
    unittest.main()

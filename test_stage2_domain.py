"""Stage two domain tests. These are intentionally written before the implementation."""
from __future__ import annotations

import json
import tempfile
import unittest
import sqlite3
from unittest.mock import patch
from datetime import date, timedelta
from pathlib import Path

from stage2_db import connect_db, initialize_database, reopen_database
from stage2_domain import (
    DomainError,
    cancel_work_order,
    confirm_plan,
    create_inspection_request,
    create_plan,
    create_work_order_for_plan,
    get_request,
    get_work_order,
    adjust_inventory_quantity,
    list_inventory,
    list_workers,
    preview_resources,
    release_plan_resources,
    reserve_plan_resources,
)


class Stage2DomainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "stage2.db"
        initialize_database(self.db_path)
        self.work_date = (date.today() + timedelta(days=1)).isoformat()

    def tearDown(self):
        self.temp.cleanup()

    def request_payload(self, **changes):
        payload = {
            "pump_id": "pump-001",
            "work_date": self.work_date,
            "start_time": "09:00",
            "duration_minutes": 60,
            "description": "检查泵体振动和密封状态",
        }
        payload.update(changes)
        return payload

    def test_seed_has_three_pumps_workers_and_inventory(self):
        self.assertEqual(len(list_workers(self.db_path)), 6)
        self.assertGreaterEqual(len(list_inventory(self.db_path)), 8)
        with connect_db(self.db_path) as conn:
            self.assertEqual(conn.execute("select count(*) from pumps").fetchone()[0], 3)

    def test_missing_input_is_awaiting_input_with_field_names(self):
        request = create_inspection_request({"pump_id": "pump-001"}, self.db_path)
        self.assertEqual(request["status"], "awaiting_input")
        self.assertEqual(set(request["missing_fields"]), {"work_date", "start_time", "duration_minutes", "description"})

    def test_time_range_is_rejected(self):
        with self.assertRaisesRegex(DomainError, "结束时间"):
            create_inspection_request(self.request_payload(start_time="23:30", duration_minutes=120), self.db_path)

    def test_plan_confirm_creates_one_work_order_and_reservations(self):
        request = create_inspection_request(self.request_payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        self.assertEqual(plan["status"], "proposed")
        first = confirm_plan(plan["id"], "confirm-001", self.db_path)
        second = confirm_plan(plan["id"], "confirm-001", self.db_path)
        self.assertEqual(first["work_order"]["id"], second["work_order"]["id"])
        self.assertEqual(get_work_order(first["work_order"]["id"], self.db_path)["status"], "confirmed")
        with connect_db(self.db_path) as conn:
            self.assertEqual(conn.execute("select count(*) from work_orders").fetchone()[0], 1)
            self.assertEqual(conn.execute("select count(*) from reservations where status='active'").fetchone()[0], 3)

    def test_existing_plan_is_returned_without_nested_write_lock(self):
        request = create_inspection_request(self.request_payload(), self.db_path)
        original = create_plan(request["id"], self.db_path)
        real_connect = sqlite3.connect
        def short_lock_timeout(*args, **kwargs):
            return real_connect(*args, **{**kwargs, "timeout": 0.1})
        with patch("stage2_db.sqlite3.connect", side_effect=short_lock_timeout):
            try:
                repeated = create_plan(request["id"], self.db_path)
            except sqlite3.OperationalError as exc:
                self.fail(f"Repeated create_plan must return after releasing its write transaction: {exc}")
        self.assertEqual(repeated["id"], original["id"])

    def test_worker_conflict_does_not_create_success(self):
        first = create_inspection_request(self.request_payload(), self.db_path)
        first_plan = create_plan(first["id"], self.db_path)
        second = create_inspection_request(self.request_payload(description="第二个任务"), self.db_path)
        second_plan = create_plan(second["id"], self.db_path)
        confirm_plan(first_plan["id"], "confirm-first", self.db_path)
        with self.assertRaisesRegex(DomainError, "不可用|没有可用"):
            confirm_plan(second_plan["id"], "confirm-second", self.db_path)
        with connect_db(self.db_path) as conn:
            self.assertEqual(conn.execute("select count(*) from work_orders").fetchone()[0], 1)

    def test_tool_conflict_at_same_time_does_not_create_success(self):
        with connect_db(self.db_path) as conn:
            conn.execute("update inventory_items set available_qty=1 where id='tool-inspection-kit'")
        first = create_inspection_request(self.request_payload(), self.db_path)
        second = create_inspection_request(self.request_payload(description="另一个检查任务"), self.db_path)
        first_plan = create_plan(first["id"], self.db_path)
        second_plan = create_plan(second["id"], self.db_path)
        reserve_plan_resources(first_plan["id"], self.db_path)
        with self.assertRaisesRegex(DomainError, "库存"):
            reserve_plan_resources(second_plan["id"], self.db_path)
        release_plan_resources(first_plan["id"], self.db_path)
        with connect_db(self.db_path) as conn:
            self.assertEqual(conn.execute("select available_qty from inventory_items where id='tool-inspection-kit'").fetchone()[0], 1)

    def test_no_staff_for_evening_slot(self):
        request = create_inspection_request(self.request_payload(start_time="19:00", duration_minutes=60), self.db_path)
        preview = preview_resources(request["id"], self.db_path)
        self.assertFalse(preview["available"])
        self.assertIn("没有可用人员", preview["reasons"])

    def test_requested_skill_filters_the_candidate_workers(self):
        request = create_inspection_request(self.request_payload(required_skill="electrical_inspection"), self.db_path)
        preview = preview_resources(request["id"], self.db_path)
        self.assertEqual(preview["required_skill"], "electrical_inspection")
        self.assertEqual([worker["id"] for worker in preview["workers"]], ["worker-02", "worker-06"])
        plan = create_plan(request["id"], self.db_path)
        self.assertEqual(plan["worker_id"], "worker-02")

    def test_unknown_requested_skill_does_not_fall_back_to_pump_workers(self):
        request = create_inspection_request(self.request_payload(required_skill="nonexistent_special_skill"), self.db_path)
        preview = preview_resources(request["id"], self.db_path)
        self.assertFalse(preview["available"])
        self.assertEqual(preview["workers"], [])

    def test_existing_chinese_pump_skill_maps_to_seed_skill(self):
        request = create_inspection_request(self.request_payload(required_skill="泵体检查"), self.db_path)
        preview = preview_resources(request["id"], self.db_path)
        self.assertTrue(preview["available"])
        self.assertEqual(preview["required_skill"], "pump_inspection")

    def test_inventory_shortage_does_not_create_success(self):
        with connect_db(self.db_path) as conn:
            conn.execute("update inventory_items set available_qty=0 where id='tool-inspection-kit'")
            conn.commit()
        request = create_inspection_request(self.request_payload(), self.db_path)
        with self.assertRaisesRegex(DomainError, "库存"):
            create_plan(request["id"], self.db_path)

    def test_cancel_releases_resources_and_is_idempotent(self):
        request = create_inspection_request(self.request_payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        created = confirm_plan(plan["id"], "confirm-cancel", self.db_path)
        cancelled = cancel_work_order(created["work_order"]["id"], self.db_path)
        self.assertEqual(cancelled["status"], "cancelled")
        cancel_work_order(created["work_order"]["id"], self.db_path)
        with connect_db(self.db_path) as conn:
            self.assertEqual(conn.execute("select count(*) from reservations where status='active'").fetchone()[0], 0)
            self.assertEqual(conn.execute("select available_qty from inventory_items where id='tool-inspection-kit'").fetchone()[0], 5)

    def test_work_order_failure_can_release_reserved_resources(self):
        request = create_inspection_request(self.request_payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        reserve_plan_resources(plan["id"], self.db_path)
        with self.assertRaisesRegex(DomainError, "创建失败"):
            create_work_order_for_plan(plan["id"], "failed-order-001", self.db_path, force_failure=True)
        release_plan_resources(plan["id"], self.db_path)
        with connect_db(self.db_path) as conn:
            self.assertEqual(conn.execute("select count(*) from reservations where status='active'").fetchone()[0], 0)

    def test_reopen_keeps_business_rows(self):
        request = create_inspection_request(self.request_payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        confirm_plan(plan["id"], "confirm-reopen", self.db_path)
        reopen_database(self.db_path)
        self.assertEqual(get_request(request["id"], self.db_path)["status"], "confirmed")

    def test_inventory_adjustment_changes_available_and_total_with_audit(self):
        before = next(item for item in list_inventory(self.db_path) if item["id"] == "tool-inspection-kit")
        increased = adjust_inventory_quantity("tool-inspection-kit", 2, self.db_path, actor="operator")
        self.assertEqual(increased["available_qty"], before["available_qty"] + 2)
        self.assertEqual(increased["total_qty"], before["total_qty"] + 2)
        decreased = adjust_inventory_quantity("tool-inspection-kit", -1, self.db_path, actor="operator")
        self.assertEqual(decreased["available_qty"], before["available_qty"] + 1)
        self.assertEqual(decreased["total_qty"], before["total_qty"] + 1)
        with connect_db(self.db_path) as conn:
            event = conn.execute("SELECT details_json FROM task_events WHERE event_type='inventory_adjusted' ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(json.loads(event[0])["delta"], -1)

    def test_inventory_adjustment_cannot_reduce_below_zero_or_ignore_active_reservations(self):
        with self.assertRaisesRegex(DomainError, "不能低于"):
            adjust_inventory_quantity("tool-inspection-kit", -6, self.db_path)
        request = create_inspection_request(self.request_payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        reserve_plan_resources(plan["id"], self.db_path)
        with self.assertRaisesRegex(DomainError, "不能低于"):
            adjust_inventory_quantity("tool-inspection-kit", -5, self.db_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)

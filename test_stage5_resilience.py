"""Stage five tests: re-planning, compensation, recovery and audit trail."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stage2_db import connect_db, initialize_database
from stage2_domain import (
    DomainError,
    confirm_plan,
    create_inspection_request,
    create_plan,
    get_plan,
    get_request,
    list_events,
    recover_interrupted_state,
    replan_request,
)


class Stage5ResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "stage2.db"
        initialize_database(self.db_path)
        self.work_date = (date.today() + timedelta(days=1)).isoformat()

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **changes):
        value = {
            "pump_id": "pump-001", "work_date": self.work_date,
            "start_time": "09:00", "duration_minutes": 60,
            "description": "阶段五重排测试",
        }
        value.update(changes)
        return value

    def test_replan_increments_version_after_resource_change(self):
        request = create_inspection_request(self.payload(start_time="13:00"), self.db_path)
        first = create_plan(request["id"], self.db_path)
        with connect_db(self.db_path) as connection:
            connection.execute("UPDATE workers SET role='临时不可用' WHERE id=?", (first["worker_id"],))
            connection.execute("DELETE FROM worker_skills WHERE worker_id=?", (first["worker_id"],))
            connection.commit()
        replanned = replan_request(request["id"], self.db_path)
        self.assertEqual(replanned["id"], first["id"])
        self.assertEqual(replanned["version"], 2)
        self.assertEqual(replanned["status"], "proposed")
        self.assertNotEqual(replanned["worker_id"], first["worker_id"])
        self.assertIn("plan_replanned", {event["event_type"] for event in list_events(request["id"], self.db_path)})

    def test_force_failure_compensates_resources_in_one_operation(self):
        request = create_inspection_request(self.payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        with self.assertRaisesRegex(DomainError, "创建失败"):
            confirm_plan(plan["id"], "stage5-failure", self.db_path, force_failure=True)
        with connect_db(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT available_qty FROM inventory_items WHERE id='tool-inspection-kit'").fetchone()[0], 5)
        self.assertIn("resource_released", {event["event_type"] for event in list_events(request["id"], self.db_path)})
        self.assertIn("work_order_failed", {event["event_type"] for event in list_events(request["id"], self.db_path)})

    def test_release_cannot_detach_resources_from_a_committed_order(self):
        from stage2_domain import release_plan_resources
        request = create_inspection_request(self.payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        confirm_plan(plan["id"], "committed-order", self.db_path)
        with self.assertRaisesRegex(DomainError, "工单"):
            release_plan_resources(plan["id"], self.db_path)
        with connect_db(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 3)
        self.assertEqual(get_plan(plan["id"], self.db_path)["status"], "confirmed")

    def test_empty_release_fences_late_reserve_and_order(self):
        from stage2_domain import release_plan_resources, reserve_plan_resources, create_work_order_for_plan
        request = create_inspection_request(self.payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        self.assertEqual(release_plan_resources(plan["id"], self.db_path), [])
        self.assertEqual(get_plan(plan["id"], self.db_path)["status"], "cancelled")
        with self.assertRaises(DomainError):
            reserve_plan_resources(plan["id"], self.db_path)
        with self.assertRaises(DomainError):
            create_work_order_for_plan(plan["id"], "late-order", self.db_path)
        with connect_db(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 0)

    def test_release_before_order_fences_late_order(self):
        from stage2_domain import release_plan_resources, reserve_plan_resources, create_work_order_for_plan
        request = create_inspection_request(self.payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        reserve_plan_resources(plan["id"], self.db_path)
        release_plan_resources(plan["id"], self.db_path)
        with self.assertRaises(DomainError):
            create_work_order_for_plan(plan["id"], "late-order", self.db_path)
        with connect_db(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0], 0)

    def test_recovery_releases_orphaned_confirming_plan(self):
        request = create_inspection_request(self.payload(), self.db_path)
        plan = create_plan(request["id"], self.db_path)
        from stage2_domain import reserve_plan_resources
        reserve_plan_resources(plan["id"], self.db_path)
        result = recover_interrupted_state(self.db_path)
        self.assertEqual(result["compensated"], 1)
        self.assertEqual(get_plan(plan["id"], self.db_path)["status"], "cancelled")
        with connect_db(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 0)

    def test_failed_replan_commits_failure_state_and_audit(self):
        # The demo seed now includes evening-capable worker-05 (until 19:00).
        # Use a slot outside every seeded availability window so this remains
        # a deterministic no-worker replan case.
        request = create_inspection_request(self.payload(start_time="20:00"), self.db_path)
        with self.assertRaisesRegex(DomainError, "没有可用人员"):
            replan_request(request["id"], self.db_path)
        self.assertEqual(get_request(request["id"], self.db_path)["status"], "failed")
        self.assertIn("replan_failed", {event["event_type"] for event in list_events(request["id"], self.db_path)})

    def test_same_idempotency_key_cannot_return_another_plan_order(self):
        first = create_inspection_request(self.payload(), self.db_path)
        first_plan = create_plan(first["id"], self.db_path)
        confirm_plan(first_plan["id"], "shared-key", self.db_path)
        second = create_inspection_request(self.payload(start_time="13:00", description="第二个任务"), self.db_path)
        second_plan = create_plan(second["id"], self.db_path)
        with self.assertRaisesRegex(DomainError, "幂等键"):
            confirm_plan(second_plan["id"], "shared-key", self.db_path)

    def test_unavailable_plan_failure_is_audited(self):
        request = create_inspection_request(self.payload(start_time="20:00"), self.db_path)
        with self.assertRaisesRegex(DomainError, "没有可用人员"):
            create_plan(request["id"], self.db_path)
        self.assertEqual(get_request(request["id"], self.db_path)["status"], "failed")
        self.assertIn("plan_failed", {event["event_type"] for event in list_events(request["id"], self.db_path)})

    def test_resource_conflict_failure_is_audited(self):
        first = create_inspection_request(self.payload(), self.db_path)
        first_plan = create_plan(first["id"], self.db_path)

        # The seed contains several pump-inspection workers. Remove the other
        # workers' availability in this fixture so both plans intentionally
        # contend for one deterministic worker without changing production
        # availability data.
        with connect_db(self.db_path) as connection:
            connection.execute(
                "DELETE FROM worker_availability WHERE worker_id IN ('worker-03','worker-04','worker-05')"
            )
            connection.commit()

        second = create_inspection_request(self.payload(description="冲突任务"), self.db_path)
        second_plan = create_plan(second["id"], self.db_path)
        from stage2_domain import reserve_plan_resources
        reserve_plan_resources(first_plan["id"], self.db_path)
        with self.assertRaisesRegex(DomainError, "没有可用"):
            reserve_plan_resources(second_plan["id"], self.db_path)
        self.assertEqual(get_request(second["id"], self.db_path)["status"], "failed")
        self.assertIn("resource_conflict", {event["event_type"] for event in list_events(second["id"], self.db_path)})


if __name__ == "__main__":
    unittest.main(verbosity=2)

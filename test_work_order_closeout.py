"""Real SQLite regressions for terminal work-order resource accounting."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from stage2_db import connect_db, initialize_database
from stage2_domain import (
    DomainError, confirm_plan, create_inspection_request, create_plan,
    update_work_order_status, reserve_plan_resources, replan_request,
    recover_interrupted_state,
)


class WorkOrderCloseoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'business.db'
        initialize_database(self.db)
        request = create_inspection_request({
            'pump_id': 'pump-001',
            'work_date': (date.today() + timedelta(days=1)).isoformat(),
            'start_time': '09:00', 'duration_minutes': 60,
            'description': '检查泵体',
        }, self.db)
        self.plan = create_plan(request['id'], self.db)
        self.order = confirm_plan(self.plan['id'], 'closeout-test', self.db)['work_order']

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        with connect_db(self.db) as db:
            return {
                'reservations': [dict(row) for row in db.execute('SELECT * FROM reservations ORDER BY id')],
                'inventory': {row['id']: row['available_qty'] for row in db.execute('SELECT * FROM inventory_items')},
                'plan': db.execute('SELECT status FROM plans WHERE id=?', (self.plan['id'],)).fetchone()[0],
                'request': db.execute('SELECT status FROM inspection_requests WHERE id=?', (self.order['request_id'],)).fetchone()[0],
            }

    def test_completion_returns_worker_tool_and_part(self):
        result = update_work_order_status(self.order['id'], 'completed', self.db)
        self.assertEqual(result['status'], 'completed')
        snapshot = self.snapshot()
        states = {row['resource_id']: row['status'] for row in snapshot['reservations']}
        self.assertEqual(states[self.plan['worker_id']], 'released')
        self.assertEqual(states['tool-inspection-kit'], 'released')
        self.assertEqual(states['part-seal-ring'], 'released')
        self.assertEqual(snapshot['inventory']['tool-inspection-kit'], 5)
        self.assertEqual(snapshot['inventory']['part-seal-ring'], 5)
        self.assertEqual(snapshot['plan'], 'completed')
        self.assertEqual(snapshot['request'], 'completed')
        with connect_db(self.db) as db:
            event = db.execute("SELECT details_json FROM task_events WHERE event_type='work_order_resources_closed' AND work_order_id=?", (self.order['id'],)).fetchone()
            details = json.loads(event[0])
            self.assertEqual(len(details['released_reservations']), 3)
            self.assertEqual(details['consumed_reservations'], [])

    def test_repeated_and_concurrent_completion_never_returns_tool_twice(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: update_work_order_status(self.order['id'], 'completed', self.db), range(2)))
        before = self.snapshot()
        self.assertEqual(before['inventory']['tool-inspection-kit'], 5)
        self.assertTrue(all(row['status'] == 'completed' for row in results))
        update_work_order_status(self.order['id'], 'completed', self.db)
        self.assertEqual(before, self.snapshot())
        with connect_db(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_events WHERE event_type='work_order_resources_closed'").fetchone()[0], 1)

    def test_completed_order_cannot_regress(self):
        update_work_order_status(self.order['id'], 'completed', self.db)
        for status in ('in_progress', 'failed'):
            with self.subTest(status=status), self.assertRaises(DomainError):
                update_work_order_status(self.order['id'], status, self.db)

    def test_failure_compensates_all_resources_once(self):
        update_work_order_status(self.order['id'], 'failed', self.db)
        snapshot = self.snapshot()
        self.assertTrue(all(row['status'] == 'released' for row in snapshot['reservations']))
        self.assertEqual(snapshot['inventory']['tool-inspection-kit'], 5)
        self.assertEqual(snapshot['inventory']['part-seal-ring'], 5)
        self.assertEqual(snapshot['plan'], 'failed')
        update_work_order_status(self.order['id'], 'failed', self.db)
        self.assertEqual(snapshot, self.snapshot())
        with self.assertRaises(DomainError):
            update_work_order_status(self.order['id'], 'in_progress', self.db)

    def test_cancellation_returns_tool_and_part(self):
        from stage2_domain import cancel_work_order

        result = cancel_work_order(self.order['id'], self.db)
        self.assertEqual(result['status'], 'cancelled')
        snapshot = self.snapshot()
        states = {row['resource_id']: row['status'] for row in snapshot['reservations']}
        self.assertEqual(states['tool-inspection-kit'], 'released')
        self.assertEqual(states['part-seal-ring'], 'released')
        self.assertEqual(snapshot['inventory']['tool-inspection-kit'], 5)
        self.assertEqual(snapshot['inventory']['part-seal-ring'], 5)

    def test_legacy_completed_active_reservations_are_reconciled(self):
        # Reproduce the previous production state without bypassing the new handler.
        with connect_db(self.db) as db:
            db.execute("UPDATE work_orders SET status='completed' WHERE id=?", (self.order['id'],))
        update_work_order_status(self.order['id'], 'completed', self.db)
        snapshot = self.snapshot()
        self.assertFalse(any(row['status'] == 'active' for row in snapshot['reservations']))
        self.assertEqual(snapshot['inventory']['tool-inspection-kit'], 5)

    def test_legacy_consumed_part_is_reconciled_once_on_recovery(self):
        with connect_db(self.db) as db:
            db.execute("UPDATE work_orders SET status='completed' WHERE id=?", (self.order['id'],))
            db.execute("UPDATE plans SET status='completed' WHERE id=?", (self.plan['id'],))
            db.execute("UPDATE inspection_requests SET status='completed' WHERE id=?", (self.order['request_id'],))
            db.execute("UPDATE reservations SET status='consumed' WHERE plan_id=? AND resource_type='inventory' AND resource_id='part-seal-ring'", (self.plan['id'],))
        result = recover_interrupted_state(self.db)
        self.assertEqual(result['inventory_reconciled'], 1)
        snapshot = self.snapshot()
        states = {row['resource_id']: row['status'] for row in snapshot['reservations']}
        self.assertEqual(states['part-seal-ring'], 'released')
        self.assertEqual(snapshot['inventory']['part-seal-ring'], 5)
        self.assertEqual(recover_interrupted_state(self.db)['inventory_reconciled'], 0)

    def test_unknown_inventory_category_rolls_back_entire_closeout(self):
        with connect_db(self.db) as db:
            db.execute("UPDATE inventory_items SET category='unknown' WHERE id='part-seal-ring'")
        before = self.snapshot()
        with self.assertRaisesRegex(DomainError, '分类'):
            update_work_order_status(self.order['id'], 'completed', self.db)
        self.assertEqual(before, self.snapshot())
        with connect_db(self.db) as db:
            self.assertEqual(db.execute('SELECT status FROM work_orders WHERE id=?', (self.order['id'],)).fetchone()[0], 'confirmed')

    def test_late_reserve_cannot_reopen_completed_or_failed_order(self):
        update_work_order_status(self.order['id'], 'completed', self.db)
        before = self.snapshot()
        with self.assertRaises(DomainError):
            reserve_plan_resources(self.plan['id'], self.db)
        self.assertEqual(before, self.snapshot())

    def test_failed_order_cannot_replan_or_accept_late_reserve(self):
        update_work_order_status(self.order['id'], 'failed', self.db)
        before = self.snapshot()
        with self.assertRaises(DomainError):
            reserve_plan_resources(self.plan['id'], self.db)
        with self.assertRaises(DomainError):
            replan_request(self.order['request_id'], self.db)
        self.assertEqual(before, self.snapshot())

    def test_in_progress_duplicate_reserve_keeps_existing_resources(self):
        update_work_order_status(self.order['id'], 'in_progress', self.db)
        before = self.snapshot()
        rows = reserve_plan_resources(self.plan['id'], self.db)
        self.assertEqual(len(rows), 3)
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main()

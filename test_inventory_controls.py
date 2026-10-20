"""Regression tests for reusable inventory quantities and operator controls."""
import tempfile
import unittest
from pathlib import Path

from stage2_db import connect_db, initialize_database
from stage2_domain import DomainError, adjust_inventory_quantity, create_inspection_request, create_plan, confirm_plan


class InventoryControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "inventory.db"
        initialize_database(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_seed_has_expanded_tool_quantities(self):
        with connect_db(self.db) as db:
            tools = {
                row["id"]: (row["total_qty"], row["available_qty"])
                for row in db.execute("SELECT id,total_qty,available_qty FROM inventory_items WHERE category='tool'")
            }
        self.assertEqual(tools["tool-inspection-kit"], (5, 5))
        self.assertEqual(tools["tool-vibration-meter"], (4, 4))
        self.assertEqual(tools["tool-lockout-tag"], (6, 6))
        self.assertEqual(tools["tool-thermal-camera"], (4, 4))
        self.assertEqual(tools["tool-pressure-gauge"], (5, 5))
        self.assertEqual(tools["tool-insulation-tester"], (4, 4))

    def test_existing_v4_database_is_expanded_once_without_losing_reservations(self):
        with connect_db(self.db) as db:
            db.execute("UPDATE inventory_items SET total_qty=total_qty-3, available_qty=available_qty-3 WHERE category='tool'")
            db.execute("PRAGMA user_version=4")
        initialize_database(self.db)
        with connect_db(self.db) as db:
            rows = db.execute("SELECT id,total_qty,available_qty FROM inventory_items WHERE category='tool' ORDER BY id").fetchall()
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
        self.assertEqual(
            {row["id"]: (row["total_qty"], row["available_qty"]) for row in rows},
            {"tool-inspection-kit": (5, 5), "tool-vibration-meter": (4, 4), "tool-lockout-tag": (6, 6),
             "tool-thermal-camera": (4, 4), "tool-pressure-gauge": (5, 5), "tool-insulation-tester": (4, 4)},
        )
        initialize_database(self.db)
        with connect_db(self.db) as db:
            rows_again = db.execute("SELECT id,total_qty,available_qty FROM inventory_items WHERE category='tool' ORDER BY id").fetchall()
        self.assertEqual([(row["id"], row["total_qty"], row["available_qty"]) for row in rows],
                         [(row["id"], row["total_qty"], row["available_qty"]) for row in rows_again])

    def test_manual_set_cannot_reduce_below_active_reservation(self):
        request = create_inspection_request({
            "pump_id": "pump-001", "work_date": "2030-01-02", "start_time": "14:00",
            "duration_minutes": 60, "description": "库存控制测试",
        }, self.db)
        plan = create_plan(request["id"], self.db)
        confirm_plan(plan["id"], "inventory-control", self.db)
        with self.assertRaises(DomainError):
            adjust_inventory_quantity("tool-inspection-kit", -5, self.db)
        with connect_db(self.db) as db:
            row = db.execute("SELECT total_qty,available_qty FROM inventory_items WHERE id='tool-inspection-kit'").fetchone()
        self.assertEqual((row["total_qty"], row["available_qty"]), (5, 4))


if __name__ == "__main__":
    unittest.main(verbosity=2)

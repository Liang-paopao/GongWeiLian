"""Tests of simulated read-only business logic, not SDK or platform verification."""
import json
import tempfile
import unittest
from pathlib import Path
from business import DATA_FILE, lookup_staff


def query(slot="slot-a", **changes):
    value = {"action": "lookup_staff", "device_id": "pump-001", "slot": slot}
    value.update(changes)
    return value


class BusinessTests(unittest.TestCase):
    def test_available(self):
        self.assertEqual([p["id"] for p in lookup_staff(query())["available_staff"]], ["staff-01", "staff-04", "staff-05"])
    def test_unavailable(self):
        self.assertEqual(lookup_staff(query("slot-b"))["available_staff"], [])
    def test_unknown_device(self):
        with self.assertRaises(ValueError):
            lookup_staff(query(device_id="pump-unknown"))
    def test_unknown_slot(self):
        with self.assertRaises(ValueError):
            lookup_staff(query("slot-unknown"))
    def test_no_write_action(self):
        with self.assertRaises(ValueError):
            lookup_staff(query(action="reserve_staff"))
    def test_read_only(self):
        before = DATA_FILE.read_bytes()
        out = lookup_staff(query())
        self.assertEqual(DATA_FILE.read_bytes(), before)
        self.assertFalse(out["staff_reserved"])
        self.assertFalse(out["work_order_created"])
    def test_explicit_simulation_required(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "resources.json"
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            data["simulated"] = False
            file.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                lookup_staff(query(), file)


if __name__ == "__main__":
    unittest.main(verbosity=2)

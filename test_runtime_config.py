"""Regression checks for the local runtime's configurable resource port."""
import os
import importlib
import unittest
from pathlib import Path

import leader


ROOT = Path(__file__).resolve().parent


class RuntimeConfigTests(unittest.TestCase):
    def test_leader_uses_safe_default_port(self):
        self.assertEqual(leader.PARTNER_URL, "http://127.0.0.1:18011/rpc")

    def test_leader_honors_port_environment(self):
        original = os.environ.get("GONGWEI_RESOURCE_PORT")
        try:
            os.environ["GONGWEI_RESOURCE_PORT"] = "18099"
            importlib.reload(leader)
            self.assertEqual(leader.PARTNER_URL, "http://127.0.0.1:18099/rpc")
            self.assertIn("GONGWEI_RESOURCE_PORT", (ROOT / "02_start_resource.cmd").read_text(encoding="utf-8"))
            self.assertIn("GONGWEI_RESOURCE_PORT", (ROOT / "03_run_leader.cmd").read_text(encoding="utf-8"))
        finally:
            if original is None:
                os.environ.pop("GONGWEI_RESOURCE_PORT", None)
            else:
                os.environ["GONGWEI_RESOURCE_PORT"] = original
            importlib.reload(leader)

    def test_untrusted_transport_error_is_redacted(self):
        raw = "BadStatusLine: " + ("opaque-value " * 80)
        safe = leader.safe_error_message(RuntimeError(raw))
        self.assertNotIn("opaque-value", safe)
        self.assertIn("非本练习", safe)


if __name__ == "__main__":
    unittest.main(verbosity=2)

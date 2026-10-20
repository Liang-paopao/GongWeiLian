"""Local launcher safety checks; never terminate a real user process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from scripts import local_services as services
except ImportError:
    services = None


class LocalServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(services, "A launcher with verified process ownership is required")

    def test_configured_ports_are_used_and_duplicate_ports_rejected(self):
        with patch.dict(os.environ, {"GONGWEI_STAGE2_RESOURCE_PORT": "28112"}, clear=True):
            self.assertEqual(services.configured_services()[0]["port"], 28112)
        with patch.dict(os.environ, {"GONGWEI_STAGE2_RESOURCE_PORT": "18010"}, clear=True):
            with self.assertRaisesRegex(ValueError, "重复"):
                services.configured_services()

    def test_process_identity_requires_executable_command_and_creation_time(self):
        row = {"pid": 123, "executable": str(services.PYTHON), "command": "expected", "created": "time-a"}
        actual = {"pid": 123, "executable": str(services.PYTHON), "command": "expected", "created": "time-a"}
        self.assertTrue(services.same_process(row, actual))
        for key in ("executable", "command", "created"):
            self.assertFalse(services.same_process(row, {**actual, key: "another"}))
        self.assertFalse(services.same_process(row, None))

    def test_health_requires_expected_service_and_ok_status(self):
        spec = {"health_key": "partner", "health_value": "stage2-gongwei-resource"}
        self.assertTrue(services.healthy(spec, {"status": "ok", "partner": spec["health_value"]}))
        self.assertFalse(services.healthy(spec, {"status": "pending", "partner": spec["health_value"]}))
        self.assertFalse(services.healthy(spec, {"status": "ok", "partner": "some-other-app"}))

    def test_stop_refuses_pid_reuse_and_preserves_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "services.json"
            row = {"pid": 123, "module": "web_app:app", "port": 28110,
                   "executable": str(services.PYTHON), "command": "expected", "created": "old"}
            state.write_text(json.dumps({"root": str(services.ROOT), "processes": [row]}), encoding="utf-8")
            with patch.object(services, "STATE_PATH", state), patch.object(services, "process_info", return_value={**row, "created": "new"}), patch.object(services, "terminate_process") as stop:
                self.assertEqual(services.stop_services(), 1)
                stop.assert_not_called()
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["processes"], [row])

    def test_occupied_unowned_port_is_rejected_before_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(services, "STATE_PATH", Path(directory) / "services.json"), patch.object(services, "port_is_open", return_value=True), patch.object(services.subprocess, "Popen") as spawn:
                self.assertEqual(services.start_services(), 1)
                spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()

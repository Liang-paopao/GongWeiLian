"""Regression runners must isolate data, ports, transport, and test logs."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LocalRegressionIsolationTests(unittest.TestCase):
    def capture_start(self, module, workspace):
        captured = []

        def start(name, port, env, log_name):
            captured.append((port, env.copy()))
            raise RuntimeError("stop after configuration")

        starter = "start_service"
        with patch.object(module, "ROOT", workspace), \
                patch.object(module, "LOG_DIR", workspace / "old-logs"), \
                patch.dict(os.environ, {"GONGWEI_TRANSPORT_MODE": "platform_mq_inbox",
                                       "GONGWEI_RUNTIME_MODE": "external",
                                       "GONGWEI_DISCOVERY_URL": "https://unused.invalid",
                                       "GONGWEI_STAGE2_DB": str(workspace / "user.db")}), \
                patch.object(module, starter, side_effect=start):
            (workspace / "old-logs").mkdir(exist_ok=True)
            with self.assertRaisesRegex(RuntimeError, "stop after configuration"):
                module.main()
        return captured[0]

    def test_blackbox_runners_force_local_transport_and_allocate_fresh_ports(self):
        import run_stage2_tests
        import run_stage5_tests
        for module in (run_stage2_tests, run_stage5_tests):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / "data").mkdir()
                _, env = self.capture_start(module, root)
                self.assertEqual(env["GONGWEI_TRANSPORT_MODE"], "local_rpc")
                self.assertEqual(env["GONGWEI_RUNTIME_MODE"], "local")
                self.assertEqual(env.get("GONGWEI_DISCOVERY_URL"), "")
                ports = [int(value) for key, value in env.items()
                         if key.startswith("GONGWEI_STAGE2_") and key.endswith("_PORT")]
                self.assertEqual(len(set(ports)), len(ports))
                self.assertTrue(all(port not in {18110, 18112, 18113, 18210, 18212, 18213, 18214}
                                    for port in ports))
                self.assertTrue(Path(env["GONGWEI_LOG_DIR"]).is_relative_to(root / "reports"))

    def test_stage5_does_not_delete_existing_database_or_sidecars(self):
        import run_stage5_tests
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            originals = [root / "data" / f"stage5_test.db{suffix}" for suffix in ("", "-wal", "-shm")]
            for path in originals:
                path.write_bytes(b"existing user file")
            _, env = self.capture_start(run_stage5_tests, root)
            self.assertTrue(all(path.exists() and path.read_bytes() == b"existing user file" for path in originals))
            self.assertFalse(Path(env["GONGWEI_STAGE2_DB"]).is_relative_to(root))
            self.assertFalse(Path(env["GONGWEI_STAGE2_DB"]).exists())

    def test_stage2_stops_first_child_if_second_start_fails(self):
        import run_stage2_tests
        child = object()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(run_stage2_tests, "ROOT", root), \
                    patch.object(run_stage2_tests, "LOG_DIR", root / "old-logs"), \
                    patch.object(run_stage2_tests, "start_service", side_effect=[child, RuntimeError("second failed")]), \
                    patch.object(run_stage2_tests, "stop_process") as stop:
                with self.assertRaisesRegex(RuntimeError, "second failed"):
                    run_stage2_tests.main()
                stop.assert_called_once_with(child)

    def test_sixty_scenarios_keep_domain_logs_inside_report_directory(self):
        import local_log
        from scripts import run_60_scenarios
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reports = root / "reports"
            reports.mkdir()
            previous_logs = root / "existing-logs"
            previous_logs.mkdir()
            observed = []

            def run_one(group, index, db):
                observed.append((local_log.LOG_DIR, os.environ.get("GONGWEI_TRANSPORT_MODE")))
                local_log.record("isolated-test", "event", {})
                return {"group": group, "scene": index, "passed": True, "detail": "fixture"}

            with patch.object(run_60_scenarios, "ROOT", root), \
                    patch.object(run_60_scenarios, "REPORT_JSON", reports / "result.json"), \
                    patch.object(run_60_scenarios, "REPORT_MD", reports / "result.md"), \
                    patch.object(run_60_scenarios, "run_one", side_effect=run_one), \
                    patch.object(local_log, "LOG_DIR", previous_logs), \
                    patch.dict(os.environ, {"GONGWEI_TRANSPORT_MODE": "platform_mq_inbox"}):
                self.assertEqual(run_60_scenarios.main(), 0)
                self.assertEqual(local_log.LOG_DIR, previous_logs)
                self.assertEqual(os.environ["GONGWEI_TRANSPORT_MODE"], "platform_mq_inbox")
            self.assertTrue(all(path.is_relative_to(reports) and mode == "local_rpc" for path, mode in observed))
            self.assertEqual(list(previous_logs.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

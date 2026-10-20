from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FinalAuditFeatureTests(unittest.TestCase):
    def test_https_transport_requires_real_external_configuration(self):
        from transport_mode import get_transport_mode, https_configuration_status

        with patch.dict(os.environ, {"GONGWEI_TRANSPORT_MODE": "platform_https_rpc"}, clear=True):
            self.assertEqual(get_transport_mode(), "platform_https_rpc")
            status = https_configuration_status()
        self.assertFalse(status["configured"])
        self.assertIn("leader_rpc_url", status["missing"])
        self.assertIn("leader_aic", status["missing"])
        self.assertIn("server_cert_file", status["missing"])
        self.assertFalse(status["platform_verified"])

    def test_https_configuration_rejects_local_and_example_urls(self):
        from transport_mode import https_configuration_status

        values = {
            "GONGWEI_TRANSPORT_MODE": "platform_https_rpc",
            "GONGWEI_PUBLIC_LEADER_RPC_URL": "http://127.0.0.1:18010/rpc",
            "GONGWEI_PUBLIC_RESOURCE_RPC_URL": "https://resource.example.com/rpc",
            "GONGWEI_PUBLIC_WORKORDER_RPC_URL": "https://work.example.com/rpc",
            "GONGWEI_LEADER_AIC": "leader-aic",
            "GONGWEI_RESOURCE_AIC": "resource-aic",
            "GONGWEI_WORKORDER_AIC": "workorder-aic",
            "GONGWEI_SERVER_CERT_FILE": "cert.pem",
            "GONGWEI_CLIENT_CERT_FILE": "client.pem",
            "GONGWEI_PRIVATE_KEY_FILE": "client.key",
            "GONGWEI_TRUST_BUNDLE_FILE": "ca.pem",
        }
        with patch.dict(os.environ, values, clear=True):
            status = https_configuration_status()
        self.assertFalse(status["configured"])
        self.assertTrue(any("leader_rpc_url" in item for item in status["invalid"]))
        self.assertTrue(any("resource_rpc_url" in item for item in status["invalid"]))

    def test_database_schema_version_is_set_and_old_database_is_upgraded(self):
        from stage2_db import SCHEMA_VERSION, connect_db, initialize_database

        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "old.db"
            with connect_db(db) as connection:
                connection.execute("CREATE TABLE pumps (id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT NOT NULL, model TEXT NOT NULL, simulated INTEGER NOT NULL DEFAULT 1)")
                connection.execute("INSERT INTO pumps(id,name,location,model) VALUES('pump-old','旧泵','旧区','M')")
                connection.commit()
            initialize_database(db)
            with connect_db(db) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(connection.execute("SELECT name FROM pumps WHERE id='pump-old'").fetchone()[0], "旧泵")
                self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_events'").fetchone())

    def test_state_mapping_covers_business_and_aip_states(self):
        from state_mapping import AIP_TO_BUSINESS, BUSINESS_TO_AIP, map_aip_to_business, map_business_to_aip

        for state in ("created", "awaiting_input", "planned", "awaiting_confirmation", "confirming", "reserved", "work_order_created", "in_progress", "completed", "cancelled", "failed", "compensating", "recovery_required"):
            self.assertIn(state, BUSINESS_TO_AIP)
            self.assertIn(BUSINESS_TO_AIP[state], AIP_TO_BUSINESS)
            self.assertEqual(map_aip_to_business(BUSINESS_TO_AIP[state]), AIP_TO_BUSINESS[BUSINESS_TO_AIP[state]])
        self.assertEqual(map_business_to_aip("completed"), "completed")

    def test_audio_can_be_disabled_without_removing_manual_flow(self):
        from audio_service import audio_enabled

        with patch.dict(os.environ, {"GONGWEI_AUDIO_ENABLED": "false"}, clear=False):
            self.assertFalse(audio_enabled())
        with patch.dict(os.environ, {"GONGWEI_AUDIO_ENABLED": "true"}, clear=False):
            self.assertTrue(audio_enabled())

    def test_observability_writes_six_categories_with_secret_redaction(self):
        import local_log

        with tempfile.TemporaryDirectory() as folder:
            old = local_log.LOG_DIR
            local_log.LOG_DIR = Path(folder)
            try:
                local_log.record("audit_test", "task_completed", {
                    "task_id": "task-1", "message_id": "message-1", "password": "do-not-log",
                })
                local_log.record_all_categories("task-1", "message-1")
                for category in local_log.LOG_CATEGORIES:
                    path = Path(folder) / f"{category.lower()}.jsonl"
                    self.assertTrue(path.exists(), category)
                    self.assertNotIn("do-not-log", path.read_text(encoding="utf-8"))
            finally:
                local_log.LOG_DIR = old

    def test_https_acs_generator_requires_aic_and_certificates(self):
        from scripts.build_platform_acs import build

        with patch.dict(os.environ, {"GONGWEI_PUBLIC_BASE_URL": "https://ops.vendor.cn"}, clear=False):
            with self.assertRaisesRegex(ValueError, "AIC"):
                with tempfile.TemporaryDirectory() as folder:
                    build(Path(folder))


if __name__ == "__main__":
    unittest.main(verbosity=2)

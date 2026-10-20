import unittest
from types import SimpleNamespace

from acps_sdk.aip import TaskState
from scripts import probe_group_resource, probe_group_workflow, probe_hybrid_discovery


class PlatformDiagnosticTests(unittest.TestCase):
    def test_group_membership_is_not_a_task_state(self):
        self.assertNotIn("state", probe_group_resource.public_message(SimpleNamespace(status="joined")))
        self.assertEqual(probe_group_resource.public_message(
            SimpleNamespace(status=SimpleNamespace(state=TaskState.Completed)))["state"], "completed")

    def test_catalog_query_explicitly_includes_unknown_liveness(self):
        query = probe_hybrid_discovery.build_query("test-aic", catalog=True)
        self.assertEqual(query["extFilter"]["conditions"][0],
                         {"field": "alive", "op": "in", "value": ["online", "offline", "unknown"]})
        self.assertNotIn("extFilter", probe_hybrid_discovery.build_query("test-aic"))

    def test_indexed_does_not_mean_available_or_callable(self):
        result = probe_hybrid_discovery.summarize_lookup(
            {"success": True, "target_found": False}, {"success": True, "target_found": True})
        self.assertTrue(result["indexed"])
        self.assertFalse(result["default_discoverable"])
        self.assertFalse(result["dingdang_verified"])

    def test_discovery_error_is_unknown_instead_of_index_absence(self):
        result = probe_hybrid_discovery.summarize_lookup({"success": False}, {"success": False})
        self.assertIsNone(result["indexed"])
        self.assertIsNone(result["default_discoverable"])

    def test_replay_requires_target_handler_completion_and_duplicate_receipt(self):
        event = {"event": "command_processed", "role": "resource", "id": "same",
                 "mentioned": False, "duplicate": False, "ok": True}
        self.assertIsNone(probe_group_workflow.replay_receipt([event], "workorder", "same"))
        event.update(role="workorder", mentioned=True)
        self.assertIsNone(probe_group_workflow.replay_receipt([event], "workorder", "same"))
        event.update(duplicate=True, event="received_command")
        self.assertIsNone(probe_group_workflow.replay_receipt([event], "workorder", "same"))
        event["event"] = "command_processed"
        self.assertIs(probe_group_workflow.replay_receipt([event], "workorder", "same"), event)


if __name__ == "__main__":
    unittest.main()

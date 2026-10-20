import unittest
from unittest.mock import MagicMock, patch


class PartnerInboxEntryTests(unittest.TestCase):
    def test_partner_entrypoint_builds_official_inbox_without_rpc_fallback(self):
        from run_partner_inbox import build_runtime
        with patch("run_partner_inbox.get_transport_mode", return_value="platform_mq_inbox"), patch("run_partner_inbox.configure_platform_environment", return_value={"aic": "real-resource-aic"}), patch("run_partner_inbox._runtime_rabbitmq_config", return_value={"host": "wt.ioa.pub"}), patch("run_partner_inbox.OfficialMqPartnerRuntime") as runtime_cls, patch("run_partner_inbox.OfficialMqPartnerHandler", return_value=MagicMock()):
            runtime = runtime_cls.return_value
            instance = build_runtime("resource")
            self.assertIs(instance, runtime)
            runtime.set_command_handler.assert_called_once()
            runtime_cls.assert_called_once_with(partner_aic="real-resource-aic", rabbitmq_config={"host": "wt.ioa.pub"})

    def test_partner_entrypoint_rejects_local_rpc_mode(self):
        from run_partner_inbox import _ensure_platform_mode
        with patch("run_partner_inbox.get_transport_mode", return_value="local_rpc"):
            with self.assertRaises(RuntimeError):
                _ensure_platform_mode()


if __name__ == "__main__":
    unittest.main()



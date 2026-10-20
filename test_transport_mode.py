from __future__ import annotations

import os
import unittest
from unittest.mock import patch


class TransportModeTests(unittest.TestCase):
    def test_local_rpc_is_the_safe_default(self):
        from transport_mode import get_transport_mode

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_transport_mode(), "local_rpc")

    def test_platform_mq_inbox_is_explicitly_selectable(self):
        from transport_mode import get_transport_mode

        with patch.dict(os.environ, {"GONGWEI_TRANSPORT_MODE": "platform_mq_inbox"}, clear=True):
            self.assertEqual(get_transport_mode(), "platform_mq_inbox")

    def test_unknown_mode_is_rejected_without_fallback(self):
        from transport_mode import TransportModeError, get_transport_mode

        with patch.dict(os.environ, {"GONGWEI_TRANSPORT_MODE": "rabbitmq_guess"}, clear=True):
            with self.assertRaises(TransportModeError):
                get_transport_mode()

    def test_mq_configuration_status_redacts_credentials(self):
        from transport_mode import mq_configuration_status

        with patch.dict(os.environ, {
            "GONGWEI_TRANSPORT_MODE": "platform_mq_inbox",
            "GONGWEI_MQ_BROKER_URL": "amqps://user:secret@example.invalid:5671/acps",
            "GONGWEI_MQ_AUTH_SERVICE_URL": "https://mq-auth.example.invalid",
            "GONGWEI_MQ_VHOST": "acps",
            "GONGWEI_MQ_TLS_MODE": "mtls",
            "GONGWEI_MQ_INBOX_ENDPOINT": "amqps://example.invalid:5671/acps?inbox=inbox_{AIC}",
        }, clear=True):
            status = mq_configuration_status()
        self.assertEqual(status["mode"], "platform_mq_inbox")
        self.assertNotIn("secret", repr(status))
        self.assertFalse(status["configured"])
        self.assertTrue(any("broker_url" in item for item in status["invalid"]))

    def test_official_wutong_mq_aliases_are_accepted_and_validated(self):
        from transport_mode import mq_configuration_status

        with patch.dict(os.environ, {
            "GONGWEI_TRANSPORT_MODE": "platform_mq_inbox",
            "MQ_BROKER_URL": "amqps://wt.ioa.pub:5671",
            "MQ_AUTH_SERVICE_URL": "https://wt.ioa.pub/mq-auth/",
            "MQ_VHOST": "/acps",
            "MQ_TLS_MODE": "mtls",
            "MQ_INBOX_ENDPOINT": "amqps://wt.ioa.pub:5671/acps?inbox=inbox_{AIC}",
        }, clear=True):
            status = mq_configuration_status()

        self.assertTrue(status["configured"])
        self.assertEqual(status["vhost"], "/acps")
        self.assertEqual(status["tls_mode"], "mtls")
        self.assertEqual(status["inbox_endpoint_template"], "amqps://wt.ioa.pub:5671/acps?inbox=inbox_{AIC}")

    def test_mq_configuration_rejects_non_official_endpoint(self):
        from transport_mode import mq_configuration_status

        with patch.dict(os.environ, {
            "GONGWEI_TRANSPORT_MODE": "platform_mq_inbox",
            "GONGWEI_MQ_BROKER_URL": "amqps://wt.ioa.pub:5671",
            "GONGWEI_MQ_AUTH_SERVICE_URL": "https://wt.ioa.pub/mq-auth/",
            "GONGWEI_MQ_VHOST": "/acps",
            "GONGWEI_MQ_TLS_MODE": "mtls",
            "GONGWEI_MQ_INBOX_ENDPOINT": "https://127.0.0.1/inbox?inbox={AIC}",
        }, clear=True):
            status = mq_configuration_status()

        self.assertFalse(status["configured"])
        self.assertTrue(any("inbox_endpoint_template" in item for item in status["invalid"]))


if __name__ == "__main__":
    unittest.main()

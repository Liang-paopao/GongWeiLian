from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class MqAcsTests(unittest.TestCase):
    def test_group_acs_requires_real_broker_and_auth_parameters(self):
        from scripts.build_mq_acs import build_group_acs

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "GONGWEI_MQ_BROKER_URL"):
                build_group_acs(Path(directory), {})

    def test_group_acs_preserves_group_transport_without_inventing_values(self):
        from scripts.build_mq_acs import build_group_acs

        params = {
            "GONGWEI_MQ_BROKER_URL": "amqps://mq.example.invalid:5671/acps",
            "GONGWEI_MQ_AUTH_SERVICE_URL": "https://mq-auth.example.invalid",
            "GONGWEI_MQ_VHOST": "acps",
            "GONGWEI_MQ_TLS_MODE": "mtls",
            "GONGWEI_MQ_INBOX_ENDPOINT": "amqps://mq.example.invalid:5671/acps?inbox={aic}",
        }
        with tempfile.TemporaryDirectory() as directory:
            files = build_group_acs(Path(directory), params)
            self.assertEqual(len(files), 3)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertTrue(any(item["transport"] == "AMQP" for item in payload["endPoints"]))
            self.assertIn("mq.example.invalid", json.dumps(payload))
            self.assertNotIn("127.0.0.1", json.dumps(payload))

    def test_group_acs_matches_wutong_official_mq_parameters(self):
        from scripts.build_mq_acs import build_group_acs

        params = {
            "GONGWEI_MQ_BROKER_URL": "amqps://wt.ioa.pub:5671",
            "GONGWEI_MQ_AUTH_SERVICE_URL": "https://wt.ioa.pub/mq-auth/",
            "GONGWEI_MQ_VHOST": "/acps",
            "GONGWEI_MQ_TLS_MODE": "mtls",
            "GONGWEI_MQ_INBOX_ENDPOINT": "amqps://wt.ioa.pub:5671/acps?inbox=inbox_{AIC}",
        }
        with tempfile.TemporaryDirectory() as directory:
            files = build_group_acs(Path(directory), params)
            self.assertEqual({path.name for path in files}, {"leader.json", "resource_partner.json", "work_order_partner.json"})
            for path in files:
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["aic"], "")
                self.assertEqual(payload["endPoints"], [{
                    "url": params["GONGWEI_MQ_INBOX_ENDPOINT"],
                    "transport": "AMQP",
                    "security": [{"mtls": []}],
                }])
                self.assertEqual(payload["capabilities"]["messageQueue"], ["rabbitmq:>=4.2"])
                self.assertTrue(all(skill.get("version") for skill in payload["skills"]))
                self.assertNotIn("auth_service_url", payload)
                self.assertNotIn("MQ_BROKER_URL", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()

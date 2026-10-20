from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import run_mq_inbox_integration


class MqInboxIntegrationPreflightTests(unittest.TestCase):
    def test_missing_official_runtime_is_reported_as_blocked(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("run_mq_inbox_integration.shutil.which", return_value=None):
                self.assertEqual(run_mq_inbox_integration.main(), 2)


if __name__ == "__main__":
    unittest.main()

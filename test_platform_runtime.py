"""Platform endpoint generation must refuse local or incomplete URLs."""
from __future__ import annotations

import os
import unittest

from platform_runtime import external_rpc_url, runtime_mode, validate_external_base_url


class PlatformRuntimeTests(unittest.TestCase):
    def test_local_url_is_not_an_external_platform_endpoint(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_external_base_url("http://127.0.0.1:18010")
        with self.assertRaisesRegex(ValueError, "本机"):
            validate_external_base_url("https://localhost:18010")

    def test_external_endpoint_is_normalized_for_rpc(self):
        self.assertEqual(external_rpc_url("https://ops.example.com/base/"), "https://ops.example.com/base/rpc")
        self.assertEqual(external_rpc_url("https://ops.example.com/base/rpc"), "https://ops.example.com/base/rpc")

    def test_private_and_rpc_base_addresses_are_rejected(self):
        for value in ("https://127.0.0.2:8443", "https://0.0.0.0:8443", "https://192.168.0.5:8443", "https://localhost.localdomain:8443"):
            with self.assertRaises(ValueError):
                validate_external_base_url(value)
        with self.assertRaisesRegex(ValueError, "/rpc"):
            validate_external_base_url("https://ops.example.com/base/rpc")

    def test_missing_external_endpoint_is_not_synthesized(self):
        old = os.environ.pop("GONGWEI_PUBLIC_BASE_URL", None)
        try:
            with self.assertRaisesRegex(ValueError, "GONGWEI_PUBLIC_BASE_URL"):
                external_rpc_url(None)
        finally:
            if old is not None:
                os.environ["GONGWEI_PUBLIC_BASE_URL"] = old

    def test_unknown_runtime_mode_is_rejected(self):
        old = os.environ.get("GONGWEI_RUNTIME_MODE")
        os.environ["GONGWEI_RUNTIME_MODE"] = "surprise"
        try:
            with self.assertRaisesRegex(ValueError, "local 或 external"):
                runtime_mode()
        finally:
            if old is None:
                os.environ.pop("GONGWEI_RUNTIME_MODE", None)
            else:
                os.environ["GONGWEI_RUNTIME_MODE"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)

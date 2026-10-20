"""Failing-first tests for the Sound Analysis Partner AIP contract."""
from __future__ import annotations

import unittest
import base64
import io
import json
import uuid
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient


def rpc_payload(payload: dict) -> dict:
    return {"jsonrpc": "2.0", "method": "rpc", "id": str(uuid.uuid4()), "params": {"command": {
        "type": "task-command", "id": "cmd-" + str(uuid.uuid4()), "sentAt": "2026-10-03T00:00:00+00:00",
        "senderRole": "leader", "senderId": "stage2-gongwei-leader", "sessionId": "audio-test",
        "command": "start", "taskId": "task-" + str(uuid.uuid4()),
        "dataItems": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
    }}}


class AudioPartnerContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gongwei-audio-partner-test-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        for patcher in (
            patch.dict(os.environ, {"GONGWEI_STAGE2_DB": str(root / "stage2.db")}),
            patch("audio_service.AUDIO_STORAGE", root / "uploads"),
            patch("local_log.LOG_DIR", root / "logs"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_partner_module_exposes_contract_symbols(self):
        from audio_partner_v1 import AUDIO_PARTNER_ID, app

        self.assertEqual(AUDIO_PARTNER_ID, "stage2-gongwei-audio")
        self.assertTrue(any(route.path == "/rpc" for route in app.routes))
        self.assertTrue(any(route.path == "/health" for route in app.routes))

    def test_partner_analyzes_wav_and_persists_result(self):
        from audio_partner_v1 import app
        buffer = io.BytesIO()
        sample_rate = 16000
        t = np.arange(sample_rate, dtype=np.float32) / sample_rate
        sf.write(buffer, np.sin(2 * np.pi * 440 * t), sample_rate, format="WAV", subtype="PCM_16")
        payload = {"action": "analyze_audio", "filename": "upload.wav", "audio_base64": base64.b64encode(buffer.getvalue()).decode("ascii")}
        response = TestClient(app, client=("127.0.0.1", 50003)).post("/rpc", json=rpc_payload(payload))
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        data = json.loads(result["products"][0]["dataItems"][0]["text"])
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"]["status"], "analyzed")
        self.assertIn(data["result"]["verdict"], {"未发现明显异常", "疑似异常"})

    def test_partner_rejects_corrupt_audio(self):
        from audio_partner_v1 import app
        payload = {"action": "analyze_audio", "filename": "broken.wav", "audio_base64": base64.b64encode(b"not-a-wav").decode("ascii")}
        response = TestClient(app, client=("127.0.0.1", 50004)).post("/rpc", json=rpc_payload(payload))
        data = json.loads(response.json()["result"]["products"][0]["dataItems"][0]["text"])
        self.assertFalse(data["ok"])

    def test_partner_rejects_oversized_payload_before_decode(self):
        from audio_service import MAX_AUDIO_BYTES, analyze_audio_payload

        with self.assertRaises(ValueError):
            analyze_audio_payload({"filename": "large.wav", "audio_base64": "A" * (MAX_AUDIO_BYTES * 2 + 1)})


if __name__ == "__main__":
    unittest.main(verbosity=2)

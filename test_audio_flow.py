"""Failing-first tests for the upload -> confirmation -> proposal guard."""
from __future__ import annotations

import base64
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf


class AudioFlowContractTests(unittest.TestCase):
    def test_web_app_exposes_audio_routes(self):
        from web_app import app

        paths = {route.path for route in app.routes}
        self.assertIn("/api/audio/analyze", paths)
        self.assertIn("/api/audio/confirm", paths)

    def test_analysis_is_not_a_request_until_confirmation(self):
        import audio_service
        from stage2_db import initialize_database

        buffer = io.BytesIO()
        sample_rate = 16000
        t = np.arange(sample_rate, dtype=np.float32) / sample_rate
        sf.write(buffer, np.sin(2 * np.pi * 440 * t), sample_rate, format="WAV", subtype="PCM_16")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "flow.db"
            storage = root / "uploads"
            original_storage = audio_service.AUDIO_STORAGE
            audio_service.AUDIO_STORAGE = storage
            try:
                initialize_database(db_path)
                result = audio_service.analyze_audio_payload(
                    {"filename": "pump.wav", "audio_base64": base64.b64encode(buffer.getvalue()).decode("ascii")},
                    db_path=db_path,
                )
                connection = sqlite3.connect(db_path)
                try:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM inspection_requests").fetchone()[0], 0)
                finally:
                    connection.close()
                confirmed = audio_service.confirm_audio_analysis(result["analysis_id"], db_path=db_path)
                self.assertTrue(confirmed["user_confirmed"])
                connection = sqlite3.connect(db_path)
                try:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM inspection_requests").fetchone()[0], 0)
                finally:
                    connection.close()
            finally:
                audio_service.AUDIO_STORAGE = original_storage


if __name__ == "__main__":
    unittest.main(verbosity=2)

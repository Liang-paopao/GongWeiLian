"""Regression tests for the swappable auxiliary audio detector."""
from __future__ import annotations

import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audio_service import analyze_audio_payload, register_detector_backend, unregister_detector_backend


class _StubDetector:
    backend_name = "stub"
    model_version = "stub-v1"

    def analyze_wav_bytes(self, data: bytes) -> dict[str, object]:
        return {
            "model_version": self.model_version,
            "sample_rate": 16000,
            "duration_seconds": 1.0,
            "anomaly_score": 0.0,
            "threshold": 1.0,
            "verdict": "未发现明显异常",
        }


class _UnsafeDetector(_StubDetector):
    def analyze_wav_bytes(self, data: bytes) -> dict[str, object]:
        result = super().analyze_wav_bytes(data)
        result["verdict"] = "泵轴承已损坏"
        return result


class AudioPluggableTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gongwei-audio-backend-test-")
        self.addCleanup(temporary.cleanup)
        patcher = patch("audio_service.AUDIO_STORAGE", Path(temporary.name) / "uploads")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_registered_backend_can_replace_default_without_filename_logic(self):
        register_detector_backend("stub", _StubDetector)
        try:
            sample_rate = 16000
            buffer = io.BytesIO()
            sf.write(buffer, np.zeros(sample_rate, dtype=np.float32) + 0.1, sample_rate, format="WAV", subtype="PCM_16")
            with tempfile.TemporaryDirectory() as directory:
                result = analyze_audio_payload(
                    {"filename": "anything.wav", "audio_base64": base64.b64encode(buffer.getvalue()).decode("ascii")},
                    db_path=Path(directory) / "stage2.db",
                    detector_backend="stub",
                )
            self.assertEqual(result["detector_backend"], "stub")
            self.assertEqual(result["model_version"], "stub-v1")
            self.assertEqual(result["verdict"], "未发现明显异常")
        finally:
            unregister_detector_backend("stub")

    def test_unknown_backend_is_rejected_explicitly(self):
        with self.assertRaisesRegex(ValueError, "声音检测后端"):
            analyze_audio_payload({"audio_base64": ""}, detector_backend="does-not-exist")

    def test_backend_cannot_persist_a_component_diagnosis(self):
        register_detector_backend("unsafe", _UnsafeDetector)
        try:
            with tempfile.TemporaryDirectory() as directory:
                sample_rate = 16000
                buffer = io.BytesIO()
                sf.write(buffer, np.zeros(sample_rate, dtype=np.float32) + 0.1, sample_rate, format="WAV", subtype="PCM_16")
                with self.assertRaisesRegex(ValueError, "声音检测结果"):
                    analyze_audio_payload(
                        {"filename": "anything.wav", "audio_base64": base64.b64encode(buffer.getvalue()).decode("ascii")},
                        db_path=Path(directory) / "stage2.db",
                        detector_backend="unsafe",
                    )
        finally:
            unregister_detector_backend("unsafe")


if __name__ == "__main__":
    unittest.main(verbosity=2)

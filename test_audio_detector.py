"""Failing-first tests for the CPU audio detector contract."""
from __future__ import annotations

import unittest
import io
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audio_detector import (
    MODEL_VERSION,
    extract_log_mel_features,
    fit_detector,
    score_audio,
    verdict_for_score,
    analyze_wav_bytes,
)


class AudioDetectorTests(unittest.TestCase):
    def setUp(self):
        self.sample_rate = 16000
        t = np.arange(self.sample_rate, dtype=np.float32) / self.sample_rate
        self.normal = [np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 445 * t)]
        self.abnormal = np.sin(2 * np.pi * 3000 * t)

    def test_feature_shape_is_fixed_and_does_not_accept_filename(self):
        features = extract_log_mel_features(self.normal[0], self.sample_rate)
        self.assertEqual(features.ndim, 1)
        self.assertGreater(features.size, 16)
        with self.assertRaises(TypeError):
            extract_log_mel_features("normal_file.wav", self.sample_rate)

    def test_normal_only_model_returns_score_threshold_and_safe_verdict(self):
        model = fit_detector(self.normal, self.sample_rate)
        self.assertEqual(model["model_version"], MODEL_VERSION)
        normal_score = score_audio(model, self.normal[0], self.sample_rate)
        abnormal_score = score_audio(model, self.abnormal, self.sample_rate)
        self.assertIsInstance(normal_score, float)
        self.assertIn(verdict_for_score(normal_score, model["threshold"]), {"未发现明显异常", "疑似异常"})
        self.assertGreaterEqual(abnormal_score, 0.0)
        self.assertIn("threshold", model)


class AudioDecodeBoundaryTests(unittest.TestCase):
    model = {"model_version": MODEL_VERSION, "sample_rate": 16000, "mean": [0.0] * 64, "scale": [1.0] * 64, "threshold": 1.0}

    def _bytes(self, *, frames=16000, sample_rate=16000, channels=1, format="WAV"):
        audio = np.sin(np.arange(frames, dtype=np.float32) * 0.1)
        if channels > 1:
            audio = np.repeat(audio[:, None], channels, axis=1)
        buffer = io.BytesIO()
        sf.write(buffer, audio, sample_rate, format=format)
        return buffer.getvalue()

    def test_invalid_headers_are_rejected_before_sample_decoding(self):
        cases = [
            {"format": "FLAC"},
            {"sample_rate": 8000},
            {"frames": 16000 * 31},
            {"frames": 10},
            {"channels": 9},
        ]
        for options in cases:
            data = self._bytes(**options)
            with self.subTest(options=options), patch.object(sf.SoundFile, "read", side_effect=AssertionError("sample decoding must not occur")) as read:
                with self.assertRaises(ValueError):
                    analyze_wav_bytes(data, self.model)
                read.assert_not_called()

    def test_valid_wav_uses_a_bounded_read(self):
        data = self._bytes()
        original = sf.SoundFile.read
        calls = []
        def read(sound, frames=-1, *args, **kwargs):
            calls.append(frames)
            return original(sound, frames, *args, **kwargs)
        with patch.object(sf.SoundFile, "read", new=read):
            result = analyze_wav_bytes(data, self.model)
        self.assertEqual(result["sample_rate"], 16000)
        self.assertEqual(result["duration_seconds"], 1.0)
        self.assertTrue(calls)
        self.assertTrue(all(0 < count <= 16001 for count in calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Offline checks for archive and HTTP Range input boundaries."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import prepare_mimii


class PrepareMimiiBoundaryTests(unittest.TestCase):
    def test_archive_member_targets_stay_inside_output(self):
        self.assertTrue(hasattr(prepare_mimii, "_safe_member_target"), "ZIP extraction must validate a resolved target before opening it")
        with tempfile.TemporaryDirectory() as root, patch.object(prepare_mimii, "OUTPUT", Path(root) / "output"):
            for member in ("../../../outside.wav", "..\\outside.wav", "/outside.wav", "C:/outside.wav", "C:outside.wav", "\\\\server\\share\\outside.wav", "id_00/normal/clip.wav:stream"):
                with self.subTest(member=member), self.assertRaises(ValueError):
                    prepare_mimii._safe_member_target(member, "0_dB_pump.zip")
            target = prepare_mimii._safe_member_target("id_00/normal/clip.wav", "0_dB_pump.zip")
            self.assertEqual(target, (Path(root) / "output/wav/0_dB_pump/id_00/normal/clip.wav").resolve())

    def test_short_http_range_response_is_rejected_without_caching(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 206
        response.headers = {"Content-Range": "bytes 0-7/8"}
        response.read.return_value = b"short"
        reader = prepare_mimii.HTTPRangeReader("https://example.invalid/archive.zip", 8, chunk_size=8)
        with patch.object(prepare_mimii.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "length|short|长度|不完整"):
                reader._chunk(0)
        self.assertEqual(reader.cache, {})

    def test_valid_range_reader_bounds_each_response_read(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 206
        response.headers = {"Content-Range": "bytes 0-7/8"}
        response.read.return_value = b"12345678"
        reader = prepare_mimii.HTTPRangeReader("https://example.invalid/archive.zip", 8, chunk_size=8)
        with patch.object(prepare_mimii.urllib.request, "urlopen", return_value=response):
            self.assertEqual(reader.read(8), b"12345678")
        response.read.assert_called_once_with(9)


if __name__ == "__main__":
    unittest.main()

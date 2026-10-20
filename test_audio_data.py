"""Failing-first tests for the frozen MIMII pump data contract."""
from __future__ import annotations

import unittest

from audio_data import assign_splits, validate_split_integrity


class AudioDataContractTests(unittest.TestCase):
    def test_grouped_split_is_deterministic_and_disjoint(self):
        rows = [
            {"member": "pump/id_00/section_00/a.wav", "machine_id": "00", "section": "00", "noise_db": "0", "label": "normal", "group_id": "00-00-0"},
            {"member": "pump/id_00/section_00/b.wav", "machine_id": "00", "section": "00", "noise_db": "0", "label": "normal", "group_id": "00-00-0"},
            {"member": "pump/id_02/section_00/c.wav", "machine_id": "02", "section": "00", "noise_db": "0", "label": "normal", "group_id": "02-00-0"},
            {"member": "pump/id_04/section_00/d.wav", "machine_id": "04", "section": "00", "noise_db": "0", "label": "abnormal", "group_id": "04-00-0"},
            {"member": "pump/id_06/section_00/e.wav", "machine_id": "06", "section": "00", "noise_db": "0", "label": "abnormal", "group_id": "06-00-0"},
        ]
        first = assign_splits(rows, seed=20261003)
        second = assign_splits(rows, seed=20261003)
        self.assertEqual(first, second)
        validate_split_integrity(first)
        groups = {split: {row["group_id"] for row in values} for split, values in first.items()}
        self.assertTrue(groups["train"].isdisjoint(groups["validation"]))
        self.assertTrue(groups["validation"].isdisjoint(groups["test"]))

    def test_manifest_labels_are_explicit_metadata(self):
        rows = [{"member": "normal/secret.wav", "label": "normal", "group_id": "g1"}, {"member": "abnormal/other.wav", "label": "abnormal", "group_id": "g2"}, {"member": "normal/third.wav", "label": "normal", "group_id": "g3"}]
        split = assign_splits(rows, seed=7)
        all_rows = [row for values in split.values() for row in values]
        self.assertEqual({row["label"] for row in all_rows}, {"normal", "abnormal"})
        self.assertTrue(all("feature_source" not in row for row in all_rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)

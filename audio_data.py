"""Deterministic manifest and split helpers for the MIMII pump subset."""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

SPLITS = ("train", "validation", "test")


def assign_splits(rows: list[dict[str, Any]], *, seed: int = 20261003) -> dict[str, list[dict[str, Any]]]:
    """Assign whole recording groups to deterministic train/validation/test splits."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        group_id = str(row.get("group_id") or "")
        if not group_id:
            raise ValueError("manifest row is missing group_id")
        groups[group_id].append(dict(row))
    group_ids = sorted(groups)
    if len(group_ids) < 3:
        raise ValueError("at least three recording groups are required")
    shuffled = list(group_ids)
    random.Random(seed).shuffle(shuffled)
    train_count = max(1, int(round(len(shuffled) * 0.6)))
    validation_count = max(1, int(round(len(shuffled) * 0.2)))
    if train_count + validation_count >= len(shuffled):
        validation_count = 1
        train_count = len(shuffled) - 2
    boundaries = {
        "train": shuffled[:train_count],
        "validation": shuffled[train_count:train_count + validation_count],
        "test": shuffled[train_count + validation_count:],
    }
    return {
        split: [row for group_id in group_ids_for_split for row in groups[group_id]]
        for split, group_ids_for_split in boundaries.items()
    }


def validate_split_integrity(splits: dict[str, list[dict[str, Any]]]) -> None:
    if set(splits) != set(SPLITS):
        raise ValueError(f"splits must contain exactly {SPLITS}")
    seen: dict[str, str] = {}
    for split in SPLITS:
        if not splits[split]:
            raise ValueError(f"split {split} is empty")
        for row in splits[split]:
            group_id = str(row.get("group_id") or "")
            if not group_id:
                raise ValueError("manifest row is missing group_id")
            previous = seen.setdefault(group_id, split)
            if previous != split:
                raise ValueError(f"group {group_id} occurs in both {previous} and {split}")
            if row.get("label") not in {"normal", "abnormal"}:
                raise ValueError("manifest row label must be normal or abnormal")


def flatten_splits(splits: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        for row in splits[split]:
            rows.append({**row, "split": split})
    return rows

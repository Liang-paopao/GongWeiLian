"""Prepare a small, reproducible MIMII pump subset using HTTP Range requests.

The official archives are multi-gigabyte ZIP files.  This script reads only ZIP
metadata and the selected WAV members, then records every source and checksum.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audio_data import assign_splits, flatten_splits, validate_split_integrity

OUTPUT = ROOT / "data" / "mimii_pump"
RECORD_URL = "https://zenodo.org/api/records/3384388"
ARCHIVE_RE = re.compile(r"^(?P<noise>-?\d+)_dB_pump\.zip$")
MACHINE_RE = re.compile(r"(?:^|[/\\])id_(?P<machine>\d+)(?:[/\\]|$)", re.IGNORECASE)
SECTION_RE = re.compile(r"section_(?P<section>\d+)", re.IGNORECASE)


class HTTPRangeReader(io.RawIOBase):
    """Seekable read-only file that fetches fixed-size HTTP byte ranges."""

    def __init__(self, url: str, size: int, *, chunk_size: int = 4 * 1024 * 1024):
        self.url = url
        self.size = int(size)
        self.chunk_size = int(chunk_size)
        if self.size < 0 or self.chunk_size <= 0:
            raise ValueError("Range size must be nonnegative and chunk_size must be positive")
        self.position = 0
        self.cache: dict[int, bytes] = {}

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            target = offset
        elif whence == io.SEEK_CUR:
            target = self.position + offset
        elif whence == io.SEEK_END:
            target = self.size + offset
        else:
            raise ValueError("unsupported whence")
        if target < 0:
            raise ValueError("negative seek")
        self.position = min(target, self.size)
        return self.position

    def _chunk(self, index: int) -> bytes:
        if index not in self.cache:
            start = index * self.chunk_size
            end = min(self.size - 1, start + self.chunk_size - 1)
            request = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status != 206:
                    raise RuntimeError(f"Zenodo did not honor Range request: HTTP {response.status}")
                content_range = response.headers.get("Content-Range", "")
                if content_range != f"bytes {start}-{end}/{self.size}":
                    raise RuntimeError(f"unexpected Content-Range: {content_range}")
                expected = end - start + 1
                payload = response.read(expected + 1)
                if len(payload) != expected:
                    raise RuntimeError("HTTP Range response length is incomplete or exceeds the requested range")
                self.cache[index] = payload
        return self.cache[index]

    def read(self, size: int = -1) -> bytes:
        if self.position >= self.size:
            return b""
        remaining = self.size - self.position if size is None or size < 0 else min(size, self.size - self.position)
        parts: list[bytes] = []
        while remaining:
            index = self.position // self.chunk_size
            offset = self.position % self.chunk_size
            chunk = self._chunk(index)
            take = min(remaining, len(chunk) - offset)
            if take <= 0:
                raise RuntimeError("HTTP Range returned an incomplete chunk; no read progress")
            parts.append(chunk[offset:offset + take])
            self.position += take
            remaining -= take
        return b"".join(parts)


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _label_from_member(member: str) -> str | None:
    parts = [part.lower() for part in member.replace("\\", "/").split("/")]
    for part in parts[:-1]:
        if part in {"normal", "abnormal"}:
            return part
    # Public MIMII archives use the label in the recording path when no label
    # directory is present.  This metadata is written to the manifest only;
    # it is never supplied to the detector as an input feature.
    lower = parts[-1]
    if "_normal_" in lower:
        return "normal"
    if "_abnormal_" in lower:
        return "abnormal"
    return None


def _member_metadata(member: str, archive_name: str) -> dict[str, str] | None:
    normalized = member.replace("\\", "/")
    label = _label_from_member(normalized)
    machine_match = MACHINE_RE.search(normalized)
    section_match = SECTION_RE.search(normalized)
    archive_match = ARCHIVE_RE.match(archive_name)
    if not (label and machine_match and archive_match):
        return None
    machine_id = machine_match.group("machine")
    section = section_match.group("section") if section_match else "all"
    noise_db = archive_match.group("noise")
    return {
        "machine_id": machine_id,
        "section": section,
        "noise_db": noise_db,
        "label": label,
        "group_id": f"id_{machine_id}-section_{section}-{noise_db}dB",
    }


def _select_members(infos: list[zipfile.ZipInfo], archive_name: str, per_label: int) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for info in infos:
        if info.is_dir() or not info.filename.lower().endswith(".wav"):
            continue
        metadata = _member_metadata(info.filename, archive_name)
        if metadata:
            candidates.append({"member": info.filename, **metadata})
    candidates.sort(key=lambda row: row["member"])
    selected: list[dict[str, str]] = []
    buckets: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in candidates:
        key = (row["group_id"], row["label"], row["machine_id"])
        buckets.setdefault(key, []).append(row)
    for key in sorted(buckets):
        selected.extend(buckets[key][:per_label])
    return selected


def _safe_member_target(member: str, archive_name: str) -> Path:
    """Validate both Windows and ZIP path syntax before any filesystem write."""
    normalized = member.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (not ARCHIVE_RE.fullmatch(archive_name) or not normalized or relative.is_absolute()
            or PureWindowsPath(member).drive or any(part in {".", ".."} or ":" in part for part in normalized.split("/"))):
        raise ValueError("ZIP member path is not a safe relative path")
    output = OUTPUT.resolve()
    target = (output / "wav" / archive_name.removesuffix(".zip") / relative).resolve()
    if not target.is_relative_to(output):
        raise ValueError("ZIP member resolves outside the output directory")
    return target


def prepare(*, per_label: int = 4, archives: tuple[str, ...] = ("0_dB_pump.zip",)) -> dict[str, Any]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    metadata = fetch_json(RECORD_URL)
    archive_map = {entry["key"]: entry for entry in metadata["files"]}
    rows: list[dict[str, str]] = []
    source_archives: list[dict[str, Any]] = []
    for archive_name in archives:
        entry = archive_map[archive_name]
        source_archives.append({"key": entry["key"], "size": entry["size"], "checksum": entry["checksum"], "url": entry["links"]["self"]})
        reader = HTTPRangeReader(entry["links"]["self"], entry["size"])
        with zipfile.ZipFile(reader) as archive:
            rows.extend({**row, "archive": archive_name} for row in _select_members(archive.infolist(), archive_name, per_label))
            for row in rows:
                if row.get("archive") != archive_name:
                    continue
                target = _safe_member_target(row["member"], row["archive"])
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    with archive.open(row["member"]) as source, target.open("wb") as destination:
                        destination.write(source.read(20 * 1024 * 1024 + 1))
                    digest = hashlib.sha256(target.read_bytes()).hexdigest()
                else:
                    digest = hashlib.sha256(target.read_bytes()).hexdigest()
                row["local_path"] = str(target.relative_to(ROOT))
                row["sha256"] = digest
    splits = assign_splits(rows)
    validate_split_integrity(splits)
    all_rows = flatten_splits(splits)
    with (OUTPUT / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=sorted(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    (OUTPUT / "splits.json").write_text(json.dumps({"seed": 20261003, "splits": {key: [row["member"] for row in value] for key, value in splits.items()}}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT / "source.json").write_text(json.dumps({"doi": "10.5281/zenodo.3384388", "record_url": "https://zenodo.org/records/3384388", "license": "CC BY-SA 4.0", "version": metadata.get("metadata", {}).get("version"), "retrieved_at": datetime.now(timezone.utc).isoformat(), "archives": source_archives, "selection": {"per_label_per_group": per_label, "archives": list(archives), "note": "Labels are manifest ground truth metadata only; detector input excludes member names and labels."}}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"rows": len(all_rows), "counts": {split: len(values) for split, values in splits.items()}, "output": str(OUTPUT)}


def prepare_offline(*, per_label: int = 3, archive_name: str = "0_dB_pump.zip") -> dict[str, Any]:
    """Rebuild the manifest from already cached WAVs without network access."""
    root = OUTPUT / "wav" / archive_name.removesuffix(".zip")
    cached = sorted(root.rglob("*.wav"))
    rows: list[dict[str, str]] = []
    buckets: dict[tuple[str, str], list[dict[str, str]]] = {}
    for path in cached:
        try:
            import soundfile as sf
            sf.info(path)
        except Exception:
            # Interrupted range downloads are ignored and never enter the
            # manifest or the model evaluation set.
            continue
        member = path.relative_to(root).as_posix()
        metadata = _member_metadata(member, archive_name)
        if metadata:
            row = {"member": member, "archive": archive_name, "local_path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **metadata}
            buckets.setdefault((row["group_id"], row["label"]), []).append(row)
    for key in sorted(buckets):
        rows.extend(sorted(buckets[key], key=lambda row: row["member"])[:per_label])
    if not rows:
        raise RuntimeError(f"no cached WAV files found under {root}")
    splits = assign_splits(rows)
    validate_split_integrity(splits)
    all_rows = flatten_splits(splits)
    with (OUTPUT / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=sorted(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    (OUTPUT / "splits.json").write_text(json.dumps({"seed": 20261003, "offline_rebuild": True, "splits": {key: [row["member"] for row in value] for key, value in splits.items()}}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"rows": len(all_rows), "counts": {split: len(values) for split, values in splits.items()}, "output": str(OUTPUT), "mode": "offline_cached"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-label", type=int, default=4)
    parser.add_argument("--archive", action="append", dest="archives")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    archives = tuple(args.archives or ("0_dB_pump.zip",))
    result = prepare_offline(per_label=args.per_label, archive_name=archives[0]) if args.offline else prepare(per_label=args.per_label, archives=archives)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

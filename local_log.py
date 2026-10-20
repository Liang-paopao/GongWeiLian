"""Local development logs only; these are NOT platform statistics or AMP reports."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path(os.environ.get("GONGWEI_LOG_DIR") or (Path(__file__).resolve().parent / "logs"))
LOG_CATEGORIES = ("Heartbeat", "System", "Message", "Access", "Metrics", "Audit")
_SENSITIVE_KEYS = {"password", "secret", "token", "authorization", "private_key", "client_secret", "audio_base64"}
MAX_LOG_BYTES = 2 * 1024 * 1024


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[redacted]" if str(key).lower() in _SENSITIVE_KEYS else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _append(path: Path, row: dict[str, Any]) -> None:
    encoded = json.dumps(_redact(row), ensure_ascii=False) + "\n"
    if path.exists() and path.stat().st_size + len(encoded.encode("utf-8")) > MAX_LOG_BYTES:
        rotated = path.with_suffix(path.suffix + ".1")
        if rotated.exists():
            rotated.unlink()
        path.replace(rotated)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(encoded)


def record(actor: str, event: str, details: dict[str, Any]) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    row = {"time_utc": datetime.now(timezone.utc).isoformat(),
           "scope": "local_simulation_only", "event": event, **details}
    _append(LOG_DIR / f"{actor}.jsonl", row)
    event_lower = event.lower()
    category = "Audit" if any(word in event_lower for word in ("audit", "compensat", "recover", "duplicate")) else "Message" if any(word in event_lower for word in ("request", "response", "message", "aip")) else "System"
    record_category(category, actor, event, details)


def record_category(category: str, actor: str, event: str, details: dict[str, Any]) -> None:
    if category not in LOG_CATEGORIES:
        raise ValueError(f"未知日志类别：{category}")
    LOG_DIR.mkdir(exist_ok=True)
    _append(LOG_DIR / f"{category.lower()}.jsonl", {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "local_simulation_only", "category": category, "actor": actor,
        "event": event, **details,
    })


def record_all_categories(task_id: str, message_id: str) -> None:
    """Write a compact end-to-end sample used by audit checks and demos."""
    for category in LOG_CATEGORIES:
        record_category(category, "observability", "sample", {"task_id": task_id, "message_id": message_id})

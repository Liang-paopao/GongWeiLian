"""Optional OpenAI-compatible parser boundary for the Leader.

The local project remains usable without a model endpoint.  When all three
LLM_* settings are present, this adapter asks for a strict JSON intent and
validates it before the deterministic business layer can consume it.  Keys
and response bodies are never written to project logs.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class LlmIntent:
    intent: str
    fields: dict[str, Any]
    missing_fields: list[str]


REQUIRED_FIELDS = ("pump_id", "work_date", "start_time", "duration_minutes", "description")
ALLOWED_INTENTS = {"schedule_inspection", "revise_task", "cancel_task"}


def configured() -> bool:
    return all(os.environ.get(name, "").strip() for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))


def _validate(payload: Any) -> LlmIntent | None:
    if not isinstance(payload, dict) or payload.get("intent") not in ALLOWED_INTENTS:
        return None
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return None
    if fields.get("duration_minutes") is not None:
        try:
            fields["duration_minutes"] = int(fields["duration_minutes"])
        except (TypeError, ValueError):
            return None
        if not 1 <= fields["duration_minutes"] <= 24 * 60:
            return None
    missing = payload.get("missing_fields")
    if not isinstance(missing, list) or any(item not in REQUIRED_FIELDS for item in missing):
        return None
    return LlmIntent(payload["intent"], fields, list(dict.fromkeys(missing)))


def parse(text: str, *, today: date) -> LlmIntent | None:
    if not configured():
        return None
    endpoint = os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    body = {
        "model": os.environ["LLM_MODEL"],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Extract a maintenance scheduling intent as JSON with intent, fields, missing_fields. Use ISO dates and HH:MM times. Do not invent missing values."},
            {"role": "user", "content": f"Today is {today.isoformat()}. Request: {text}"},
        ],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", "8"))) as response:
            outer = json.loads(response.read().decode("utf-8"))
        content = outer["choices"][0]["message"]["content"]
        return _validate(json.loads(content))
    except (OSError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError, urllib.error.URLError):
        return None

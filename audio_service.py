"""Audio analysis persistence and boundary checks shared by Partner and Leader."""
from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from audio_detector import AudioDetector, LogMelGaussianDetector
from stage2_db import connect_db, initialize_database, transaction

ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "models" / "audio" / "mimii_pump_baseline.json"
AUDIO_STORAGE = ROOT / "data" / "audio_uploads"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
SAFE_VERDICTS = frozenset({"未发现明显异常", "疑似异常"})
DetectorFactory = Callable[[], AudioDetector]
_DETECTOR_FACTORIES: dict[str, DetectorFactory] = {
    "logmel_gaussian": lambda: LogMelGaussianDetector(MODEL_PATH),
}


def audio_enabled() -> bool:
    """Allow the auxiliary detector to be disabled without affecting manual flow."""
    return os.environ.get("GONGWEI_AUDIO_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def register_detector_backend(name: str, factory: DetectorFactory) -> None:
    """Register a detector implementation for local tests or a public baseline."""
    normalized = str(name).strip()
    if not normalized or not callable(factory):
        raise ValueError("声音检测后端名称和工厂函数不能为空。")
    _DETECTOR_FACTORIES[normalized] = factory


def unregister_detector_backend(name: str) -> None:
    if name == "logmel_gaussian":
        raise ValueError("不能移除默认声音检测后端。")
    _DETECTOR_FACTORIES.pop(str(name), None)


def get_detector_backend_name() -> str:
    return os.environ.get("GONGWEI_AUDIO_DETECTOR", "logmel_gaussian").strip() or "logmel_gaussian"


def get_audio_detector(name: str | None = None) -> AudioDetector:
    backend = str(name or get_detector_backend_name()).strip()
    factory = _DETECTOR_FACTORIES.get(backend)
    if factory is None:
        raise ValueError(f"声音检测后端不受支持：{backend}")
    return factory()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def analyze_audio_payload(payload: dict[str, Any], *, db_path: str | Path | None = None,
                          detector_backend: str | None = None) -> dict[str, Any]:
    if not audio_enabled():
        raise ValueError("声音辅助工具当前已停用，请改用手动检查入口。")
    # Resolve the backend before decoding so an unknown configuration cannot
    # silently fall back to a model or inspect a filename/label.
    detector = get_audio_detector(detector_backend)
    encoded = payload.get("audio_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("缺少 audio_base64。")
    if len(encoded) > MAX_AUDIO_BYTES * 2:
        raise ValueError("录音文件超过 10 MB 限制。")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("audio_base64 不是有效编码。") from exc
    if len(raw) > MAX_AUDIO_BYTES:
        raise ValueError("录音文件超过 10 MB 限制。")
    result = dict(detector.analyze_wav_bytes(raw))
    result.setdefault("detector_backend", getattr(detector, "backend_name", get_detector_backend_name()))
    if result.get("verdict") not in SAFE_VERDICTS:
        raise ValueError("声音检测结果必须是未发现明显异常或疑似异常。")
    analysis_id = "audio-" + uuid.uuid4().hex
    digest = hashlib.sha256(raw).hexdigest()
    filename = str(payload.get("filename") or "upload.wav")[:160]
    target = AUDIO_STORAGE / f"{analysis_id}.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    try:
        storage_path = str(target.relative_to(ROOT))
    except ValueError:
        # Tests may inject an isolated temporary storage directory outside the
        # project root; keep that path valid without changing production output.
        storage_path = str(target)
    timestamp = _now()
    initialize_database(db_path)
    with transaction(db_path) as connection:
        connection.execute(
            "INSERT INTO audio_analyses(id,sha256,original_filename,storage_path,model_version,sample_rate,duration_seconds,anomaly_score,threshold,verdict,status,user_confirmed,error_message,request_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (analysis_id, digest, filename, storage_path, result["model_version"], result["sample_rate"], result["duration_seconds"], result["anomaly_score"], result["threshold"], result["verdict"], "analyzed", 0, None, None, timestamp, timestamp),
        )
    return {"analysis_id": analysis_id, "sha256": digest, "status": "analyzed", "user_confirmed": False, **result}


def get_audio_analysis(analysis_id: str, *, db_path: str | Path | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    with connect_db(db_path) as connection:
        row = connection.execute("SELECT * FROM audio_analyses WHERE id=?", (analysis_id,)).fetchone()
    if row is None:
        raise ValueError("声音分析记录不存在。")
    result = dict(row)
    result["user_confirmed"] = bool(result["user_confirmed"])
    return result


def confirm_audio_analysis(analysis_id: str, *, db_path: str | Path | None = None) -> dict[str, Any]:
    timestamp = _now()
    initialize_database(db_path)
    with transaction(db_path) as connection:
        row = connection.execute("SELECT * FROM audio_analyses WHERE id=?", (analysis_id,)).fetchone()
        if row is None:
            raise ValueError("声音分析记录不存在。")
        connection.execute("UPDATE audio_analyses SET status='confirmed',user_confirmed=1,updated_at=? WHERE id=?", (timestamp, analysis_id))
    return get_audio_analysis(analysis_id, db_path=db_path)


def link_audio_analysis(analysis_id: str, request_id: str, *, db_path: str | Path | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    with transaction(db_path) as connection:
        row = connection.execute("SELECT id FROM audio_analyses WHERE id=?", (analysis_id,)).fetchone()
        if row is None:
            raise ValueError("声音分析记录不存在。")
        connection.execute("UPDATE audio_analyses SET request_id=?,updated_at=? WHERE id=?", (request_id, _now(), analysis_id))
    return get_audio_analysis(analysis_id, db_path=db_path)

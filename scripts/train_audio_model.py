"""Train and evaluate the frozen MIMII pump CPU baseline."""
from __future__ import annotations

import csv
import json
import platform
import sys
import time
from pathlib import Path

import soundfile as sf
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio_detector import fit_detector, save_model, score_audio, verdict_for_score  # noqa: E402

MANIFEST = ROOT / "data" / "mimii_pump" / "manifest.csv"
MODEL_PATH = ROOT / "models" / "audio" / "mimii_pump_baseline.json"
METRICS_PATH = ROOT / "reports" / "stage4_audio_metrics.json"


def load_rows() -> list[dict[str, str]]:
    with MANIFEST.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def read_audio(row: dict[str, str]):
    audio, sample_rate = sf.read(ROOT / row["local_path"], dtype="float32", always_2d=False)
    return audio, int(sample_rate)


def train_and_evaluate() -> dict[str, object]:
    rows = load_rows()
    train_normal = [row for row in rows if row["split"] == "train" and row["label"] == "normal"]
    validation_normal = [row for row in rows if row["split"] == "validation" and row["label"] == "normal"]
    test_rows = [row for row in rows if row["split"] == "test"]
    if not train_normal or not validation_normal or not test_rows:
        raise RuntimeError("manifest must contain train normal, validation normal and test rows")
    train_audio = [read_audio(row)[0] for row in train_normal]
    sample_rate = read_audio(train_normal[0])[1]
    validation_audio = [read_audio(row)[0] for row in validation_normal]
    model = fit_detector(train_audio, sample_rate, validation_normal=validation_audio)
    save_model(model, MODEL_PATH)

    scored: list[dict[str, object]] = []
    for row in test_rows:
        started = time.perf_counter()
        audio, row_rate = read_audio(row)
        score = score_audio(model, audio, row_rate)
        scored.append({"member": row["member"], "label": row["label"], "score": score, "verdict": verdict_for_score(score, model["threshold"]), "duration_ms": round((time.perf_counter() - started) * 1000, 3)})
    y_true = [1 if row["label"] == "abnormal" else 0 for row in scored]
    y_score = [float(row["score"]) for row in scored]
    y_pred = [1 if score >= model["threshold"] else 0 for score in y_score]
    normal_total = max(1, sum(1 for label in y_true if label == 0))
    abnormal_total = max(1, sum(1 for label in y_true if label == 1))
    false_positive = sum(1 for actual, predicted in zip(y_true, y_pred) if actual == 0 and predicted == 1)
    false_negative = sum(1 for actual, predicted in zip(y_true, y_pred) if actual == 1 and predicted == 0)
    metrics = {
        "model_version": model["model_version"],
        "dataset": "MIMII public 1.0 pump 0 dB fixed subset",
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "split_counts": {split: sum(1 for row in rows if row["split"] == split) for split in ("train", "validation", "test")},
        "normal_train_count": len(train_normal),
        "validation_normal_count": len(validation_normal),
        "test_normal_count": sum(1 for row in test_rows if row["label"] == "normal"),
        "test_abnormal_count": sum(1 for row in test_rows if row["label"] == "abnormal"),
        "roc_auc": round(float(roc_auc_score(y_true, y_score)), 6),
        "threshold": model["threshold"],
        "false_positive_rate": round(false_positive / normal_total, 6),
        "false_negative_rate": round(false_negative / abnormal_total, 6),
        "mean_inference_ms": round(sum(float(row["duration_ms"]) for row in scored) / len(scored), 3),
        "model_size_bytes": MODEL_PATH.stat().st_size,
        "runtime": {"python": sys.version, "platform": platform.platform(), "cpu": platform.processor() or "unknown"},
        "scores": scored,
        "limitations": ["小样本固定子集仅用于本机阶段四验收。", "结果只表示未发现明显异常或疑似异常，不诊断具体零件。"],
    }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


if __name__ == "__main__":
    print(json.dumps(train_and_evaluate(), ensure_ascii=False, indent=2))

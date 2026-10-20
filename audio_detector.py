"""CPU-only log-Mel statistical anomaly detector for pump recordings."""
from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Any, Iterable, Protocol

import numpy as np
import soundfile as sf

MODEL_VERSION = "mimii-pump-logmel-gaussian-v1"
MIN_DURATION_SECONDS = 0.25
MAX_DURATION_SECONDS = 30.0
MAX_AUDIO_CHANNELS = 8
MAX_SAMPLE_RATE = 192000
MAX_DECODED_BYTES = 32 * 1024 * 1024


class AudioDetector(Protocol):
    """Small contract for an auxiliary detector backend.

    The business workflow only depends on this method and the two metadata
    fields.  A different public baseline or a locally supplied model can be
    registered without changing the Leader, Partner or confirmation flow.
    """

    backend_name: str
    model_version: str

    def analyze_wav_bytes(self, data: bytes) -> dict[str, Any]:
        ...


def validate_audio(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if isinstance(audio, (str, bytes, bytearray, Path)):
        raise TypeError("检测器只接受已解码的音频数组，不读取文件名或标签。")
    values = np.asarray(audio, dtype=np.float32)
    if values.ndim == 2:
        values = values.mean(axis=1)
    if values.ndim != 1:
        raise ValueError("录音必须是单声道或多声道 WAV。")
    if sample_rate <= 0:
        raise ValueError("录音采样率无效。")
    if values.size < int(sample_rate * MIN_DURATION_SECONDS):
        raise ValueError("录音时长过短，至少需要 0.25 秒。")
    if values.size > int(sample_rate * MAX_DURATION_SECONDS):
        raise ValueError("录音时长超过 30 秒限制。")
    if not np.isfinite(values).all():
        raise ValueError("录音包含无效数值。")
    peak = float(np.max(np.abs(values)))
    if peak <= 1e-9:
        raise ValueError("录音没有有效声音信号。")
    return values


def _mel_filter_bank(sample_rate: int, n_fft: int, n_mels: int) -> np.ndarray:
    def hz_to_mel(value: float) -> float:
        return 2595.0 * math.log10(1.0 + value / 700.0)

    def mel_to_hz(value: float) -> float:
        return 700.0 * (10 ** (value / 2595.0) - 1.0)

    low = hz_to_mel(20.0)
    high = hz_to_mel(sample_rate / 2.0)
    points = np.linspace(low, high, n_mels + 2)
    bins = np.floor((n_fft + 1) * np.array([mel_to_hz(item) for item in points]) / sample_rate).astype(int)
    filters = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for index in range(n_mels):
        left, center, right = bins[index:index + 3]
        if center > left:
            filters[index, left:center] = np.linspace(0.0, 1.0, center - left, endpoint=False)
        if right > center:
            filters[index, center:right] = np.linspace(1.0, 0.0, right - center, endpoint=False)
    return filters


def extract_log_mel_features(audio: np.ndarray, sample_rate: int, *, n_fft: int = 512, hop_length: int = 256, n_mels: int = 32) -> np.ndarray:
    values = validate_audio(audio, sample_rate)
    if values.size < n_fft:
        values = np.pad(values, (0, n_fft - values.size))
    frame_count = 1 + max(0, (values.size - n_fft) // hop_length)
    frames = np.stack([values[index * hop_length:index * hop_length + n_fft] for index in range(frame_count)])
    spectrum = np.fft.rfft(frames * np.hanning(n_fft), n=n_fft, axis=1)
    power = (np.abs(spectrum) ** 2).astype(np.float32)
    mel = power @ _mel_filter_bank(sample_rate, n_fft, n_mels).T
    log_mel = np.log(np.maximum(mel, 1e-10)).astype(np.float32)
    return np.concatenate([log_mel.mean(axis=0), log_mel.std(axis=0)]).astype(np.float32)


def fit_detector(normal_audio: Iterable[np.ndarray], sample_rate: int, *, validation_normal: Iterable[np.ndarray] | None = None) -> dict[str, Any]:
    train_features = np.stack([extract_log_mel_features(audio, sample_rate) for audio in normal_audio])
    if train_features.shape[0] < 2:
        raise ValueError("至少需要两段正常训练录音。")
    mean = train_features.mean(axis=0)
    scale = train_features.std(axis=0)
    scale[scale < 1e-6] = 1e-6
    model: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "sample_rate": int(sample_rate),
        "feature_dim": int(train_features.shape[1]),
        "mean": mean.tolist(),
        "scale": scale.tolist(),
    }
    validation_scores = [score_features(model, extract_log_mel_features(audio, sample_rate)) for audio in (validation_normal or normal_audio)]
    model["threshold"] = float(np.percentile(validation_scores, 95.0))
    return model


def score_features(model: dict[str, Any], features: np.ndarray) -> float:
    mean = np.asarray(model["mean"], dtype=np.float32)
    scale = np.asarray(model["scale"], dtype=np.float32)
    values = np.asarray(features, dtype=np.float32)
    return float(np.sqrt(np.mean(((values - mean) / scale) ** 2)))


def score_audio(model: dict[str, Any], audio: np.ndarray, sample_rate: int) -> float:
    if int(model["sample_rate"]) != int(sample_rate):
        raise ValueError(f"模型需要 {model['sample_rate']} Hz 录音。")
    return score_features(model, extract_log_mel_features(audio, sample_rate))


def verdict_for_score(score: float, threshold: float) -> str:
    return "疑似异常" if float(score) >= float(threshold) else "未发现明显异常"


def analyze_wav_bytes(data: bytes, model: dict[str, Any]) -> dict[str, Any]:
    if not data:
        raise ValueError("录音文件为空。")
    try:
        sound = sf.SoundFile(io.BytesIO(data))
    except Exception as exc:
        raise ValueError("录音文件无法读取，请上传有效 WAV。") from exc
    with sound:
        if sound.format not in {"WAV", "WAVEX", "RF64"}:
            raise ValueError("请上传有效 WAV，不能通过修改扩展名上传其他格式。")
        sample_rate = int(sound.samplerate)
        frames, channels = int(sound.frames), int(sound.channels)
        if not 0 < sample_rate <= MAX_SAMPLE_RATE or sample_rate != int(model["sample_rate"]):
            raise ValueError(f"模型需要 {model['sample_rate']} Hz 录音，采样率不匹配或无效。")
        if not 1 <= channels <= MAX_AUDIO_CHANNELS:
            raise ValueError(f"录音声道数须在 1 至 {MAX_AUDIO_CHANNELS} 之间。")
        if frames < int(sample_rate * MIN_DURATION_SECONDS):
            raise ValueError("录音时长过短，至少需要 0.25 秒。")
        if frames > int(sample_rate * MAX_DURATION_SECONDS):
            raise ValueError("录音时长超过 30 秒限制。")
        if (frames + 1) * channels * np.dtype(np.float32).itemsize > MAX_DECODED_BYTES:
            raise ValueError("录音解码大小超过内存限制。")
        try:
            audio = sound.read(frames=frames + 1, dtype="float32", always_2d=True)
        except Exception as exc:
            raise ValueError("录音内容无法解码，请上传完整 WAV。") from exc
        if audio.shape[0] != frames:
            raise ValueError("录音帧数与文件头不符，请上传完整 WAV。")
    values = validate_audio(audio, int(sample_rate))
    score = score_audio(model, values, int(sample_rate))
    return {
        "model_version": model["model_version"],
        "sample_rate": int(sample_rate),
        "duration_seconds": round(values.size / sample_rate, 4),
        "anomaly_score": round(score, 6),
        "threshold": round(float(model["threshold"]), 6),
        "verdict": verdict_for_score(score, float(model["threshold"])),
    }


def save_model(model: dict[str, Any], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")


def load_model(path: str | Path) -> dict[str, Any]:
    model = json.loads(Path(path).read_text(encoding="utf-8"))
    if model.get("model_version") != MODEL_VERSION:
        raise ValueError("模型版本不受支持。")
    return model


class LogMelGaussianDetector:
    """The existing CPU baseline exposed through the pluggable contract."""

    backend_name = "logmel_gaussian"

    def __init__(self, model_path: str | Path):
        self.model = load_model(model_path)
        self.model_version = str(self.model["model_version"])

    def analyze_wav_bytes(self, data: bytes) -> dict[str, Any]:
        return {
            "detector_backend": self.backend_name,
            **analyze_wav_bytes(data, self.model),
        }

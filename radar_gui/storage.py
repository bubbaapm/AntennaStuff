"""Persistence helpers for settings, backgrounds, and capture sessions."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import numpy as np

from .models import BackgroundProfile, CaptureSession, RadarConfig, SweepConfig


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = APP_DIR / "data"
BACKGROUND_DIR = DATA_DIR / "backgrounds"
CAPTURE_DIR = DATA_DIR / "captures"
CONFIG_PATH = APP_DIR / "radar_gui_config.json"


def ensure_data_dirs() -> None:
    BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("_")
    return slug or f"profile_{int(time.time())}"


def load_settings() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(settings: Dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def save_background(profile: BackgroundProfile) -> Path:
    ensure_data_dirs()
    path = BACKGROUND_DIR / f"{slugify(profile.name)}.npz"
    np.savez_compressed(
        path,
        s21=profile.complex_s21_avg,
        metadata=json.dumps(profile.metadata()),
    )
    return path


def load_background(path: Path) -> BackgroundProfile:
    data = np.load(path, allow_pickle=False)
    meta = json.loads(str(data["metadata"].item()))
    return BackgroundProfile(
        name=meta["name"],
        sweep_config=SweepConfig.from_dict(meta["sweep_config"]),
        complex_s21_avg=np.asarray(data["s21"], dtype=np.complex128),
        created_at=float(meta["created_at"]),
        notes=meta.get("notes", ""),
        device_id=meta.get("device_id", ""),
    )


def list_backgrounds() -> list[Path]:
    ensure_data_dirs()
    return sorted(BACKGROUND_DIR.glob("*.npz"))


def save_capture(session: CaptureSession) -> Path:
    ensure_data_dirs()
    path = CAPTURE_DIR / f"{slugify(session.name)}.npz"
    payload = {
        "timestamps": session.timestamps,
        "freq_hz": session.freq_hz,
        "s21_frames": session.s21_frames,
        "metadata": json.dumps(
            {
                "name": session.name,
                "sweep_config": session.sweep_config.to_dict(),
                "radar_config": session.radar_config.to_dict(),
                "background_name": session.background_name,
                "device_id": session.device_id,
                "has_s11": session.s11_frames is not None,
                "has_peak_history": session.peak_distance_m is not None and session.peak_amplitude is not None,
            }
        ),
    }
    if session.s11_frames is not None:
        payload["s11_frames"] = session.s11_frames
    if session.peak_distance_m is not None and session.peak_amplitude is not None:
        payload["peak_distance_m"] = session.peak_distance_m
        payload["peak_amplitude"] = session.peak_amplitude
    np.savez_compressed(path, **payload)
    return path


def load_capture(path: Path) -> CaptureSession:
    data = np.load(path, allow_pickle=False)
    meta = json.loads(str(data["metadata"].item()))
    s11 = np.asarray(data["s11_frames"], dtype=np.complex128) if meta.get("has_s11") else None
    peak_distance = np.asarray(data["peak_distance_m"], dtype=float) if meta.get("has_peak_history") else None
    peak_amplitude = np.asarray(data["peak_amplitude"], dtype=float) if meta.get("has_peak_history") else None
    return CaptureSession(
        name=meta["name"],
        sweep_config=SweepConfig.from_dict(meta["sweep_config"]),
        radar_config=RadarConfig.from_dict(meta["radar_config"]),
        timestamps=np.asarray(data["timestamps"], dtype=float),
        freq_hz=np.asarray(data["freq_hz"], dtype=float),
        s21_frames=np.asarray(data["s21_frames"], dtype=np.complex128),
        s11_frames=s11,
        peak_distance_m=peak_distance,
        peak_amplitude=peak_amplitude,
        background_name=meta.get("background_name", ""),
        device_id=meta.get("device_id", ""),
    )


def list_captures() -> list[Path]:
    ensure_data_dirs()
    return sorted(CAPTURE_DIR.glob("*.npz"))


def stack_frames(frames: Iterable[np.ndarray]) -> np.ndarray:
    return np.vstack([np.asarray(frame, dtype=np.complex128)[None, :] for frame in frames])

"""Typed shared models for the radar VNA GUI."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


SPEED_OF_LIGHT_M_S = 299_792_458.0


@dataclass(frozen=True)
class SweepConfig:
    start_hz: float = 5.0e9
    stop_hz: float = 5.4e9
    points: int = 501
    mode: str = "s21"
    power: str = "max"
    poll_delay_s: float = 0.02
    backend_options: Dict[str, Any] = field(default_factory=dict)

    @property
    def bandwidth_hz(self) -> float:
        return max(1.0, float(self.stop_hz) - float(self.start_hz))

    def frequency_axis(self) -> np.ndarray:
        return np.linspace(float(self.start_hz), float(self.stop_hz), int(self.points))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SweepConfig":
        clean = dict(data)
        clean["points"] = int(clean.get("points", cls.points))
        return cls(**clean)


@dataclass(frozen=True)
class Peak:
    distance_m: float
    amplitude: float
    index: int
    prominence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SweepFrame:
    freq_hz: np.ndarray
    s11: Optional[np.ndarray]
    s21: np.ndarray
    timestamp: float
    device_id: str = ""
    raw_meta: Dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "SweepFrame":
        return SweepFrame(
            freq_hz=np.array(self.freq_hz, copy=True),
            s11=None if self.s11 is None else np.array(self.s11, copy=True),
            s21=np.array(self.s21, copy=True),
            timestamp=float(self.timestamp),
            device_id=self.device_id,
            raw_meta=dict(self.raw_meta),
        )


@dataclass(frozen=True)
class RadarConfig:
    background_id: str = ""
    ema_alpha: float = 0.25
    window: str = "hann"
    tvg_enabled: bool = False
    tvg_exponent: float = 2.0
    range_min_m: float = 0.0
    range_max_m: float = 10.0
    peak_threshold: float = 0.0
    peak_prominence: float = 0.0
    max_peaks: int = 3
    range_fft_points: int = 2048

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RadarConfig":
        return cls(**dict(data))


@dataclass
class RadarFrame:
    distance_m: np.ndarray
    magnitude: np.ndarray
    peaks: List[Peak]
    waterfall_row: np.ndarray
    intermediates: Dict[str, np.ndarray] = field(default_factory=dict)


@dataclass
class BackgroundProfile:
    name: str
    sweep_config: SweepConfig
    complex_s21_avg: np.ndarray
    created_at: float
    notes: str = ""
    device_id: str = ""

    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "sweep_config": self.sweep_config.to_dict(),
            "created_at": self.created_at,
            "notes": self.notes,
            "device_id": self.device_id,
        }


@dataclass
class CaptureSession:
    name: str
    sweep_config: SweepConfig
    radar_config: RadarConfig
    timestamps: np.ndarray
    freq_hz: np.ndarray
    s21_frames: np.ndarray
    s11_frames: Optional[np.ndarray] = None
    peak_distance_m: Optional[np.ndarray] = None
    peak_amplitude: Optional[np.ndarray] = None
    background_name: str = ""
    device_id: str = ""

    def frame_count(self) -> int:
        return int(self.s21_frames.shape[0]) if self.s21_frames.ndim else 0

"""Pure NumPy/SciPy radar processing helpers."""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from scipy.fft import ifft
from scipy.signal import find_peaks

from .models import Peak, RadarConfig, RadarFrame, SPEED_OF_LIGHT_M_S, SweepConfig


def distance_axis(config: SweepConfig, bins: Optional[int] = None) -> np.ndarray:
    """Return two-way radar distance bins for a stepped-frequency sweep."""
    bins = int(bins or config.points)
    bandwidth = config.bandwidth_hz
    # Zero-padding the IFFT interpolates the displayed range profile. Keep the
    # same approximate unambiguous range as the unpadded sweep so A-scope bins
    # are a display/DSP setting, not extra VNA measurements.
    spacing = (SPEED_OF_LIGHT_M_S / (2.0 * bandwidth)) * (int(config.points) / bins)
    return np.arange(bins, dtype=float) * spacing


def make_window(name: str, points: int) -> np.ndarray:
    key = name.strip().lower()
    if key in {"hann", "hanning"}:
        return np.hanning(points)
    if key == "hamming":
        return np.hamming(points)
    if key in {"rect", "rectangular", "none"}:
        return np.ones(points)
    raise ValueError(f"Unsupported window: {name}")


def apply_complex_ema(
    current: np.ndarray,
    previous: Optional[np.ndarray],
    alpha: float,
) -> np.ndarray:
    alpha = float(np.clip(alpha, 0.0, 1.0))
    if previous is None or previous.shape != current.shape:
        return np.array(current, copy=True)
    return alpha * current + (1.0 - alpha) * previous


def normalize_for_waterfall(magnitude: np.ndarray) -> np.ndarray:
    mag = np.asarray(magnitude, dtype=float)
    if mag.size == 0:
        return mag
    floor = np.percentile(mag, 5)
    ceil = np.percentile(mag, 99)
    span = max(float(ceil - floor), 1e-15)
    return np.clip((mag - floor) / span, 0.0, 1.0)


def detect_peaks(
    distance_m: np.ndarray,
    magnitude: np.ndarray,
    config: RadarConfig,
) -> list[Peak]:
    if magnitude.size == 0:
        return []
    kwargs = {}
    if config.peak_threshold > 0:
        kwargs["height"] = config.peak_threshold
    if config.peak_prominence > 0:
        kwargs["prominence"] = config.peak_prominence
    indices, props = find_peaks(magnitude, **kwargs)
    if indices.size == 0:
        return []
    prominences = props.get("prominences", np.zeros_like(indices, dtype=float))
    order = np.argsort(magnitude[indices])[::-1][: max(1, int(config.max_peaks))]
    peaks = []
    for pos in order:
        idx = int(indices[pos])
        peaks.append(
            Peak(
                distance_m=float(distance_m[idx]),
                amplitude=float(magnitude[idx]),
                index=idx,
                prominence=float(prominences[pos]) if prominences.size else 0.0,
            )
        )
    return peaks


def process_s21(
    s21: np.ndarray,
    sweep_config: SweepConfig,
    radar_config: RadarConfig,
    background: Optional[np.ndarray] = None,
    previous_ema: Optional[np.ndarray] = None,
    include_intermediates: bool = False,
) -> Tuple[RadarFrame, np.ndarray]:
    """Process one complex S21 sweep into a range profile and return EMA state."""
    complex_s21 = np.asarray(s21, dtype=np.complex128)
    if complex_s21.size != int(sweep_config.points):
        raise ValueError(
            f"S21 length {complex_s21.size} does not match points {sweep_config.points}"
        )
    if background is None:
        subtracted = complex_s21
    else:
        bg = np.asarray(background, dtype=np.complex128)
        if bg.shape != complex_s21.shape:
            raise ValueError("Background shape does not match live sweep")
        subtracted = complex_s21 - bg

    ema = apply_complex_ema(subtracted, previous_ema, radar_config.ema_alpha)
    window = make_window(radar_config.window, complex_s21.size)
    windowed = ema * window
    fft_points = max(int(sweep_config.points), int(radar_config.range_fft_points))
    magnitude = np.abs(ifft(windowed, n=fft_points))
    distances = distance_axis(sweep_config, fft_points)

    if radar_config.tvg_enabled:
        gain = np.power(np.maximum(distances, 1e-6), float(radar_config.tvg_exponent))
        magnitude = magnitude * gain

    mask = (distances >= radar_config.range_min_m) & (distances <= radar_config.range_max_m)
    cropped_dist = distances[mask]
    cropped_mag = magnitude[mask]
    peaks = detect_peaks(cropped_dist, cropped_mag, radar_config)

    intermediates = {}
    if include_intermediates:
        intermediates = {
            "raw_s21": complex_s21,
            "subtracted": subtracted,
            "ema": ema,
            "windowed": windowed,
            "full_distance_m": distances,
            "full_magnitude": magnitude,
        }

    frame = RadarFrame(
        distance_m=cropped_dist,
        magnitude=cropped_mag,
        peaks=peaks,
        waterfall_row=normalize_for_waterfall(cropped_mag),
        intermediates=intermediates,
    )
    return frame, ema

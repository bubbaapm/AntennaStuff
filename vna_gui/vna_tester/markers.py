"""
Markers — small objects living on a (trace, frequency) tuple.

A marker subscribes to a trace and reports values at the closest sampled
frequency (or interpolated). Special markers compute their position from
the trace data: peak, min, target-value crossing, -10dB bandwidth.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

import numpy as np

from .trace import Trace


class MarkerKind(Enum):
    NORMAL = "normal"        # user-placed at a fixed frequency
    PEAK = "peak"            # tracks max |S|
    MIN = "min"              # tracks min |S|
    TARGET = "target"        # tracks crossing of target dB value (left)
    BW_M10DB = "bw_m10db"    # bandwidth box where dB(|S|) <= -10
    DELTA = "delta"          # difference vs another marker


# Human-friendly labels for the right-click menu / UI.
MARKER_KIND_LABELS = {
    MarkerKind.NORMAL:   "Normal (fixed freq)",
    MarkerKind.PEAK:     "Max (tracks maximum)",
    MarkerKind.MIN:      "Min (tracks minimum)",
    MarkerKind.TARGET:   "Target dB (first crossing)",
    MarkerKind.BW_M10DB: "Bandwidth box (target-dB band)",
    MarkerKind.DELTA:    "Delta (difference)",
}


MARKER_STYLES = ("line", "point", "both")


MARKER_SCOPES = ("all", "panel")


@dataclass
class Marker:
    label: str
    kind: MarkerKind
    trace_name: str
    freq_hz: float = 0.0
    target_db: float = -10.0
    visible: bool = True
    color: str = "#ffffff"
    style: str = "both"          # "line" | "point" | "both"
    scope: str = "all"           # "all" | "panel"
    panel_id: str = ""           # plot panel id this marker is restricted to (when scope="panel")
    # secondary anchor for delta/BW (left & right edges)
    secondary_freq_hz: float = 0.0
    # cached readout
    last_db: float = 0.0
    last_phase_deg: float = 0.0
    last_real: float = 0.0
    last_imag: float = 0.0
    last_vswr: float = 1.0
    last_z: complex = 0.0 + 0.0j

    def evaluate(self, trace: Trace, z0: float = 50.0) -> None:
        """Recompute marker position and cached readouts for given trace."""
        if trace.freq.size == 0:
            return
        if self.kind == MarkerKind.PEAK:
            idx = int(np.argmax(np.abs(trace.s)))
            self.freq_hz = float(trace.freq[idx])
        elif self.kind == MarkerKind.MIN:
            idx = int(np.argmin(np.abs(trace.s)))
            self.freq_hz = float(trace.freq[idx])
        elif self.kind == MarkerKind.TARGET:
            db = trace.magnitude_db()
            below = np.where(db <= self.target_db)[0]
            if below.size > 0:
                self.freq_hz = float(trace.freq[below[0]])
            else:
                idx = int(np.argmin(db))
                self.freq_hz = float(trace.freq[idx])
        elif self.kind == MarkerKind.BW_M10DB:
            # Walk left and right from the *minimum* — gives the contiguous
            # band around the operating resonance, not the convex hull of
            # every dip in the sweep (which is meaningless for antennas).
            db = trace.magnitude_db()
            below = db <= self.target_db
            if below.any():
                idx_min = int(np.argmin(db))
                left = idx_min
                while left > 0 and below[left - 1]:
                    left -= 1
                right = idx_min
                while right < below.size - 1 and below[right + 1]:
                    right += 1
                self.freq_hz = float(trace.freq[left])
                self.secondary_freq_hz = float(trace.freq[right])
            else:
                self.freq_hz = float(trace.freq[0])
                self.secondary_freq_hz = float(trace.freq[0])

        # Snap to closest sample for readouts (avoid interpolation surprises).
        idx = int(np.argmin(np.abs(trace.freq - self.freq_hz)))
        s = trace.s[idx]
        self.last_real = float(np.real(s))
        self.last_imag = float(np.imag(s))
        mag = max(abs(s), 1e-12)
        self.last_db = 20.0 * np.log10(mag)
        self.last_phase_deg = float(np.rad2deg(np.angle(s)))
        m = min(mag, 0.999_999)
        self.last_vswr = (1.0 + m) / (1.0 - m)
        if abs(1.0 - s) > 1e-9:
            self.last_z = z0 * (1.0 + s) / (1.0 - s)
        else:
            self.last_z = complex(float("inf"), 0.0)

    def bandwidth_hz(self) -> float:
        if self.kind == MarkerKind.BW_M10DB:
            return max(0.0, self.secondary_freq_hz - self.freq_hz)
        return 0.0

    def center_hz(self) -> float:
        if self.kind == MarkerKind.BW_M10DB:
            return 0.5 * (self.freq_hz + self.secondary_freq_hz)
        return self.freq_hz

"""
Trace data model.

A Trace is one S-parameter (S11, S12, S21, S22) sampled at N frequency
points. It carries complex values (linear, not dB).

A TraceAssignment is "this trace, drawn this way, on this plot's left or
right Y-axis". Plot panels own a list of assignments — that's how dual
Y-axes, per-trace formats, and per-plot color/style overrides work.

The TraceManager holds the global registry of traces + reference traces
(loaded .s2p files) and emits Qt signals when traces update.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


VNA_PARAMS = ("S11", "S12", "S21", "S22")
DEFAULT_TRACE_COLORS = {
    "S11": "#00e0b4",
    "S22": "#ffd34d",
    "S21": "#73c4ff",
    "S12": "#ff6b9d",
}

# Cycled when references are added so each loaded .s1p/.s2p gets its own
# color out of the box — desaturated relative to the live-trace palette so
# the live sweep still pops against a stack of references.
REFERENCE_COLORS = (
    "#a0a0a0",  # gray (legacy default)
    "#c5e1a5",  # light green
    "#90caf9",  # light blue
    "#ffcc80",  # light orange
    "#ce93d8",  # light purple
    "#ef9a9a",  # light red
    "#80deea",  # light cyan
    "#fff59d",  # light yellow
    "#bcaaa4",  # warm taupe
    "#b0bec5",  # cool gray-blue
)

LINE_STYLES = ("solid", "dash", "dot", "dashdot")


@dataclass
class TraceAssignment:
    """
    Per-plot trace configuration. Owns visual overrides; if `color_override`
    is empty the panel uses the global Trace.color. `axis` and `y_format`
    only apply to cartesian plots and are ignored elsewhere.
    """
    trace_name: str
    visible: bool = True
    axis: str = "left"               # "left" | "right" (cartesian only)
    y_format: str = "dB"             # cartesian only — see CARTESIAN_FORMATS
    color_override: str = ""         # "" → inherit from trace
    line_style: str = "solid"        # solid | dash | dot | dashdot
    line_width: float = 2.0
    show_dots: bool = False          # scatter points along the trace

    def color_for(self, trace: "Trace") -> str:
        return self.color_override if self.color_override else trace.color

    def to_dict(self) -> Dict:
        return {
            "trace_name": self.trace_name, "visible": self.visible,
            "axis": self.axis, "y_format": self.y_format,
            "color_override": self.color_override,
            "line_style": self.line_style, "line_width": self.line_width,
            "show_dots": self.show_dots,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "TraceAssignment":
        return cls(
            trace_name=d.get("trace_name", "S11"),
            visible=bool(d.get("visible", True)),
            axis=d.get("axis", "left"),
            y_format=d.get("y_format", "dB"),
            color_override=d.get("color_override", ""),
            line_style=d.get("line_style", "solid"),
            line_width=float(d.get("line_width", 2.0)),
            show_dots=bool(d.get("show_dots", False)),
        )


@dataclass
class Trace:
    name: str
    parameter: str           # S11/S12/S21/S22
    freq: np.ndarray         # Hz
    s: np.ndarray            # complex linear
    visible: bool = True
    color: str = "#00e0b4"
    is_reference: bool = False  # loaded from disk
    source_file: str = ""

    @property
    def n_points(self) -> int:
        return int(self.freq.size)

    def magnitude_db(self) -> np.ndarray:
        m = np.maximum(np.abs(self.s), 1e-12)
        return 20.0 * np.log10(m)

    def magnitude_linear(self) -> np.ndarray:
        return np.abs(self.s)

    def phase_deg(self, unwrap: bool = False) -> np.ndarray:
        ph = np.angle(self.s)
        if unwrap:
            ph = np.unwrap(ph)
        return np.rad2deg(ph)

    def vswr(self) -> np.ndarray:
        m = np.clip(np.abs(self.s), 0.0, 0.999_999)
        return (1.0 + m) / (1.0 - m)

    def real(self) -> np.ndarray:
        return np.real(self.s)

    def imag(self) -> np.ndarray:
        return np.imag(self.s)

    def impedance(self, z0: float = 50.0) -> np.ndarray:
        """Convert reflection coefficient to impedance (only meaningful for S11/S22)."""
        s = np.clip(self.s, -0.999_999 + 0j, None)  # avoid /0 at unit circle
        return z0 * (1.0 + s) / (1.0 - s)

    def group_delay(self) -> np.ndarray:
        """Group delay in seconds. Approximated by -dphase/dω."""
        if self.freq.size < 2:
            return np.zeros_like(self.freq)
        ph = np.unwrap(np.angle(self.s))
        omega = 2.0 * np.pi * self.freq
        gd = -np.gradient(ph, omega)
        return gd


class TraceManager(QObject):
    """
    Holds named live traces and reference traces. Emits when sets change.

    Live trace names are simply the S-parameter (e.g. "S11"). Reference
    trace names are user-supplied (e.g. "Ref_PatchAntenna_S11").
    """

    traces_changed = pyqtSignal()         # set/visibility/color changed
    traces_data = pyqtSignal()            # data values updated (one or many)

    def __init__(self) -> None:
        super().__init__()
        self._traces: Dict[str, Trace] = {}

    # ------------------------------------------------------------- access
    def names(self) -> List[str]:
        return list(self._traces.keys())

    def get(self, name: str) -> Optional[Trace]:
        return self._traces.get(name)

    def all(self) -> List[Trace]:
        return list(self._traces.values())

    def live(self) -> List[Trace]:
        return [t for t in self._traces.values() if not t.is_reference]

    def references(self) -> List[Trace]:
        return [t for t in self._traces.values() if t.is_reference]

    # ------------------------------------------------------------- mutate
    def set_live(self, parameter: str, freq: np.ndarray, s: np.ndarray) -> Trace:
        """Create or refresh the live trace for an S-parameter."""
        return self.bulk_update({parameter: (freq, s)})[parameter]

    def bulk_update(self, updates: Dict[str, "tuple[np.ndarray, np.ndarray]"]
                    ) -> Dict[str, Trace]:
        """
        Atomically update many traces. Emits at most one traces_changed
        (if the set of trace names grew) and one traces_data (always).
        Worker uses this to avoid signal-cascade lag.
        """
        new_set = False
        out: Dict[str, Trace] = {}
        for parameter, (freq, s) in updates.items():
            existing = self._traces.get(parameter)
            if existing is not None and not existing.is_reference:
                existing.freq = freq
                existing.s = s
                out[parameter] = existing
            else:
                t = Trace(
                    name=parameter, parameter=parameter,
                    freq=freq, s=s,
                    color=DEFAULT_TRACE_COLORS.get(parameter, "#00e0b4"),
                    is_reference=False,
                )
                self._traces[parameter] = t
                out[parameter] = t
                new_set = True
        if new_set:
            self.traces_changed.emit()
        self.traces_data.emit()
        return out

    def add_reference(self, name: str, parameter: str,
                      freq: np.ndarray, s: np.ndarray,
                      source_file: str = "") -> Trace:
        if name in self._traces:
            name = self._unique_name(name)
        # Cycle through the reference palette by reference-count so loading
        # a folder of .s1p files doesn't yield ten identical gray traces.
        idx = len(self.references())
        color = REFERENCE_COLORS[idx % len(REFERENCE_COLORS)]
        t = Trace(
            name=name, parameter=parameter, freq=freq, s=s,
            color=color, is_reference=True, source_file=source_file,
        )
        self._traces[name] = t
        self.traces_changed.emit()
        return t

    def remove(self, name: str) -> None:
        if name in self._traces:
            del self._traces[name]
            self.traces_changed.emit()

    def set_visible(self, name: str, visible: bool) -> None:
        t = self._traces.get(name)
        if t is not None and t.visible != visible:
            t.visible = visible
            self.traces_changed.emit()

    def set_color(self, name: str, color: str) -> None:
        t = self._traces.get(name)
        if t is not None:
            t.color = color
            self.traces_changed.emit()

    def clear_references(self) -> None:
        self._traces = {n: t for n, t in self._traces.items() if not t.is_reference}
        self.traces_changed.emit()

    def _unique_name(self, base: str) -> str:
        if base not in self._traces:
            return base
        i = 2
        while f"{base}_{i}" in self._traces:
            i += 1
        return f"{base}_{i}"

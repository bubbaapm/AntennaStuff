"""
Time-domain reflectometry / transmission plot.

Frequency-domain S → time-domain via windowed inverse FFT (host-side).
Per-trace styling via assignments; window/Vp/x-axis are plot-wide settings.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..trace import Trace, TraceAssignment
from .base import (
    PlotPanel, default_assignments, make_header_buttons, register_plot,
    style_to_qt_pen,
)


C0 = 2.997_924_58e8


WINDOWS = {
    "Rectangular": np.ones,
    "Hann": np.hanning,
    "Hamming": np.hamming,
    "Blackman": np.blackman,
    "Kaiser β=6": lambda n: np.kaiser(n, 6.0),
    "Kaiser β=10": lambda n: np.kaiser(n, 10.0),
}


def freq_to_time_response(freq_hz: np.ndarray, s: np.ndarray,
                          window: str = "Hann", oversample: int = 4):
    if freq_hz.size < 4:
        return np.array([]), np.array([]), np.array([])
    order = np.argsort(freq_hz)
    f = freq_hz[order]
    sv = s[order]
    n = f.size
    df = float(np.median(np.diff(f)))
    win = WINDOWS.get(window, np.hanning)(n)
    sv_w = sv * win
    nfft = max(int(2 ** np.ceil(np.log2(n * oversample))), 64)
    spec = np.zeros(nfft, dtype=complex)
    spec[:n] = sv_w
    h = np.fft.ifft(spec)
    t = np.arange(nfft) / (nfft * df)
    mag = np.abs(h)
    half = nfft // 2
    t = t[:half]; mag = mag[:half]
    distance = (t * C0) / 2.0
    return t, mag, distance


class TDRPlot(PlotPanel):
    KIND = "tdr"
    TITLE = "Time domain"
    DEFAULT_PARAMS = ("S11",)

    def __init__(self, traces, parent=None,
                 params=None,
                 assignments: Optional[List[TraceAssignment]] = None):
        super().__init__(traces, parent)
        if assignments is None:
            assignments = default_assignments("tdr",
                                              params=params or list(self.DEFAULT_PARAMS))
        self._assignments = list(assignments)
        self._x_axis = "time"
        self._window = "Hann"
        self._vp_factor = 1.0
        self._curves: Dict[str, pg.PlotDataItem] = {}
        self._build_ui()
        self.draw()

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)

        # Header
        head = QHBoxLayout()
        self.lbl_title = QLabel(self.title)
        self.lbl_title.setStyleSheet("color:#00e0b4; font-weight:bold;")
        head.addWidget(self.lbl_title)
        head.addStretch(1)
        (self.btn_config, self.btn_reset, self.btn_left,
         self.btn_right, self.btn_remove) = make_header_buttons(self)
        for b in (self.btn_config, self.btn_reset, self.btn_left,
                  self.btn_right, self.btn_remove):
            head.addWidget(b)
        v.addLayout(head)

        # Controls row
        bar = QHBoxLayout()
        bar.addWidget(QLabel("X:"))
        self.cb_axis = QComboBox()
        self.cb_axis.addItems(["Time (ns)", "Distance (m)"])
        self.cb_axis.setToolTip(
            "Switch between time-of-flight and round-trip distance.\n"
            "Distance assumes propagation in air; tweak Vp for cable/board."
        )
        self.cb_axis.currentIndexChanged.connect(self._on_axis_changed)
        bar.addWidget(self.cb_axis)
        bar.addWidget(QLabel("Window:"))
        self.cb_win = QComboBox()
        self.cb_win.addItems(list(WINDOWS.keys()))
        self.cb_win.setCurrentText("Hann")
        self.cb_win.currentTextChanged.connect(lambda v: self._set_window(v))
        bar.addWidget(self.cb_win)
        bar.addWidget(QLabel("Vp:"))
        self.sp_vp = QDoubleSpinBox()
        self.sp_vp.setRange(0.10, 1.00); self.sp_vp.setSingleStep(0.01); self.sp_vp.setValue(1.0)
        self.sp_vp.setToolTip("Velocity factor — 1.0 = free space (c).")
        self.sp_vp.valueChanged.connect(lambda v: self._set_vp(v))
        bar.addWidget(self.sp_vp)
        bar.addStretch(1)
        v.addLayout(bar)

        self.pw = pg.PlotWidget()
        self.pw.setBackground("#1d1d1d")
        self.pw.showGrid(x=True, y=True, alpha=0.25)
        self.pw.setLabel("left", "Magnitude")
        self.pw.setLabel("bottom", "Time", units="s")
        self.pw.addLegend(offset=(-10, 10),
                          labelTextColor="#e0e0e0",
                          brush=QColor(20, 20, 20, 220))
        self.pw.setToolTip(
            "Time-domain reflectometry: peaks indicate impedance discontinuities.\n"
            "Useful for finding cable length, antenna feed reflections, solder defects."
        )
        v.addWidget(self.pw, 1)

    def _on_axis_changed(self, _) -> None:
        self._x_axis = "time" if self.cb_axis.currentIndex() == 0 else "distance"
        if self._x_axis == "time":
            self.pw.setLabel("bottom", "Time", units="s")
        else:
            self.pw.setLabel("bottom", "Distance", units="m")
        self.draw()

    def _set_window(self, w: str) -> None:
        self._window = w
        self.draw()

    def _set_vp(self, v: float) -> None:
        self._vp_factor = float(v)
        self.draw()

    def draw(self) -> None:
        self.lbl_title.setText(self.header_title)

        visible: Dict[str, tuple[Trace, TraceAssignment]] = {}
        for a in self._assignments:
            if not a.visible:
                continue
            t = self.traces.get(a.trace_name)
            if t is None or t.freq.size < 8 or not t.visible:
                continue
            visible[a.trace_name] = (t, a)

        for name in list(self._curves.keys()):
            if name not in visible:
                self.pw.removeItem(self._curves[name])
                del self._curves[name]

        for name, (t, a) in visible.items():
            tt, mag, dist = freq_to_time_response(t.freq, t.s, window=self._window)
            x = tt if self._x_axis == "time" else dist * self._vp_factor
            color = QColor(a.color_for(t))
            pen = pg.mkPen(color, width=a.line_width, style=style_to_qt_pen(a.line_style))
            curve = self._curves.get(name)
            if curve is None:
                curve = pg.PlotDataItem(x, mag, pen=pen, name=name)
                self.pw.addItem(curve)
                self._curves[name] = curve
            else:
                curve.setData(x, mag)
                curve.setPen(pen)

    def export_image(self, path: str, width_px: int, height_px: int,
                     fmt: str = "png") -> bool:
        try:
            from pyqtgraph.exporters import ImageExporter, SVGExporter
        except Exception:
            return False
        item = self.pw.plotItem
        if fmt.lower() == "svg":
            exp = SVGExporter(item)
        else:
            exp = ImageExporter(item)
            exp.parameters()["width"] = int(width_px)
            try:
                exp.parameters()["height"] = int(height_px)
            except Exception:
                pass
        try:
            exp.export(path)
            return True
        except Exception:
            return False

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update(window=self._window, x_axis=self._x_axis, vp=self._vp_factor)
        return d

    def from_dict(self, d: Dict[str, Any]) -> None:
        super().from_dict(d)
        if "window" in d:
            self.cb_win.setCurrentText(d["window"])
        if "x_axis" in d:
            self.cb_axis.setCurrentIndex(0 if d["x_axis"] == "time" else 1)
        if "vp" in d:
            self.sp_vp.setValue(float(d["vp"]))


register_plot("tdr")

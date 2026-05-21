"""
Polar plot — magnitude vs phase. Uses matplotlib's polar projection.

Same persistent-artist + assignment-list pattern as the Smith plot.
Per-trace color, line style, line width, and dots are honored.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavTB
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..trace import Trace, TraceAssignment
from .base import (
    PlotPanel, default_assignments, make_header_buttons, register_plot,
    style_to_mpl,
)


class PolarPlot(PlotPanel):
    KIND = "polar"
    TITLE = "Polar"
    DEFAULT_PARAMS = ("S11",)

    def __init__(self, traces, parent=None,
                 params=None,
                 assignments: Optional[List[TraceAssignment]] = None):
        super().__init__(traces, parent)
        if assignments is None:
            assignments = default_assignments("polar",
                                              params=params or list(self.DEFAULT_PARAMS))
        self._assignments = list(assignments)
        self._trace_lines: Dict[str, Any] = {}
        self._marker_artists: Dict[str, list] = {}
        self._legend = None
        self._legend_sig = None
        self._build_ui()
        self._init_axes()
        self.draw()

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)

        bar = QHBoxLayout()
        self.lbl_title = QLabel(self.title)
        self.lbl_title.setStyleSheet("color:#00e0b4; font-weight:bold;")
        bar.addWidget(self.lbl_title)
        bar.addStretch(1)
        (self.btn_config, self.btn_reset, self.btn_left,
         self.btn_right, self.btn_remove) = make_header_buttons(self)
        for b in (self.btn_config, self.btn_reset, self.btn_left,
                  self.btn_right, self.btn_remove):
            bar.addWidget(b)
        v.addLayout(bar)

        self.fig = Figure(figsize=(5, 5), facecolor="#1d1d1d")
        self.fig.set_layout_engine("none")
        self.canvas = FigureCanvas(self.fig)
        v.addWidget(self.canvas, 1)

        self.toolbar = NavTB(self.canvas, self)
        self.toolbar.setStyleSheet("background:#242424; color:#e0e0e0;")
        v.addWidget(self.toolbar)

    def _init_axes(self) -> None:
        self.fig.clf()
        self.ax = self.fig.add_subplot(111, projection="polar")
        self.ax.set_facecolor("#1d1d1d")
        self.ax.tick_params(colors="#888")
        self.ax.grid(True, alpha=0.3, color="#3a3a3a")
        self.fig.subplots_adjust(left=0.05, right=0.85, top=0.95, bottom=0.05)

    def draw(self) -> None:
        self.lbl_title.setText(self.header_title)

        visible: Dict[str, tuple[Trace, TraceAssignment]] = {}
        max_mag = 1.0
        for a in self._assignments:
            if not a.visible:
                continue
            t = self.traces.get(a.trace_name)
            if t is None or t.freq.size == 0 or not t.visible:
                continue
            visible[a.trace_name] = (t, a)
            mm = float(np.max(np.abs(t.s))) if t.s.size else 0.0
            if mm > max_mag:
                max_mag = mm

        for name in list(self._trace_lines.keys()):
            if name not in visible:
                self._trace_lines[name].remove()
                del self._trace_lines[name]

        for name, (t, a) in visible.items():
            mag = np.abs(t.s); ph = np.angle(t.s)
            color = a.color_for(t)
            ls = style_to_mpl(a.line_style)
            line = self._trace_lines.get(name)
            if line is None:
                line, = self.ax.plot(ph, mag, color=color, lw=a.line_width,
                                     ls=ls, label=name,
                                     marker="o" if a.show_dots else None,
                                     markersize=3)
                self._trace_lines[name] = line
            else:
                line.set_data(ph, mag)
                line.set_color(color)
                line.set_linestyle(ls)
                line.set_linewidth(a.line_width)
                line.set_marker("o" if a.show_dots else "None")

        # markers
        seen = set()
        for m in self.markers_for_panel():
            tr = self.traces.get(m.trace_name)
            if tr is None or tr.freq.size == 0:
                continue
            seen.add(m.label)
            idx = int(np.argmin(np.abs(tr.freq - m.freq_hz)))
            ph_at = float(np.angle(tr.s[idx]))
            mag_at = float(np.abs(tr.s[idx]))
            arts = self._marker_artists.get(m.label)
            if arts is None:
                pt, = self.ax.plot([ph_at], [mag_at], "o",
                                    color=m.color, markersize=7)
                self._marker_artists[m.label] = [pt]
            else:
                pt = arts[0]
                pt.set_data([ph_at], [mag_at])
                pt.set_color(m.color)
        for label in list(self._marker_artists.keys()):
            if label not in seen:
                for a in self._marker_artists[label]:
                    a.remove()
                del self._marker_artists[label]

        self.ax.set_rmax(max(1.05, max_mag * 1.05))
        self._refresh_legend(visible)
        self.canvas.draw_idle()

    def _refresh_legend(self, visible: Dict[str, tuple]) -> None:
        items = []
        for name, (t, a) in sorted(visible.items()):
            items.append(f"{name}|{a.color_for(t)}|{a.line_style}|{a.line_width}")
        sig = ";".join(items)
        if self._legend_sig == sig:
            return
        self._legend_sig = sig
        if self._legend is not None:
            self._legend.remove()
            self._legend = None
        if visible:
            self._legend = self.ax.legend(
                loc="upper right", fontsize=8, facecolor="#1f1f1f",
                edgecolor="#3a3a3a", labelcolor="#e0e0e0",
                bbox_to_anchor=(1.25, 1.10),
            )

    def export_image(self, path: str, width_px: int, height_px: int,
                     fmt: str = "png") -> bool:
        target_dpi = 200
        w_in = max(1.0, width_px / target_dpi)
        h_in = max(1.0, height_px / target_dpi)
        # Save & restore on-screen figure size — without this, exporting
        # at a non-square resolution permanently shrinks the live plot.
        prev_size = tuple(self.fig.get_size_inches())
        self.fig.set_size_inches(w_in, h_in)
        try:
            self.fig.savefig(path, dpi=target_dpi, facecolor="#1d1d1d",
                             format=fmt.lower() if fmt else None)
            return True
        except Exception:
            return False
        finally:
            self.fig.set_size_inches(*prev_size)
            try:
                w = self.canvas.width()
                h = self.canvas.height()
                self.canvas.resize(w + 1, h)
                self.canvas.resize(w, h)
            except Exception:
                pass
            self.canvas.draw_idle()


register_plot("polar")

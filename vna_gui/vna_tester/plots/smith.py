"""
Smith chart panel using matplotlib.

Any trace can be plotted on a Smith chart — the math is just "complex
value on the unit disc." S11/S22 are the obvious ones (reflection
coefficient → impedance), but plotting S21/S12 or a reference trace is
allowed for visualization purposes; the user is in charge of what's
meaningful.

Performance: the constant-R/X grid is built ONCE; on redraw we update
trace lines and marker dots in place via set_data — no fig.clf(),
no tight_layout, no full re-render.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavTB
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..markers import Marker
from ..trace import Trace, TraceAssignment
from .base import (
    PlotPanel, default_assignments, make_header_buttons, register_plot,
    style_to_mpl,
)


GRID_R = (0.0, 0.2, 0.5, 1.0, 2.0, 5.0)
GRID_X = (0.2, 0.5, 1.0, 2.0, 5.0)


def _draw_smith_grid(ax) -> None:
    ax.set_facecolor("#1d1d1d")
    ax.add_patch(Circle((0, 0), 1.0, fill=False, ec="#888", lw=1.2, zorder=1))
    for R in GRID_R:
        if R == 0.0:
            continue
        c = R / (R + 1.0)
        r = 1.0 / (R + 1.0)
        ax.add_patch(Circle((c, 0), r, fill=False, ec="#3a3a3a", lw=0.6, zorder=1))
    ax.plot([-1.0, 1.0], [0.0, 0.0], color="#3a3a3a", lw=0.6, zorder=1)
    for X in GRID_X:
        c = (1.0, 1.0 / X)
        r = 1.0 / X
        ax.add_patch(Circle(c, r, fill=False, ec="#3a3a3a", lw=0.6, zorder=1))
        ax.add_patch(Circle((1.0, -1.0 / X), r, fill=False, ec="#3a3a3a", lw=0.6, zorder=1))
    ax.add_patch(Circle((0, 0), 2.0, fill=False, lw=18, ec="#1d1d1d", zorder=2))
    ax.set_xlim(-1.05, 1.05)
    ax.set_ylim(-1.05, 1.05)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)


class SmithPlot(PlotPanel):
    KIND = "smith"
    TITLE = "Smith Chart"
    DEFAULT_PARAMS = ("S11", "S22")

    def __init__(self, traces, parent=None,
                 params=None,
                 assignments: Optional[List[TraceAssignment]] = None):
        super().__init__(traces, parent)
        if assignments is None:
            assignments = default_assignments("smith",
                                              params=params or list(self.DEFAULT_PARAMS))
        self._assignments = list(assignments)
        self._trace_lines: Dict[str, Any] = {}
        self._marker_artists: Dict[str, list] = {}
        self._legend = None
        self._legend_sig = None
        self._build_ui()
        self._init_grid()
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
        self.canvas.setToolTip(
            "Reflection coefficient (Γ) on a Smith chart.\n"
            "Inner circles = constant resistance; arcs = constant reactance.\n"
            "Center = matched (Z = Z₀); rim = total reflection (|Γ| = 1)."
        )
        v.addWidget(self.canvas, 1)

        self.toolbar = NavTB(self.canvas, self)
        self.toolbar.setStyleSheet("background:#242424; color:#e0e0e0;")
        v.addWidget(self.toolbar)

    def _init_grid(self) -> None:
        self.fig.clf()
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.02)
        _draw_smith_grid(self.ax)

    # ------------------------------------------------------------ drawing
    def draw(self) -> None:
        self.lbl_title.setText(self.header_title)

        # Active traces — anything in self._assignments that resolves.
        visible: Dict[str, tuple[Trace, TraceAssignment]] = {}
        for a in self._assignments:
            if not a.visible:
                continue
            t = self.traces.get(a.trace_name)
            if t is None or t.freq.size == 0 or not t.visible:
                continue
            visible[a.trace_name] = (t, a)

        # Drop gone
        for name in list(self._trace_lines.keys()):
            if name not in visible:
                self._trace_lines[name].remove()
                del self._trace_lines[name]
        # Update / create
        for name, (t, a) in visible.items():
            xs = np.real(t.s); ys = np.imag(t.s)
            color = a.color_for(t)
            ls = style_to_mpl(a.line_style)
            line = self._trace_lines.get(name)
            if line is None:
                line, = self.ax.plot(xs, ys, color=color, lw=a.line_width,
                                     ls=ls, label=name, zorder=3,
                                     marker="o" if a.show_dots else None,
                                     markersize=3)
                self._trace_lines[name] = line
            else:
                line.set_data(xs, ys)
                line.set_color(color)
                line.set_linestyle(ls)
                line.set_linewidth(a.line_width)
                line.set_marker("o" if a.show_dots else "None")

        # Markers — scoped to this panel
        seen = set()
        for m in self.markers_for_panel():
            tr = self.traces.get(m.trace_name)
            if tr is None or tr.freq.size == 0:
                continue
            seen.add(m.label)
            idx = int(np.argmin(np.abs(tr.freq - m.freq_hz)))
            mx, my = float(np.real(tr.s[idx])), float(np.imag(tr.s[idx]))
            artists = self._marker_artists.get(m.label)
            if artists is None:
                pt, = self.ax.plot([mx], [my], "o", color=m.color,
                                   markersize=8, zorder=4)
                txt = self.ax.annotate(m.label, xy=(mx, my),
                                        xytext=(6, 6), textcoords="offset points",
                                        color="#e0e0e0", fontsize=8, zorder=5)
                self._marker_artists[m.label] = [pt, txt]
            else:
                pt, txt = artists
                pt.set_data([mx], [my])
                pt.set_color(m.color)
                txt.set_position((mx, my))
                txt.set_text(m.label)
        for label in list(self._marker_artists.keys()):
            if label not in seen:
                for a in self._marker_artists[label]:
                    a.remove()
                del self._marker_artists[label]

        self._refresh_legend(visible)
        self.canvas.draw_idle()

    def _refresh_legend(self, visible: Dict[str, tuple]) -> None:
        # Signature must include color + style so edits show up immediately.
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
            )

    def export_image(self, path: str, width_px: int, height_px: int,
                     fmt: str = "png") -> bool:
        target_dpi = 200
        w_in = max(1.0, width_px / target_dpi)
        h_in = max(1.0, height_px / target_dpi)
        self.fig.set_size_inches(w_in, h_in)
        try:
            self.fig.savefig(path, dpi=target_dpi, facecolor="#1d1d1d",
                             format=fmt.lower() if fmt else None)
            return True
        except Exception:
            return False
        finally:
            self.canvas.draw_idle()


register_plot("smith")

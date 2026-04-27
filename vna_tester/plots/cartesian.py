"""
Cartesian (XY) plot using pyqtgraph.

Supports:
  • Per-trace assignment to LEFT or RIGHT Y-axis (dual-axis plotting).
  • Per-trace Y format (dB, VSWR, phase, group delay, real/imag, R/X of Z).
  • Per-trace color override, line style, line width, optional dots.
  • Manual or auto X / Y-left / Y-right ranges.
  • Click-to-place marker that picks the trace nearest the click point.
  • Right-click on a marker line → context menu (scope/color/kind/remove).
  • Header row with ⚙ Configure, ◀ ▶ move, ✕ remove.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget,
)

from ..markers import Marker, MarkerKind
from ..trace import Trace, TraceAssignment
from .base import PlotPanel, default_assignments, register_plot, style_to_qt_pen

pg.setConfigOptions(antialias=True, useOpenGL=False)


CARTESIAN_FORMATS = (
    "dB",
    "Linear |S|",
    "VSWR",
    "Phase (°)",
    "Phase unwrapped (°)",
    "Group delay (ns)",
    "Real",
    "Imag",
    "Re(Z) Ω",
    "Im(Z) Ω",
    "|Z| Ω",
    "Mismatch loss (dB)",
)


def _y_for(trace: Trace, fmt: str, z0: float = 50.0) -> np.ndarray:
    if fmt == "dB":
        return trace.magnitude_db()
    if fmt == "Linear |S|":
        return trace.magnitude_linear()
    if fmt == "VSWR":
        return np.minimum(trace.vswr(), 50.0)
    if fmt == "Phase (°)":
        return trace.phase_deg(unwrap=False)
    if fmt == "Phase unwrapped (°)":
        return trace.phase_deg(unwrap=True)
    if fmt == "Group delay (ns)":
        return trace.group_delay() * 1e9
    if fmt == "Real":
        return trace.real()
    if fmt == "Imag":
        return trace.imag()
    if fmt == "Re(Z) Ω":
        return np.real(trace.impedance(z0))
    if fmt == "Im(Z) Ω":
        return np.imag(trace.impedance(z0))
    if fmt == "|Z| Ω":
        return np.abs(trace.impedance(z0))
    if fmt == "Mismatch loss (dB)":
        m2 = np.clip(np.abs(trace.s) ** 2, 0.0, 0.999_999)
        return -10.0 * np.log10(np.maximum(1e-12, 1.0 - m2))
    return trace.magnitude_db()


class CartesianPlot(PlotPanel):
    KIND = "cartesian"
    TITLE = "Cartesian"
    SUPPORTS_DUAL_Y = True
    SUPPORTS_FORMATS = True

    marker_dragged = pyqtSignal(str, float)
    marker_context = pyqtSignal(str, object)   # label, screenPos QPoint

    def __init__(self, traces, parent=None,
                 y_format: str = "dB", params=None,
                 assignments: Optional[List[TraceAssignment]] = None):
        super().__init__(traces, parent)
        if assignments is None:
            assignments = default_assignments("cartesian",
                                              params=params or ["S11", "S22"])
            for a in assignments:
                a.y_format = y_format
        self._assignments = list(assignments)
        self._build_ui()
        self.draw()

    # ----------------------------------------------------------- build UI
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        self.lbl_title = QLabel(self.title)
        self.lbl_title.setStyleSheet("color:#00e0b4; font-weight:bold;")
        bar.addWidget(self.lbl_title)
        bar.addStretch(1)

        self.btn_config = QPushButton("⚙")
        self.btn_config.setFixedWidth(28)
        self.btn_config.setToolTip("Configure traces, axes, colors, line styles…")
        self.btn_config.clicked.connect(lambda: self.request_configure.emit(self))
        bar.addWidget(self.btn_config)

        self.btn_left = QPushButton("◀")
        self.btn_left.setFixedWidth(28)
        self.btn_left.setToolTip("Move plot one position left")
        self.btn_left.clicked.connect(lambda: self.request_move.emit(self, -1))
        bar.addWidget(self.btn_left)

        self.btn_right = QPushButton("▶")
        self.btn_right.setFixedWidth(28)
        self.btn_right.setToolTip("Move plot one position right")
        self.btn_right.clicked.connect(lambda: self.request_move.emit(self, +1))
        bar.addWidget(self.btn_right)

        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedWidth(28)
        self.btn_remove.setToolTip("Remove this plot panel")
        self.btn_remove.clicked.connect(lambda: self.request_remove.emit(self))
        bar.addWidget(self.btn_remove)
        v.addLayout(bar)

        self.pw = pg.PlotWidget()
        self.pw.setBackground("#1d1d1d")
        self.pi = self.pw.getPlotItem()
        self.pi.showGrid(x=True, y=True, alpha=0.25)
        self.pi.setLabel("bottom", "Frequency", units="Hz")
        self.pi.setLabel("left", "")
        self.pi.showAxis("right")
        self.pi.setLabel("right", "")

        # Right Y-axis: a second ViewBox sharing the X axis.
        self.right_vb = pg.ViewBox()
        self.pi.scene().addItem(self.right_vb)
        self.pi.getAxis("right").linkToView(self.right_vb)
        self.right_vb.setXLink(self.pi)
        self.pi.vb.sigResized.connect(self._sync_right_vb)
        self._sync_right_vb()

        self.pi.scene().sigMouseClicked.connect(self._on_mouse_click)
        self.pw.setToolTip(
            "Click empty space to drop a marker on the trace nearest the cursor.\n"
            "Drag a line marker to move it. Right-click a marker line for options.\n"
            "Wheel = zoom, drag = pan; right-click on the plot = pyqtgraph menu."
        )
        v.addWidget(self.pw, 1)

        # Persistent artist registries.
        # Curves keyed by f"{trace_name}|{format}|{axis}" so two assignments
        # of the same trace (e.g. S11 dB + S11 VSWR) don't collide.
        self._curves_left: Dict[str, pg.PlotDataItem] = {}
        self._curves_right: Dict[str, pg.PlotDataItem] = {}
        self._marker_lines: Dict[str, pg.InfiniteLine] = {}
        # Per-marker dot lists: label -> list of (host, scatter)
        self._marker_dot_groups: Dict[str, List[tuple]] = {}
        self._region_items: Dict[str, pg.LinearRegionItem] = {}

        # Track applied axis state so we don't repeatedly re-enable autorange
        # (which silently kills the user's manual zoom on the next sweep).
        self._applied_axes = {
            "x": (None, None, None),
            "yl": (None, None, None),
            "yr": (None, None, None),
        }

    def _sync_right_vb(self) -> None:
        self.right_vb.setGeometry(self.pi.vb.sceneBoundingRect())
        self.right_vb.linkedViewChanged(self.pi.vb, self.right_vb.XAxis)

    # ------------------------------------------------------------ drawing
    def draw(self) -> None:
        self.lbl_title.setText(self.title)

        # Gather active assignments by axis. Compose unique keys per
        # assignment so multiple S11 assignments (e.g. dB and VSWR) coexist.
        left_assigns: List[TraceAssignment] = []
        right_assigns: List[TraceAssignment] = []
        seen_left: set[str] = set()
        seen_right: set[str] = set()
        for a in self._assignments:
            if not a.visible:
                continue
            t = self.traces.get(a.trace_name)
            if t is None or t.freq.size == 0:
                continue
            key = self._curve_key(a)
            if a.axis == "right":
                right_assigns.append(a); seen_right.add(key)
            else:
                left_assigns.append(a); seen_left.add(key)

        self._draw_axis_curves(left_assigns, self.pi, self._curves_left, seen_left)
        self._draw_axis_curves(right_assigns, self.right_vb, self._curves_right, seen_right)

        # Axis labels — pick the format of the first trace on each side
        if left_assigns:
            self.pi.setLabel("left", left_assigns[0].y_format)
        else:
            self.pi.setLabel("left", "")
        if right_assigns:
            self.pi.setLabel("right", right_assigns[0].y_format)
            self.pi.showAxis("right")
        else:
            self.pi.setLabel("right", "")

        # Apply axis ranges
        self._apply_axis_ranges()

        # Markers (only those scoped to this panel)
        self._draw_markers()

    @staticmethod
    def _curve_key(a: TraceAssignment) -> str:
        return f"{a.trace_name}|{a.y_format}|{a.axis}"

    def _draw_axis_curves(self, assigns: List[TraceAssignment],
                          host, registry: Dict[str, pg.PlotDataItem],
                          seen_keys: set) -> None:
        # Drop curves no longer present.
        for key in list(registry.keys()):
            if key not in seen_keys:
                try:
                    host.removeItem(registry[key])
                except Exception:
                    pass
                del registry[key]

        for a in assigns:
            t = self.traces.get(a.trace_name)
            if t is None or t.freq.size == 0:
                continue
            x = t.freq
            y = _y_for(t, a.y_format, z0=self._z0)
            color = QColor(a.color_for(t))
            pen = pg.mkPen(color, width=a.line_width, style=style_to_qt_pen(a.line_style))
            symbol = "o" if a.show_dots else None
            label = f"{a.trace_name} ({a.y_format})"
            key = self._curve_key(a)

            curve = registry.get(key)
            if curve is None:
                curve = pg.PlotDataItem(x, y, pen=pen, symbol=symbol,
                                        symbolBrush=color, symbolPen=color,
                                        symbolSize=5, name=label)
                host.addItem(curve)
                registry[key] = curve
            else:
                curve.setData(x, y)
                curve.setPen(pen)
                curve.opts["name"] = label
                if symbol:
                    curve.setSymbol("o")
                    curve.setSymbolBrush(color)
                    curve.setSymbolPen(color)
                else:
                    curve.setSymbol(None)

    def _apply_axis_ranges(self) -> None:
        """
        Only push axis state to pyqtgraph when our local config actually
        changed. Otherwise the user's manual zoom (which pyqtgraph implicitly
        disables autorange for) gets clobbered by a redundant
        enableAutoRange(True) on every redraw.
        """
        # X axis
        new_x = (self.x_auto, self.x_min, self.x_max)
        if new_x != self._applied_axes["x"]:
            if self.x_auto:
                self.pi.enableAutoRange(axis="x", enable=True)
            else:
                self.pi.setXRange(self.x_min, self.x_max, padding=0)
            self._applied_axes["x"] = new_x
        # Y left
        new_yl = (self.yl_auto, self.yl_min, self.yl_max)
        if new_yl != self._applied_axes["yl"]:
            if self.yl_auto:
                self.pi.enableAutoRange(axis="y", enable=True)
            else:
                self.pi.setYRange(self.yl_min, self.yl_max, padding=0)
            self._applied_axes["yl"] = new_yl
        # Y right
        new_yr = (self.yr_auto, self.yr_min, self.yr_max)
        if new_yr != self._applied_axes["yr"]:
            if self.yr_auto:
                self.right_vb.enableAutoRange(axis="y", enable=True)
            else:
                self.right_vb.setYRange(self.yr_min, self.yr_max, padding=0)
            self._applied_axes["yr"] = new_yr

    def set_axis_ranges(self, *args, **kwargs) -> None:
        # Invalidate the applied cache so the next draw re-pushes state.
        self._applied_axes = {"x": (None, None, None),
                              "yl": (None, None, None),
                              "yr": (None, None, None)}
        super().set_axis_ranges(*args, **kwargs)

    def _draw_markers(self) -> None:
        markers = self.markers_for_panel()
        seen_labels: set[str] = set()
        for m in markers:
            seen_labels.add(m.label)
            self._draw_marker(m)

        # Drop artists for markers no longer on this panel.
        for label in list(self._marker_lines.keys()):
            if label not in seen_labels:
                self.pi.removeItem(self._marker_lines.pop(label))
        for label in list(self._marker_dot_groups.keys()):
            if label not in seen_labels:
                for host, scatter in self._marker_dot_groups[label]:
                    try:
                        host.removeItem(scatter)
                    except Exception:
                        pass
                del self._marker_dot_groups[label]
        for label in list(self._region_items.keys()):
            if label not in seen_labels:
                self.pi.removeItem(self._region_items.pop(label))

    def _draw_marker(self, m: Marker) -> None:
        style = m.style if m.style in ("line", "point", "both") else "both"

        # Bandwidth shading (only for BW marker kind)
        if m.kind == MarkerKind.BW_M10DB and m.secondary_freq_hz > m.freq_hz:
            region = self._region_items.get(m.label)
            if region is None:
                region = pg.LinearRegionItem(
                    values=(m.freq_hz, m.secondary_freq_hz),
                    brush=pg.mkBrush(QColor(0, 224, 180, 35)),
                    pen=pg.mkPen(QColor(0, 224, 180, 120), width=1),
                    movable=False,
                )
                self.pi.addItem(region)
                self._region_items[m.label] = region
            else:
                region.setRegion((m.freq_hz, m.secondary_freq_hz))
        elif m.label in self._region_items:
            self.pi.removeItem(self._region_items.pop(m.label))

        # Vertical line — one per marker.
        if style in ("line", "both"):
            line = self._marker_lines.get(m.label)
            movable = (m.kind == MarkerKind.NORMAL)
            if line is None:
                line = pg.InfiniteLine(
                    pos=m.freq_hz, angle=90, movable=movable,
                    pen=pg.mkPen(QColor(m.color), width=1, style=Qt.PenStyle.DotLine),
                    hoverPen=pg.mkPen(QColor(m.color), width=2),
                    label=m.label,
                    labelOpts={"color": "#e0e0e0", "fill": (30, 30, 30, 200),
                               "movable": True, "position": 0.95},
                )
                if movable:
                    line.sigPositionChangeFinished.connect(
                        lambda l, label=m.label: self.marker_dragged.emit(label, float(l.value()))
                    )
                self._install_marker_context(line, m.label)
                self.pi.addItem(line)
                self._marker_lines[m.label] = line
            else:
                line.setValue(m.freq_hz)
                line.setPen(pg.mkPen(QColor(m.color), width=1, style=Qt.PenStyle.DotLine))
                line.label.setText(m.label)
                line.setMovable(m.kind == MarkerKind.NORMAL)
        elif m.label in self._marker_lines:
            self.pi.removeItem(self._marker_lines.pop(m.label))

        # Dots — one per visible-trace-this-panel-shows that the line crosses.
        # That's the whole point of a vertical marker: it tells you what every
        # trace's value is at that frequency.
        old_groups = self._marker_dot_groups.pop(m.label, [])
        for host, scatter in old_groups:
            try:
                host.removeItem(scatter)
            except Exception:
                pass

        if style in ("point", "both"):
            new_groups: List[tuple] = []
            for a in self._assignments:
                if not a.visible:
                    continue
                t = self.traces.get(a.trace_name)
                if t is None or t.freq.size == 0:
                    continue
                idx = int(np.argmin(np.abs(t.freq - m.freq_hz)))
                y_at = float(_y_for(t, a.y_format, z0=self._z0)[idx])
                host = self.right_vb if a.axis == "right" else self.pi
                scatter = pg.ScatterPlotItem(
                    x=[float(t.freq[idx])], y=[y_at],
                    pen=pg.mkPen(QColor(m.color), width=1),
                    brush=pg.mkBrush(QColor(m.color)),
                    size=10, symbol="o",
                )
                host.addItem(scatter)
                new_groups.append((host, scatter))
            if new_groups:
                self._marker_dot_groups[m.label] = new_groups

    def _install_marker_context(self, line: pg.InfiniteLine, label: str) -> None:
        """Surface a right-click menu by intercepting the line's mouseClickEvent."""
        original_handler = line.mouseClickEvent

        def handler(ev):
            if ev.button() == Qt.MouseButton.RightButton:
                ev.accept()
                screen_pos = ev.screenPos()
                # screenPos returns QPointF; convert to QPoint
                self.marker_context.emit(label, QPoint(int(screen_pos.x()),
                                                      int(screen_pos.y())))
                return
            original_handler(ev)

        line.mouseClickEvent = handler

    # ------------------------------------------------------------ events
    def _on_mouse_click(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if event.double():
            return
        if event.isAccepted():
            return  # an item handled it (e.g. dragging a marker)

        # Click point in left-axis coords + right-axis coords (different Y units)
        try:
            point_left = self.pi.vb.mapSceneToView(event.scenePos())
            point_right = self.right_vb.mapSceneToView(event.scenePos())
        except Exception:
            return

        f_hz = float(point_left.x())
        y_left = float(point_left.y())
        y_right = float(point_right.y())

        # Normalize distances by axis span so units don't dominate.
        xrng = self.pi.vb.viewRange()[0]
        ylrng = self.pi.vb.viewRange()[1]
        yrrng = self.right_vb.viewRange()[1]
        xspan = max(1e-12, xrng[1] - xrng[0])
        ylspan = max(1e-12, ylrng[1] - ylrng[0])
        yrspan = max(1e-12, yrrng[1] - yrrng[0])

        best_dist = float("inf")
        best_name: Optional[str] = None
        for a in self._assignments:
            if not a.visible:
                continue
            t = self.traces.get(a.trace_name)
            if t is None or t.freq.size == 0:
                continue
            idx = int(np.argmin(np.abs(t.freq - f_hz)))
            y_at = float(_y_for(t, a.y_format, z0=self._z0)[idx])
            if a.axis == "right":
                yc = y_right; yspan = yrspan
            else:
                yc = y_left; yspan = ylspan
            dx = (t.freq[idx] - f_hz) / xspan
            dy = (y_at - yc) / yspan
            d = (dx * dx + dy * dy) ** 0.5
            if d < best_dist:
                best_dist = d
                best_name = a.trace_name
        if best_name is not None:
            self.marker_placed.emit(best_name, f_hz, self.plot_id)

    # ------------------------------------------------------------ export
    def export_image(self, path: str, width_px: int, height_px: int,
                     fmt: str = "png") -> bool:
        try:
            from pyqtgraph.exporters import ImageExporter, SVGExporter
        except Exception:
            return False
        if fmt.lower() == "svg":
            exp = SVGExporter(self.pi)
        else:
            exp = ImageExporter(self.pi)
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


register_plot("cartesian")

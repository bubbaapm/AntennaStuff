"""
Base class for plot panels.

A plot panel owns a list of `TraceAssignment` objects (which traces, on
which axis, in what format, with what color/style) and a list of markers.
Subclasses implement `draw()` for their specific plot type.

Each panel has a unique `plot_id` so markers can be scoped to individual
panels ("show on this plot only").
"""
from __future__ import annotations
import uuid
from abc import abstractmethod
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QPushButton, QStyle, QWidget

from ..markers import Marker
from ..trace import Trace, TraceAssignment, TraceManager


PLOT_TYPES: List[str] = []


class PlotPanel(QWidget):
    """ABC-ish — concrete plots inherit and implement draw()."""

    KIND: str = "base"
    TITLE: str = "Plot"
    SUPPORTS_DUAL_Y: bool = False        # cartesian overrides
    SUPPORTS_FORMATS: bool = False       # cartesian overrides
    DEFAULT_PARAMS = ("S11", "S22")      # what fresh assignments default to

    request_remove = pyqtSignal(object)             # self when × clicked
    request_move = pyqtSignal(object, int)          # self, direction (-1 / +1)
    request_configure = pyqtSignal(object)          # self when ⚙ clicked
    request_reset_view = pyqtSignal(object)         # self when ⟲ clicked
    marker_placed = pyqtSignal(str, float, str)     # trace_name, freq_hz, panel_id
    marker_dragged = pyqtSignal(str, float)         # marker label, new freq_hz
    marker_context = pyqtSignal(str, object)        # label, screen_pos QPoint

    def __init__(self, traces: TraceManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.plot_id = uuid.uuid4().hex[:8]
        self.title = self.TITLE
        self.traces = traces
        self._assignments: List[TraceAssignment] = []
        self._markers: List[Marker] = []
        self._z0: float = 50.0

        # Manual axis range overrides (None = autorange).
        # 3 axes total: x, y_left, y_right.
        self.x_auto = True
        self.x_min = 0.0
        self.x_max = 6e9
        self.yl_auto = True
        self.yl_min = -50.0
        self.yl_max = 5.0
        self.yr_auto = True
        self.yr_min = 1.0
        self.yr_max = 10.0

        # Debounce paint events (12 Hz max).
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(80)
        self._redraw_timer.timeout.connect(self.draw)

        traces.traces_changed.connect(self._on_traces_changed)
        traces.traces_data.connect(self._request_redraw)

    # --------------------------------------------------------------- API
    def set_assignments(self, assignments: List[TraceAssignment]) -> None:
        self._assignments = list(assignments)
        self._request_redraw()

    def get_assignments(self) -> List[TraceAssignment]:
        return list(self._assignments)

    def add_assignment(self, a: TraceAssignment) -> None:
        self._assignments.append(a)
        self._request_redraw()

    def remove_assignment(self, trace_name: str) -> None:
        self._assignments = [a for a in self._assignments if a.trace_name != trace_name]
        self._request_redraw()

    def set_markers(self, markers: List[Marker]) -> None:
        self._markers = list(markers)
        # Subclasses may override to preserve drag state — see CartesianPlot.
        self._after_markers_set()
        self._request_redraw()

    def _after_markers_set(self) -> None:
        """Hook for subclasses to fix up state after the master list arrived."""
        pass

    def set_z0(self, z0: float) -> None:
        self._z0 = float(z0)
        self._request_redraw()

    def set_title(self, t: str) -> None:
        self.title = t
        self._request_redraw()

    def set_axis_ranges(self,
                        x_auto: bool, x_min: float, x_max: float,
                        yl_auto: bool, yl_min: float, yl_max: float,
                        yr_auto: bool = True, yr_min: float = 1.0, yr_max: float = 10.0,
                        ) -> None:
        self.x_auto = x_auto;   self.x_min = x_min;   self.x_max = x_max
        self.yl_auto = yl_auto; self.yl_min = yl_min; self.yl_max = yl_max
        self.yr_auto = yr_auto; self.yr_min = yr_min; self.yr_max = yr_max
        self._request_redraw()

    def _request_redraw(self) -> None:
        self._redraw_timer.start()

    def reset_view(self) -> None:
        """
        Default implementation: switch all axes back to auto-range.
        Subclasses (cartesian) override to push state to pyqtgraph immediately.
        """
        self.x_auto = True
        self.yl_auto = True
        self.yr_auto = True
        self._request_redraw()

    def visible_assignments(self) -> List[TraceAssignment]:
        out = []
        for a in self._assignments:
            if not a.visible:
                continue
            t = self.traces.get(a.trace_name)
            if t is None or not t.visible:
                continue
            out.append(a)
        return out

    def auto_title(self) -> str:
        """
        Title derived from the active assignments — e.g. "S11 (Cartesian)"
        or "S11, S22 (Smith Chart)". Falls back to the bare plot kind when
        nothing is assigned. Used as the default header when the user
        hasn't typed a custom title in the configure dialog.
        """
        seen: set[str] = set()
        params: List[str] = []
        for a in self._assignments:
            if a.trace_name in seen:
                continue
            seen.add(a.trace_name)
            params.append(a.trace_name)
        if not params:
            return self.TITLE
        return f"{', '.join(params)}  ({self.TITLE})"

    @property
    def header_title(self) -> str:
        """The string that should appear in the panel's title label."""
        return self.title if self.title and self.title != self.TITLE else self.auto_title()

    def markers_for_panel(self) -> List[Marker]:
        out = []
        for m in self._markers:
            if not m.visible:
                continue
            if m.scope == "panel" and m.panel_id and m.panel_id != self.plot_id:
                continue
            out.append(m)
        return out

    # ---------------------------------------------------------------- hooks
    def _on_traces_changed(self) -> None:
        self._request_redraw()

    @abstractmethod
    def draw(self) -> None: ...

    @abstractmethod
    def export_image(self, path: str, width_px: int, height_px: int,
                     fmt: str = "png") -> bool: ...

    # ----------------------------------------------------------- serialize
    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.KIND,
            "title": self.title,
            "plot_id": self.plot_id,
            "assignments": [a.to_dict() for a in self._assignments],
            "x_auto": self.x_auto, "x_min": self.x_min, "x_max": self.x_max,
            "yl_auto": self.yl_auto, "yl_min": self.yl_min, "yl_max": self.yl_max,
            "yr_auto": self.yr_auto, "yr_min": self.yr_min, "yr_max": self.yr_max,
        }

    def from_dict(self, d: Dict[str, Any]) -> None:
        self.title = d.get("title", self.TITLE)
        if d.get("plot_id"):
            self.plot_id = d["plot_id"]
        if "assignments" in d:
            self._assignments = [TraceAssignment.from_dict(x) for x in d["assignments"]]
        self.x_auto = d.get("x_auto", True)
        self.x_min = d.get("x_min", 0.0); self.x_max = d.get("x_max", 6e9)
        self.yl_auto = d.get("yl_auto", True)
        self.yl_min = d.get("yl_min", -50.0); self.yl_max = d.get("yl_max", 5.0)
        self.yr_auto = d.get("yr_auto", True)
        self.yr_min = d.get("yr_min", 1.0); self.yr_max = d.get("yr_max", 10.0)
        self._request_redraw()


def register_plot(kind: str) -> None:
    if kind not in PLOT_TYPES:
        PLOT_TYPES.append(kind)


def make_header_buttons(panel: PlotPanel):
    """
    Build the standard 5-button header row (configure / reset / left /
    right / remove). Returns the buttons in a list so subclasses can lay
    them out themselves; signals are pre-wired to the panel.
    Uses Qt's standard icons so symbols always render legibly across
    platforms / fonts (no more box-glyphs for ⚙ ◀ ▶ ✕).
    """
    style = panel.style()

    btn_config = QPushButton()
    btn_config.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
    btn_config.setFixedWidth(28)
    btn_config.setToolTip("Configure traces, axes, colors, line styles…")
    btn_config.clicked.connect(lambda: panel.request_configure.emit(panel))

    btn_reset = QPushButton()
    btn_reset.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
    btn_reset.setFixedWidth(28)
    btn_reset.setToolTip("Reset zoom — fit all axes to the current data")
    btn_reset.clicked.connect(lambda: panel.request_reset_view.emit(panel))

    btn_left = QPushButton()
    btn_left.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
    btn_left.setFixedWidth(28)
    btn_left.setToolTip("Move plot one position left")
    btn_left.clicked.connect(lambda: panel.request_move.emit(panel, -1))

    btn_right = QPushButton()
    btn_right.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
    btn_right.setFixedWidth(28)
    btn_right.setToolTip("Move plot one position right")
    btn_right.clicked.connect(lambda: panel.request_move.emit(panel, +1))

    btn_remove = QPushButton()
    btn_remove.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
    btn_remove.setFixedWidth(28)
    btn_remove.setToolTip("Remove this plot panel")
    btn_remove.clicked.connect(lambda: panel.request_remove.emit(panel))

    return btn_config, btn_reset, btn_left, btn_right, btn_remove


def style_to_qt_pen(line_style: str):
    """Convert our string style name to Qt.PenStyle."""
    from PyQt6.QtCore import Qt
    return {
        "solid": Qt.PenStyle.SolidLine,
        "dash": Qt.PenStyle.DashLine,
        "dot": Qt.PenStyle.DotLine,
        "dashdot": Qt.PenStyle.DashDotLine,
    }.get(line_style, Qt.PenStyle.SolidLine)


def style_to_mpl(line_style: str) -> str:
    """Matplotlib linestyle string."""
    return {
        "solid": "-", "dash": "--", "dot": ":", "dashdot": "-.",
    }.get(line_style, "-")


def default_assignments(kind: str, params=None) -> List[TraceAssignment]:
    """Sensible default assignments for a fresh plot panel."""
    params = list(params) if params else ["S11", "S22"]
    out = []
    for p in params:
        out.append(TraceAssignment(
            trace_name=p, axis="left", y_format="dB",
            color_override="", line_style="solid", line_width=2.0,
            show_dots=False, visible=True,
        ))
    return out

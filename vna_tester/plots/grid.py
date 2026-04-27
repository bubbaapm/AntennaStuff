"""
Tile-able plot grid container.

Holds a dynamic grid of plot panels. Forwards per-panel signals out so
the main window can wire them: configure dialog, marker placement,
marker drag, marker right-click, plot reorder.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Type

from PyQt6.QtCore import pyqtSignal, Qt, QPoint
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..markers import Marker
from ..trace import TraceAssignment, TraceManager, VNA_PARAMS
from .base import PlotPanel
from .cartesian import CartesianPlot
from .smith import SmithPlot
from .polar import PolarPlot
from .tdr import TDRPlot

from ..ui.plot_config_dialog import NewPlotDialog


PLOT_CLASS_REGISTRY: Dict[str, Type[PlotPanel]] = {
    "cartesian": CartesianPlot,
    "smith": SmithPlot,
    "polar": PolarPlot,
    "tdr": TDRPlot,
}


class PlotGrid(QWidget):
    """Tile-able container; main window does the heavy wiring."""

    panel_added = pyqtSignal(object)
    panel_removed = pyqtSignal(object)
    marker_placed = pyqtSignal(str, float, str)        # trace_name, freq, panel_id
    marker_dragged = pyqtSignal(str, float)            # label, freq
    marker_context = pyqtSignal(str, object, object)   # label, screen_pos, panel
    panel_configure = pyqtSignal(object)               # panel
    export_all_requested = pyqtSignal()

    def __init__(self, traces: TraceManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.traces = traces
        self._panels: List[PlotPanel] = []
        self._markers: List[Marker] = []
        self._z0 = 50.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(2)

        self._toolbar = QHBoxLayout()
        self._toolbar.setContentsMargins(6, 4, 6, 0)

        self.btn_add = QPushButton("➕  Add plot")
        self.btn_add.setToolTip("Add a new plot panel (Cartesian / Smith / Polar / Time domain)")
        self.btn_add.clicked.connect(self._on_add_clicked)
        self._toolbar.addWidget(self.btn_add)

        self.btn_clear = QPushButton("Clear all")
        self.btn_clear.setToolTip("Remove every plot panel")
        self.btn_clear.clicked.connect(self.clear)
        self._toolbar.addWidget(self.btn_clear)

        self.btn_export_all = QPushButton("🖼  Export all…")
        self.btn_export_all.setToolTip(
            "Export every plot in the current grid as one image.\n"
            "Each plot is re-rendered at the chosen resolution."
        )
        self.btn_export_all.clicked.connect(self.export_all_requested.emit)
        self._toolbar.addWidget(self.btn_export_all)

        self._toolbar.addStretch(1)
        self.lbl_count = QLabel("0 plots")
        self.lbl_count.setStyleSheet("color:#888;")
        self._toolbar.addWidget(self.lbl_count)
        outer.addLayout(self._toolbar)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(2, 2, 2, 2); self._grid.setSpacing(4)
        outer.addWidget(self._grid_host, 1)

        # Default layout
        self._add_panel("cartesian", assignments=None, params=["S11", "S22"])
        self._add_panel("smith", assignments=None, params=["S11", "S22"])

    # ----------------------------------------------------------------- API
    def panels(self) -> List[PlotPanel]:
        return list(self._panels)

    def set_markers(self, markers: List[Marker]) -> None:
        self._markers = list(markers)
        for p in self._panels:
            p.set_markers(self._markers)

    def set_z0(self, z0: float) -> None:
        self._z0 = float(z0)
        for p in self._panels:
            p.set_z0(self._z0)

    def add_plot(self, kind: str, **opts: Any) -> Optional[PlotPanel]:
        """Programmatic add — used by add-dialog and session restore."""
        return self._add_panel(kind, **opts)

    def _add_panel(self, kind: str, **opts: Any) -> Optional[PlotPanel]:
        cls = PLOT_CLASS_REGISTRY.get(kind)
        if cls is None:
            return None
        kwargs: Dict[str, Any] = {}
        if "assignments" in opts and opts["assignments"]:
            kwargs["assignments"] = opts["assignments"]
        if "params" in opts and opts["params"]:
            kwargs["params"] = opts["params"]
        if kind == "cartesian" and "y_format" in opts and opts["y_format"]:
            kwargs["y_format"] = opts["y_format"]
        panel = cls(self.traces, **kwargs)
        if "title" in opts and opts["title"]:
            panel.set_title(opts["title"])
        panel.set_markers(self._markers)
        panel.set_z0(self._z0)
        self._connect_panel(panel)
        self._panels.append(panel)
        self._relayout()
        self.panel_added.emit(panel)
        return panel

    def _connect_panel(self, panel: PlotPanel) -> None:
        panel.request_remove.connect(self._remove_panel)
        panel.request_move.connect(self._move_panel)
        panel.request_configure.connect(self.panel_configure.emit)
        panel.marker_placed.connect(self.marker_placed.emit)
        if hasattr(panel, "marker_dragged"):
            panel.marker_dragged.connect(self.marker_dragged.emit)
        if hasattr(panel, "marker_context"):
            panel.marker_context.connect(
                lambda label, pos, p=panel: self.marker_context.emit(label, pos, p)
            )

    def _remove_panel(self, panel: PlotPanel) -> None:
        if panel in self._panels:
            self._panels.remove(panel)
            panel.setParent(None); panel.deleteLater()
            self._relayout()
            self.panel_removed.emit(panel)

    def _move_panel(self, panel: PlotPanel, direction: int) -> None:
        if panel not in self._panels:
            return
        i = self._panels.index(panel)
        j = i + (1 if direction > 0 else -1)
        if 0 <= j < len(self._panels):
            self._panels[i], self._panels[j] = self._panels[j], self._panels[i]
            self._relayout()

    def clear(self) -> None:
        for p in list(self._panels):
            self._remove_panel(p)

    def _relayout(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                self._grid.removeWidget(w)
        n = len(self._panels)
        self.lbl_count.setText(f"{n} plot{'s' if n != 1 else ''}")
        if n == 0:
            empty = QLabel("No plots — click 'Add plot'.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color:#666; padding:40px;")
            self._grid.addWidget(empty, 0, 0)
            return
        cols = 1 if n == 1 else (2 if n <= 4 else 3)
        for i, p in enumerate(self._panels):
            r, c = divmod(i, cols)
            self._grid.addWidget(p, r, c)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)
        rows = (n + cols - 1) // cols
        for r in range(rows):
            self._grid.setRowStretch(r, 1)

    # ------------------------------------------------------------- ui events
    def _on_add_clicked(self) -> None:
        names = [t.name for t in self.traces.all()] or list(VNA_PARAMS)
        dlg = NewPlotDialog(self.traces, names, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            kind, assigns = dlg.selection()
            self._add_panel(kind, assignments=assigns)

    # --------------------------------------------------------------- session
    def to_dict(self) -> Dict[str, Any]:
        return {"panels": [p.to_dict() for p in self._panels]}

    def restore(self, d: Dict[str, Any]) -> None:
        self.clear()
        for p in d.get("panels", []):
            kind = p.get("kind", "cartesian")
            cls = PLOT_CLASS_REGISTRY.get(kind)
            if cls is None:
                continue
            panel = cls(self.traces)
            panel.from_dict(p)
            panel.set_markers(self._markers)
            panel.set_z0(self._z0)
            self._connect_panel(panel)
            self._panels.append(panel)
        self._relayout()

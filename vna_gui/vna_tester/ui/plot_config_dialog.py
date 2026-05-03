"""
Plot configuration dialogs.

NewPlotDialog       — picks plot type + initial trace assignments.
ConfigurePlotDialog — full per-trace customization + axis ranges + title.

A "trace row" widget is reused in both. Each row has:
  trace name | (axis | format) | color swatch | line style | width | dots | visible | ✕
The (axis | format) columns appear only for cartesian plots.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from ..trace import LINE_STYLES, TraceAssignment, TraceManager, VNA_PARAMS
from ..plots.cartesian import CARTESIAN_FORMATS


PLOT_LABEL: Dict[str, str] = {
    "cartesian": "Cartesian (XY)",
    "smith": "Smith chart",
    "polar": "Polar",
    "tdr": "Time domain",
}


# Unit family groupings — formats that share a Y-axis comfortably go in the
# same group. Mixing groups on one axis is technically allowed but the scales
# are nonsense, so we surface a warning and recommend the right axis.
FORMAT_FAMILIES: Dict[str, str] = {
    "dB": "dB",
    "Mismatch loss (dB)": "dB",
    "Linear |S|": "linear",
    "Real": "linear",
    "Imag": "linear",
    "VSWR": "vswr",
    "Phase (°)": "degrees",
    "Phase unwrapped (°)": "degrees",
    "Group delay (ns)": "ns",
    "Re(Z) Ω": "ohms",
    "Im(Z) Ω": "ohms",
    "|Z| Ω": "ohms",
}


def _validate_assignments(plot_kind: str, assigns) -> str:
    """Return a warning string if the assignment set is sketchy, else ''."""
    if plot_kind != "cartesian":
        return ""
    by_axis: Dict[str, set] = {"left": set(), "right": set()}
    for a in assigns:
        fam = FORMAT_FAMILIES.get(a.y_format, a.y_format)
        by_axis[a.axis].add(fam)
    msgs = []
    for axis, fams in by_axis.items():
        if len(fams) > 1:
            msgs.append(
                f"⚠  {axis.capitalize()} Y-axis mixes {len(fams)} unit families "
                f"({', '.join(sorted(fams))}). Lines will share one numeric scale, "
                f"so values won't align with their tick labels. Consider moving "
                f"one trace to the {'right' if axis == 'left' else 'left'} axis."
            )
    return "\n".join(msgs)


def _swatch_icon(hex_color: str, size: int = 14) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(QColor(hex_color))
    return QIcon(pix)


# ============================================================== row widget

class TraceRowWidget(QFrame):
    """
    One row of the trace assignment table. Manages its own widgets and
    can serialize to / deserialize from a TraceAssignment.

    The color swatch shows either the per-plot override (if set) OR the
    selected trace's global color, so the dialog never lies about what
    the user is currently looking at on the plot.
    """

    removed = pyqtSignal(object)
    changed = pyqtSignal()        # any field changed (for live validation)

    def __init__(self, traces: TraceManager,
                 available_trace_names: List[str],
                 plot_kind: str = "cartesian",
                 parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.kind = plot_kind
        self.traces = traces
        # _color carries either the override (when _has_override is True)
        # or a cached copy of the trace's current global color (display only).
        self._color = "#00e0b4"
        self._has_override = False
        self._build(available_trace_names)

    def _build(self, names: List[str]) -> None:
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(6)

        self.cb_trace = QComboBox()
        self.cb_trace.addItems(names)
        self.cb_trace.setMinimumWidth(120)
        self.cb_trace.setToolTip("Which trace to plot (live S-parameter or loaded reference).")
        # Re-seed the swatch when the user picks a different trace, so the
        # row always shows the trace's current color until they pick an override.
        self.cb_trace.currentTextChanged.connect(self._on_trace_changed)
        h.addWidget(self.cb_trace)

        if self.kind == "cartesian":
            self.cb_axis = QComboBox()
            self.cb_axis.addItems(["left", "right"])
            self.cb_axis.setToolTip(
                "Y-axis assignment. Use the right axis to overlay a different\n"
                "quantity (e.g. VSWR on right while dB stays on left)."
            )
            self.cb_axis.currentTextChanged.connect(lambda _=None: self.changed.emit())
            h.addWidget(self.cb_axis)

            self.cb_format = QComboBox()
            self.cb_format.addItems(CARTESIAN_FORMATS)
            self.cb_format.setToolTip("How this trace's complex value is converted to a Y value.")
            self.cb_format.setMinimumWidth(120)
            self.cb_format.currentTextChanged.connect(lambda _=None: self.changed.emit())
            h.addWidget(self.cb_format)

        self.btn_color = QPushButton(" ")
        self.btn_color.setFixedWidth(34)
        self.btn_color.clicked.connect(self._pick_color)
        # right-click clears the override and reverts to the trace's color
        self.btn_color.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_color.customContextMenuRequested.connect(self._clear_color_override)
        # initialize with the current trace's color so the swatch is honest
        self._reseed_color_from_trace()
        h.addWidget(self.btn_color)

        self.cb_style = QComboBox()
        self.cb_style.addItems(list(LINE_STYLES))
        self.cb_style.setToolTip("Line style: solid / dash / dot / dashdot.")
        self.cb_style.currentTextChanged.connect(lambda _=None: self.changed.emit())
        h.addWidget(self.cb_style)

        self.sp_width = QDoubleSpinBox()
        self.sp_width.setRange(0.5, 6.0); self.sp_width.setSingleStep(0.5)
        self.sp_width.setValue(2.0)
        self.sp_width.setToolTip("Line width in pixels.")
        self.sp_width.setMaximumWidth(70)
        self.sp_width.valueChanged.connect(lambda _=None: self.changed.emit())
        h.addWidget(self.sp_width)

        self.cb_dots = QCheckBox("dots")
        self.cb_dots.setToolTip("Overlay scatter points along the line.")
        self.cb_dots.toggled.connect(lambda _=None: self.changed.emit())
        h.addWidget(self.cb_dots)

        self.cb_visible = QCheckBox("show")
        self.cb_visible.setChecked(True)
        self.cb_visible.setToolTip("Hide this trace without removing it from the plot.")
        self.cb_visible.toggled.connect(lambda _=None: self.changed.emit())
        h.addWidget(self.cb_visible)

        self.btn_remove = QToolButton()
        self.btn_remove.setText("✕")
        self.btn_remove.setToolTip("Remove this trace from the plot")
        self.btn_remove.clicked.connect(lambda: self.removed.emit(self))
        h.addWidget(self.btn_remove)

    def _refresh_color_button(self) -> None:
        if not self._color:
            self.btn_color.setStyleSheet("background:#3a3a3a; color:#888;")
            self.btn_color.setText("?")
            self.btn_color.setToolTip("Click to pick a per-plot color.")
            return
        c = QColor(self._color)
        text = "#0a0a0a" if (c.red() + c.green() + c.blue()) > 384 else "#e0e0e0"
        self.btn_color.setStyleSheet(
            f"background:{self._color}; color:{text}; font-weight:bold;"
        )
        # Indicate whether this color is an override or just the trace's color.
        if self._has_override:
            self.btn_color.setText("•")
            self.btn_color.setToolTip(
                "Per-plot color override — click to change, "
                "or right-click to clear and inherit from the trace."
            )
        else:
            self.btn_color.setText("")
            self.btn_color.setToolTip(
                "Currently inheriting the trace's global color.\n"
                "Click to set a per-plot override."
            )

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._color or "#00e0b4"),
                                  self, "Per-plot color (Cancel = inherit trace color)")
        if c.isValid():
            self._color = c.name()
            self._has_override = True
            self._refresh_color_button()
            self.changed.emit()

    def _on_trace_changed(self, name: str) -> None:
        # Switching trace inside a row: if no override is set, refresh the
        # swatch to the new trace's actual color so the dialog always shows
        # truth. (Overrides survive trace switches.)
        if not self._has_override:
            self._reseed_color_from_trace()
        self.changed.emit()

    def _reseed_color_from_trace(self) -> None:
        name = self.cb_trace.currentText()
        t = self.traces.get(name)
        self._color = t.color if t else "#00e0b4"
        self._refresh_color_button()

    def _clear_color_override(self, _pos=None) -> None:
        if self._has_override:
            self._has_override = False
            self._reseed_color_from_trace()
            self.changed.emit()

    def to_assignment(self) -> TraceAssignment:
        # Only persist color_override if the user actually picked one;
        # otherwise leave it blank so the trace's global color flows through.
        return TraceAssignment(
            trace_name=self.cb_trace.currentText(),
            visible=self.cb_visible.isChecked(),
            axis=self.cb_axis.currentText() if self.kind == "cartesian" else "left",
            y_format=self.cb_format.currentText() if self.kind == "cartesian" else "dB",
            color_override=self._color if self._has_override else "",
            line_style=self.cb_style.currentText(),
            line_width=float(self.sp_width.value()),
            show_dots=self.cb_dots.isChecked(),
        )

    def from_assignment(self, a: TraceAssignment) -> None:
        # Block signals while seeding so we don't fire `changed` 8 times.
        for w in (self.cb_trace, self.cb_style, self.sp_width,
                  self.cb_dots, self.cb_visible):
            w.blockSignals(True)
        if self.kind == "cartesian":
            for w in (self.cb_axis, self.cb_format):
                w.blockSignals(True)
        try:
            idx = self.cb_trace.findText(a.trace_name)
            if idx >= 0:
                self.cb_trace.setCurrentIndex(idx)
            if self.kind == "cartesian":
                self.cb_axis.setCurrentText(a.axis)
                self.cb_format.setCurrentText(a.y_format)
            if a.color_override:
                self._color = a.color_override
                self._has_override = True
            else:
                t = self.traces.get(a.trace_name)
                self._color = t.color if t else "#00e0b4"
                self._has_override = False
            self._refresh_color_button()
            self.cb_style.setCurrentText(a.line_style)
            self.sp_width.setValue(a.line_width)
            self.cb_dots.setChecked(a.show_dots)
            self.cb_visible.setChecked(a.visible)
        finally:
            for w in (self.cb_trace, self.cb_style, self.sp_width,
                      self.cb_dots, self.cb_visible):
                w.blockSignals(False)
            if self.kind == "cartesian":
                for w in (self.cb_axis, self.cb_format):
                    w.blockSignals(False)


# =================================================== add plot dialog

class NewPlotDialog(QDialog):
    """Pick plot type + initial trace assignments. Replaces the old AddPlotDialog."""

    def __init__(self, traces: TraceManager,
                 available_trace_names: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add plot")
        self.resize(820, 520)
        self.traces = traces
        self._available = list(available_trace_names) or list(VNA_PARAMS)
        self._rows: List[TraceRowWidget] = []
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(QLabel("Plot type:"))
        self.cb_kind = QComboBox()
        for k, label in PLOT_LABEL.items():
            self.cb_kind.addItem(label, userData=k)
        self.cb_kind.currentIndexChanged.connect(self._on_kind_changed)
        head.addWidget(self.cb_kind, 1)
        v.addLayout(head)

        gb = QGroupBox("Traces in this plot")
        gv = QVBoxLayout(gb)
        gv.setContentsMargins(8, 14, 8, 8); gv.setSpacing(4)
        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        self._rows_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(self._rows_host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        gv.addWidget(scroll, 1)

        actions = QHBoxLayout()
        self.btn_add = QPushButton("+ Add trace")
        self.btn_add.clicked.connect(self._add_default_row)
        actions.addWidget(self.btn_add)
        actions.addStretch(1)
        gv.addLayout(actions)
        v.addWidget(gb, 1)

        # Live-validation banner — warns about mixing units on one axis.
        self.lbl_warning = QLabel("")
        self.lbl_warning.setStyleSheet(
            "color:#ffd34d; background:#2a2a1a; border:1px solid #555533;"
            "padding:6px; border-radius:3px;"
        )
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.setVisible(False)
        v.addWidget(self.lbl_warning)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        # Default rows: S11 + S22 if both available
        defaults = [n for n in ("S11", "S22") if n in self._available]
        if not defaults and self._available:
            defaults = [self._available[0]]
        for n in defaults:
            row = self._make_row(); row.cb_trace.setCurrentText(n)
            row.from_assignment(TraceAssignment(trace_name=n, color_override=""))
        self._on_kind_changed(0)
        self._validate()

    def _on_kind_changed(self, _idx: int) -> None:
        kind = self.cb_kind.currentData()
        # rebuild rows so kind changes take effect
        existing = [r.to_assignment() for r in self._rows]
        for r in self._rows:
            r.setParent(None); r.deleteLater()
        self._rows.clear()
        for a in existing:
            row = self._make_row()
            row.from_assignment(a)

    def _make_row(self) -> TraceRowWidget:
        kind = self.cb_kind.currentData()
        row = TraceRowWidget(self.traces, self._available, plot_kind=kind)
        row.removed.connect(self._remove_row)
        row.changed.connect(self._validate)
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self._rows.append(row)
        self._validate()
        return row

    def _validate(self) -> None:
        if not hasattr(self, "lbl_warning"):
            return
        msg = _validate_assignments(self.cb_kind.currentData(),
                                    [r.to_assignment() for r in self._rows])
        self.lbl_warning.setText(msg)
        self.lbl_warning.setVisible(bool(msg))

    def _add_default_row(self) -> None:
        if not self._available:
            return
        row = self._make_row()
        row.cb_trace.setCurrentIndex(0)

    def _remove_row(self, row: TraceRowWidget) -> None:
        if row in self._rows:
            self._rows.remove(row)
            row.setParent(None); row.deleteLater()

    def selection(self) -> Tuple[str, List[TraceAssignment]]:
        return self.cb_kind.currentData(), [r.to_assignment() for r in self._rows]


# =================================================== configure dialog

class ConfigurePlotDialog(QDialog):
    """
    Full configuration: title, trace assignments (with all per-trace
    options), and axis ranges. Same dialog adapts to any plot kind.
    """

    def __init__(self, plot_kind: str, title: str,
                 assignments: List[TraceAssignment],
                 axis_state: dict,
                 traces: TraceManager,
                 available_trace_names: List[str],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Configure plot — {PLOT_LABEL.get(plot_kind, plot_kind)}")
        self.resize(900, 600)
        self.setMinimumSize(720, 480)
        self.kind = plot_kind
        self.traces = traces
        self._available = list(available_trace_names) or list(VNA_PARAMS)
        self._rows: List[TraceRowWidget] = []
        self._build(title, axis_state)
        for a in assignments:
            row = self._make_row()
            row.from_assignment(a)
        self._validate()

    def _build(self, title: str, axis_state: dict) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        # Title
        head = QHBoxLayout()
        head.addWidget(QLabel("Title:"))
        self.le_title = QLineEdit(title)
        self.le_title.setToolTip("Header text shown above the plot.")
        head.addWidget(self.le_title, 1)
        v.addLayout(head)

        # Traces list
        gb_traces = QGroupBox("Traces")
        gv = QVBoxLayout(gb_traces)
        gv.setContentsMargins(8, 14, 8, 8); gv.setSpacing(4)
        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0); self._rows_layout.setSpacing(4)
        self._rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(self._rows_host); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        gv.addWidget(scroll, 1)

        actions = QHBoxLayout()
        self.btn_add = QPushButton("+ Add trace")
        self.btn_add.clicked.connect(self._add_default_row)
        actions.addWidget(self.btn_add)
        actions.addStretch(1)
        gv.addLayout(actions)
        v.addWidget(gb_traces, 2)

        # Axes
        v.addWidget(self._build_axes_box(axis_state))

        # Live warning banner
        self.lbl_warning = QLabel("")
        self.lbl_warning.setStyleSheet(
            "color:#ffd34d; background:#2a2a1a; border:1px solid #555533;"
            "padding:6px; border-radius:3px;"
        )
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.setVisible(False)
        v.addWidget(self.lbl_warning)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _build_axes_box(self, st: dict) -> QGroupBox:
        gb = QGroupBox("Axis ranges")
        g = QGridLayout(gb)
        g.setContentsMargins(8, 14, 8, 8)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)

        def axis_widgets(prefix: str):
            cb_auto = QCheckBox(f"{prefix} auto")
            sp_min = QDoubleSpinBox()
            sp_min.setRange(-1e15, 1e15); sp_min.setDecimals(4); sp_min.setMaximumWidth(140)
            sp_min.setKeyboardTracking(False)
            sp_max = QDoubleSpinBox()
            sp_max.setRange(-1e15, 1e15); sp_max.setDecimals(4); sp_max.setMaximumWidth(140)
            sp_max.setKeyboardTracking(False)
            cb_auto.toggled.connect(lambda chk: (sp_min.setEnabled(not chk),
                                                 sp_max.setEnabled(not chk)))
            return cb_auto, sp_min, sp_max

        # X axis (Hz for cartesian, abstract otherwise but still meaningful)
        self.cb_x_auto, self.sp_x_min, self.sp_x_max = axis_widgets("X")
        self.sp_x_min.setToolTip("X axis minimum (Hz for cartesian / TDR).")
        self.sp_x_max.setToolTip("X axis maximum.")
        # Y left
        self.cb_yl_auto, self.sp_yl_min, self.sp_yl_max = axis_widgets("Y left")
        # Y right
        self.cb_yr_auto, self.sp_yr_min, self.sp_yr_max = axis_widgets("Y right")

        g.addWidget(QLabel("X axis:"), 0, 0)
        g.addWidget(self.cb_x_auto, 0, 1)
        g.addWidget(QLabel("min:"), 0, 2); g.addWidget(self.sp_x_min, 0, 3)
        g.addWidget(QLabel("max:"), 0, 4); g.addWidget(self.sp_x_max, 0, 5)

        g.addWidget(QLabel("Y left:"), 1, 0)
        g.addWidget(self.cb_yl_auto, 1, 1)
        g.addWidget(QLabel("min:"), 1, 2); g.addWidget(self.sp_yl_min, 1, 3)
        g.addWidget(QLabel("max:"), 1, 4); g.addWidget(self.sp_yl_max, 1, 5)

        g.addWidget(QLabel("Y right:"), 2, 0)
        g.addWidget(self.cb_yr_auto, 2, 1)
        g.addWidget(QLabel("min:"), 2, 2); g.addWidget(self.sp_yr_min, 2, 3)
        g.addWidget(QLabel("max:"), 2, 4); g.addWidget(self.sp_yr_max, 2, 5)

        # Disable Y-right for non-cartesian
        if self.kind != "cartesian":
            for w in (self.cb_yr_auto, self.sp_yr_min, self.sp_yr_max):
                w.setEnabled(False)
                w.setToolTip("Right Y-axis only applies to Cartesian plots.")

        # Initial values
        self.cb_x_auto.setChecked(bool(st.get("x_auto", True)))
        self.sp_x_min.setValue(float(st.get("x_min", 0.0)))
        self.sp_x_max.setValue(float(st.get("x_max", 6e9)))
        self.cb_yl_auto.setChecked(bool(st.get("yl_auto", True)))
        self.sp_yl_min.setValue(float(st.get("yl_min", -50.0)))
        self.sp_yl_max.setValue(float(st.get("yl_max", 5.0)))
        self.cb_yr_auto.setChecked(bool(st.get("yr_auto", True)))
        self.sp_yr_min.setValue(float(st.get("yr_min", 1.0)))
        self.sp_yr_max.setValue(float(st.get("yr_max", 10.0)))
        # apply enable state
        for cb, mn, mx in [(self.cb_x_auto, self.sp_x_min, self.sp_x_max),
                           (self.cb_yl_auto, self.sp_yl_min, self.sp_yl_max),
                           (self.cb_yr_auto, self.sp_yr_min, self.sp_yr_max)]:
            mn.setEnabled(not cb.isChecked()); mx.setEnabled(not cb.isChecked())
        return gb

    def _make_row(self) -> TraceRowWidget:
        row = TraceRowWidget(self.traces, self._available, plot_kind=self.kind)
        row.removed.connect(self._remove_row)
        row.changed.connect(self._validate)
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self._rows.append(row)
        self._validate()
        return row

    def _validate(self) -> None:
        if not hasattr(self, "lbl_warning"):
            return
        msg = _validate_assignments(self.kind,
                                    [r.to_assignment() for r in self._rows])
        self.lbl_warning.setText(msg)
        self.lbl_warning.setVisible(bool(msg))

    def _add_default_row(self) -> None:
        if not self._available:
            return
        row = self._make_row()
        row.cb_trace.setCurrentIndex(0)

    def _remove_row(self, row: TraceRowWidget) -> None:
        if row in self._rows:
            self._rows.remove(row)
            row.setParent(None); row.deleteLater()

    def result_payload(self) -> dict:
        return {
            "title": self.le_title.text().strip(),
            "assignments": [r.to_assignment() for r in self._rows],
            "x_auto": self.cb_x_auto.isChecked(),
            "x_min": float(self.sp_x_min.value()), "x_max": float(self.sp_x_max.value()),
            "yl_auto": self.cb_yl_auto.isChecked(),
            "yl_min": float(self.sp_yl_min.value()), "yl_max": float(self.sp_yl_max.value()),
            "yr_auto": self.cb_yr_auto.isChecked(),
            "yr_min": float(self.sp_yr_min.value()), "yr_max": float(self.sp_yr_max.value()),
        }

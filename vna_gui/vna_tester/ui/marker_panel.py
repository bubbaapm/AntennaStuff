"""
Marker panel — tabular readouts plus add/remove buttons.

Markers update automatically whenever the underlying trace data changes.
"""
from __future__ import annotations
from typing import List, Optional, Tuple

import numpy as np

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QColorDialog, QComboBox, QDoubleSpinBox, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu,
    QMessageBox, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..units import parse_frequency, format_freq_input


def _shrinkable_combo(c: QComboBox, min_chars: int = 5) -> None:
    """Force a combo box to shrink to ~min_chars width regardless of items."""
    c.setMinimumContentsLength(min_chars)
    c.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    c.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

from ..markers import Marker, MarkerKind, MARKER_STYLES, MARKER_KIND_LABELS
from ..metrics import format_freq, format_z
from ..trace import TraceManager, VNA_PARAMS


MARKER_COLORS = ["#ff6b9d", "#73c4ff", "#ffd34d", "#a0f8a0", "#ff9c40", "#c896ff"]


class MarkerPanel(QGroupBox):
    """
    Holds a list of Marker objects and a QTableWidget showing their values.
    Re-evaluates markers on demand.
    """

    markers_changed = pyqtSignal(list)               # current markers
    add_normal_at_freq = pyqtSignal(str, float, str) # inbound: trace, freq, panel_id
    marker_drag = pyqtSignal(str, float)             # inbound: label, new freq_hz
    target_db_changed = pyqtSignal(float)            # outbound: new target value

    def __init__(self, traces: TraceManager, parent=None):
        super().__init__("Markers", parent)
        self.traces = traces
        self._markers: List[Marker] = []
        self._z0 = 50.0
        self._target_db = -10.0
        self._build()

        # Debounce: trace data updates fire fast; we evaluate markers and
        # repopulate the table at most ~12×/sec, regardless of poll rate.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._refresh_values)

        traces.traces_changed.connect(self._refresh_set)
        traces.traces_data.connect(self._timer.start)

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 12, 8, 8)
        v.setSpacing(4)

        # Add row 1: kind + trace
        row1 = QHBoxLayout()
        self.cb_kind = QComboBox()
        self.cb_kind.addItem("Normal", MarkerKind.NORMAL.value)
        self.cb_kind.addItem("Max", MarkerKind.PEAK.value)
        self.cb_kind.addItem("Min", MarkerKind.MIN.value)
        self.cb_kind.addItem("Target", MarkerKind.TARGET.value)
        self.cb_kind.addItem("BW box", MarkerKind.BW_M10DB.value)
        _shrinkable_combo(self.cb_kind, min_chars=6)
        self.cb_kind.setToolTip(
            "Marker kinds:\n"
            " • Normal — fixed at the entered frequency (draggable on plots).\n"
            " • Peak — tracks the trace maximum each sweep.\n"
            " • Min — tracks the trace minimum (resonance dip).\n"
            " • Target — places at the first crossing of the target dB.\n"
            " • BW box — bandwidth band at the target dB. When you type a\n"
            "    frequency before adding it, the marker locks to the\n"
            "    resonance nearest that frequency — add one per resonance\n"
            "    on a multi-band antenna."
        )
        row1.addWidget(self.cb_kind, 1)
        self.cb_trace = QComboBox()
        self.cb_trace.setToolTip("Which trace this marker reads from.")
        _shrinkable_combo(self.cb_trace, min_chars=4)
        row1.addWidget(self.cb_trace, 1)
        v.addLayout(row1)

        # Add row 2: freq + style + add
        row2 = QHBoxLayout()
        # QLineEdit (not QDoubleSpinBox) so users can type "2.4G", "915M",
        # "1.575 GHz", "2400" (assumed MHz), etc.
        self.sp_freq = QLineEdit("2.4 GHz")
        self.sp_freq.setToolTip(
            "Marker frequency. Free-form input — try:\n"
            "  2.4G        → 2.4 GHz\n"
            "  915M / 915MHz / 915 MHz → 915 MHz\n"
            "  100k        → 100 kHz\n"
            "  2400        → 2400 MHz (bare numbers default to MHz)\n"
            "  1.575 GHz   → 1.575 GHz"
        )
        self.sp_freq.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Preferred)
        row2.addWidget(self.sp_freq, 1)
        self.cb_style = QComboBox()
        for s in MARKER_STYLES:
            self.cb_style.addItem(s)
        self.cb_style.setCurrentText("both")
        self.cb_style.setToolTip(
            "Visual style: line (vertical), point (dot on trace), or both."
        )
        _shrinkable_combo(self.cb_style, min_chars=4)
        row2.addWidget(self.cb_style)
        self.btn_add = QPushButton("+ Add")
        self.btn_add.setToolTip("Add a marker with the settings above.")
        self.btn_add.clicked.connect(self._on_add_clicked)
        row2.addWidget(self.btn_add)
        v.addLayout(row2)

        # Target dB row — used by Target marker AND by the metrics verdict
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Target:"))
        self.sp_target = QDoubleSpinBox()
        self.sp_target.setRange(-80.0, 0.0); self.sp_target.setSingleStep(0.5)
        self.sp_target.setValue(-10.0); self.sp_target.setSuffix(" dB")
        self.sp_target.setToolTip(
            "Target dB threshold used by Target / -10 dB BW markers.\n"
            "Also drives the antenna verdict in the metrics panel."
        )
        self.sp_target.valueChanged.connect(self._on_target_changed)
        row3.addWidget(self.sp_target, 1)
        v.addLayout(row3)

        # Quick-add convenience buttons
        quick = QHBoxLayout()
        for label, kind, tip in [
            ("Max",  MarkerKind.PEAK, "Auto-max marker on the selected trace."),
            ("Min",  MarkerKind.MIN,  "Auto-min (resonance) marker on the selected trace."),
            ("BW",   MarkerKind.BW_M10DB,
             "Bandwidth-box marker at the target dB band on the selected trace."),
        ]:
            b = QPushButton(label)
            b.setStyleSheet("QPushButton { padding: 4px 6px; }")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=kind: self._quick_add(k))
            quick.addWidget(b)
        v.addLayout(quick)

        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(
            ["Label", "Trace", "f", "dB", "VSWR", "Z (Ω)", "Δf"]
        )
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        # Sensible default widths so nothing forces the panel to overflow.
        for col, w in enumerate([46, 46, 78, 44, 44, 70, 60]):
            self.tbl.setColumnWidth(col, w)
        # Grow the table to fit its rows (like the Live / References lists),
        # not greedily fill all remaining space. _fit_table_to_contents below
        # sets a fixed height after each repopulation.
        self.tbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        # Allow editing only the f column (col 2), via double-click.
        # Per-item flags (set in _populate_table) gate which cells are
        # actually editable — the trigger just opens the editor on
        # cells that already have the editable flag.
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked
                                 | QTableWidget.EditTrigger.EditKeyPressed)
        self.tbl.itemChanged.connect(self._on_table_item_changed)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tbl.setToolTip(
            "Marker readouts. Right-click a row for color/scope/kind/remove.\n"
            "Markers update on every sweep."
        )
        self.tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._on_table_context)
        v.addWidget(self.tbl, 1)

        btns = QHBoxLayout()
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setStyleSheet("QPushButton { padding: 4px 6px; }")
        self.btn_remove.setToolTip("Delete the highlighted marker.")
        self.btn_remove.clicked.connect(self._on_remove_clicked)
        btns.addWidget(self.btn_remove)
        self.btn_clear = QPushButton("Clear all")
        self.btn_clear.setStyleSheet("QPushButton { padding: 4px 6px; }")
        self.btn_clear.setToolTip("Delete every marker.")
        self.btn_clear.clicked.connect(self.clear)
        btns.addWidget(self.btn_clear)
        v.addLayout(btns)

        self.add_normal_at_freq.connect(self._add_normal_external)
        self.marker_drag.connect(self._on_marker_dragged_in)

    # ------------------------------------------------------------- API
    def markers(self) -> List[Marker]:
        return list(self._markers)

    def set_z0(self, z0: float) -> None:
        self._z0 = float(z0)
        self._refresh()

    def add_marker(self, m: Marker) -> None:
        self._markers.append(m)
        self._refresh()

    def clear(self) -> None:
        self._markers.clear()
        self._refresh()

    def _refresh(self) -> None:
        """Full refresh: combo box, marker eval, table. Used on user actions."""
        self._refresh_trace_combo()
        self._refresh_values()

    def _refresh_set(self) -> None:
        """Trace SET changed — combo needs to reflect new names."""
        self._refresh_trace_combo()
        self._timer.start()

    # --------------------------------------------------------- handlers
    def _refresh_trace_combo(self) -> None:
        self.cb_trace.blockSignals(True)
        prev = self.cb_trace.currentText()
        self.cb_trace.clear()
        names = [t.name for t in self.traces.all()]
        self.cb_trace.addItems(names)
        if prev in names:
            self.cb_trace.setCurrentText(prev)
        self.cb_trace.blockSignals(False)

    def _refresh_values(self) -> None:
        """Evaluate markers, repopulate table, notify plots."""
        for i, m in enumerate(self._markers):
            tr = self.traces.get(m.trace_name)
            if tr is None:
                continue
            if not m.color or m.color == "#ffffff":
                m.color = MARKER_COLORS[i % len(MARKER_COLORS)]
            m.evaluate(tr, z0=self._z0)
            # Compute readouts at the resolved primary freq for each
            # extra trace the user attached. We snap to the closest sample
            # (same convention the primary uses).
            m.extra_readings.clear()
            for ex_name in list(m.extra_traces):
                tx = self.traces.get(ex_name)
                if tx is None or tx.freq.size == 0 or ex_name == m.trace_name:
                    continue
                idx = int(np.argmin(np.abs(tx.freq - m.freq_hz)))
                s = tx.s[idx]
                mag = max(abs(s), 1e-12)
                clipped = min(mag, 0.999_999)
                if abs(1.0 - s) > 1e-9:
                    z = self._z0 * (1.0 + s) / (1.0 - s)
                else:
                    z = complex(float("inf"), 0.0)
                m.extra_readings[ex_name] = {
                    "db": 20.0 * np.log10(mag),
                    "vswr": (1.0 + clipped) / (1.0 - clipped),
                    "z": z,
                }
        self._populate_table()
        self.markers_changed.emit(list(self._markers))

    def _populate_table(self) -> None:
        # Block itemChanged while we rewrite cells, otherwise our own
        # repopulation looks like a user edit.
        self.tbl.blockSignals(True)
        try:
            # Flatten markers + their extra-trace rows into a single row
            # list. Each row's column-0 UserRole carries (label, is_primary,
            # extra_name) so the context-menu / edit / remove handlers can
            # map row → marker without keeping a parallel list.
            rows: List[Tuple["Marker", bool, str]] = []
            for m in self._markers:
                rows.append((m, True, ""))
                for ex in m.extra_traces:
                    if ex == m.trace_name:
                        continue
                    if ex not in m.extra_readings:
                        # Skip extras that didn't resolve (trace removed
                        # under us etc.) — refresh_values cleared the cache.
                        continue
                    rows.append((m, False, ex))
            self.tbl.setRowCount(len(rows))

            non_editable = (Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsEnabled)
            editable = non_editable | Qt.ItemFlag.ItemIsEditable
            prev_freq: Optional[float] = None

            for r, (m, is_primary, ex_name) in enumerate(rows):
                scope_suffix = " *" if m.scope == "panel" else ""
                if is_primary:
                    label_text = m.label + scope_suffix
                    trace_text = m.trace_name
                    if m.kind == MarkerKind.BW_M10DB:
                        f_text = (f"{format_freq(m.freq_hz)}–{format_freq(m.secondary_freq_hz)} "
                                  f"(Δ {format_freq(m.bandwidth_hz())})")
                        f_flags = non_editable
                    else:
                        f_text = format_freq_input(m.freq_hz)
                        f_flags = (editable if m.kind == MarkerKind.NORMAL
                                   else non_editable)
                    db_val = m.last_db
                    vswr_val = m.last_vswr
                    z_val = m.last_z
                    df_text = (format_freq(abs(m.freq_hz - prev_freq))
                               if prev_freq is not None and m.kind != MarkerKind.BW_M10DB
                               else "")
                    text_color = QColor(m.color)
                else:
                    rd = m.extra_readings.get(ex_name, {})
                    label_text = "  ↳"
                    trace_text = ex_name
                    f_text = ""
                    f_flags = non_editable
                    db_val = float(rd.get("db", 0.0))
                    vswr_val = float(rd.get("vswr", 1.0))
                    z_val = rd.get("z", 0+0j)
                    df_text = ""
                    # Extra rows take the trace's color so it's clear which
                    # value belongs to which trace.
                    tref = self.traces.get(ex_name)
                    text_color = QColor(tref.color) if tref is not None else QColor("#888")

                cells = [
                    (label_text, non_editable),
                    (trace_text, non_editable),
                    (f_text, f_flags),
                    (f"{db_val:.2f}", non_editable),
                    (f"{vswr_val:.2f}", non_editable),
                    (format_z(z_val), non_editable),
                    (df_text, non_editable),
                ]
                for col, (text, flags) in enumerate(cells):
                    item = QTableWidgetItem(text)
                    item.setFlags(flags)
                    if col == 0:
                        item.setForeground(text_color)
                        if is_primary:
                            item.setToolTip(
                                f"{m.label} — kind={m.kind.value}, scope={m.scope}\n"
                                f"Right-click row for color / scope / type / extras / remove."
                            )
                        else:
                            item.setToolTip(
                                f"Extra readout: {ex_name} at "
                                f"{format_freq_input(m.freq_hz)}.\n"
                                f"Manage via right-click on the marker's primary row."
                            )
                        # Stash row → marker identity here so handlers can
                        # find the owning marker without a parallel list.
                        item.setData(Qt.ItemDataRole.UserRole,
                                     (m.label, is_primary, ex_name))
                    if col == 2 and is_primary and m.kind == MarkerKind.NORMAL:
                        item.setToolTip(
                            "Double-click to type a new frequency.\n"
                            "Accepts 2.4G, 915M, 1.575 GHz, 2400 (= MHz)…"
                        )
                    self.tbl.setItem(r, col, item)
                if is_primary:
                    prev_freq = m.freq_hz
        finally:
            self.tbl.blockSignals(False)
        self._fit_table_to_contents()

    def _row_owner(self, row: int) -> Optional[Tuple[str, bool, str]]:
        """Return (marker_label, is_primary, extra_trace_name) for a row,
        or None if the row isn't ours."""
        if row < 0:
            return None
        item = self.tbl.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple) or len(data) != 3:
            return None
        return data

    def _marker_by_label(self, label: str) -> Optional["Marker"]:
        return next((m for m in self._markers if m.label == label), None)

    def _fit_table_to_contents(self) -> None:
        """Size the marker table to exactly the rows it holds, with a small
        floor so the empty state still shows the column headers."""
        rows = self.tbl.rowCount()
        row_h = self.tbl.verticalHeader().defaultSectionSize()
        if row_h <= 0:
            row_h = self.tbl.fontMetrics().height() + 6
        header_h = self.tbl.horizontalHeader().height()
        # 1 row of slack when empty so the "no markers yet" state isn't a
        # 1-pixel strip; otherwise just header + rows.
        visible_rows = max(1, rows)
        h = header_h + visible_rows * row_h + 2 * self.tbl.frameWidth() + 4
        self.tbl.setFixedHeight(h)

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        """User committed a typed-in frequency — parse it & update the marker."""
        try:
            col = item.column()
        except RuntimeError:
            # Item already deleted (e.g. handler re-entered after refresh).
            return
        if col != 2:
            return
        owner = self._row_owner(item.row())
        if owner is None or not owner[1]:
            return  # extras can't be edited from here
        m = self._marker_by_label(owner[0])
        if m is None or m.kind != MarkerKind.NORMAL:
            return
        new_hz = parse_frequency(item.text(), default_unit_hz=1e6)
        if new_hz is None:
            QMessageBox.warning(
                self, "Bad frequency",
                f"Couldn't parse '{item.text()}'. Use forms like 2.4G, 915M, "
                "1.575 GHz, or a bare number (taken as MHz)."
            )
            # Repopulate restores the prior text.
            self._refresh_values()
            return
        m.freq_hz = new_hz
        self._refresh_values()

    def _on_add_clicked(self) -> None:
        kind = MarkerKind(self.cb_kind.currentData())
        trace = self.cb_trace.currentText().strip() or "S11"
        f = parse_frequency(self.sp_freq.text(), default_unit_hz=1e6)
        if f is None:
            QMessageBox.warning(self, "Bad frequency",
                                f"Couldn't parse '{self.sp_freq.text()}'.\n"
                                "Try forms like 2.4G, 915M, 1.575 GHz, 2400.")
            return
        idx = len(self._markers) + 1
        label = self._unique_label({
            MarkerKind.NORMAL: f"M{idx}",
            MarkerKind.PEAK: "Max",
            MarkerKind.MIN: "Min",
            MarkerKind.TARGET: "Tgt",
            MarkerKind.BW_M10DB: "BW",
        }[kind])
        color = MARKER_COLORS[(idx - 1) % len(MARKER_COLORS)]
        style = self.cb_style.currentText()
        # For BW markers the typed freq anchors the resonance search — that's
        # how the user gets one BW marker per resonance instead of all of
        # them collapsing to the same global minimum.
        anchor = f if kind == MarkerKind.BW_M10DB else 0.0
        self._markers.append(Marker(label=label, kind=kind, trace_name=trace,
                                    freq_hz=f, color=color,
                                    target_db=self._target_db,
                                    style=style, anchor_freq_hz=anchor))
        self._refresh()

    def _unique_label(self, base: str) -> str:
        existing = {m.label for m in self._markers}
        if base not in existing:
            return base
        i = 2
        while f"{base}{i}" in existing:
            i += 1
        return f"{base}{i}"

    def _quick_add(self, kind: MarkerKind) -> None:
        # Use the trace currently selected in the combo, NOT a hardcoded "S11".
        target = self.cb_trace.currentText().strip()
        if not target or self.traces.get(target) is None:
            # fallback: any available trace
            names = self.traces.names()
            target = names[0] if names else ""
        if not target:
            return
        idx = len(self._markers) + 1
        base = {
            MarkerKind.PEAK: "Max",
            MarkerKind.MIN: "Min",
            MarkerKind.BW_M10DB: "BW",
        }.get(kind, f"M{idx}")
        label = self._unique_label(base)
        color = MARKER_COLORS[(idx - 1) % len(MARKER_COLORS)]
        style = self.cb_style.currentText()
        self._markers.append(Marker(label=label, kind=kind, trace_name=target,
                                    freq_hz=0.0, color=color, target_db=self._target_db,
                                    style=style))
        self._refresh()

    def _on_remove_clicked(self) -> None:
        # Selecting an extra row should still remove the owning marker —
        # extras are part of one logical marker, not their own entities.
        labels: set = set()
        for it in self.tbl.selectedItems():
            owner = self._row_owner(it.row())
            if owner is not None:
                labels.add(owner[0])
        if not labels:
            return
        self._markers = [m for m in self._markers if m.label not in labels]
        self._refresh()

    def _add_normal_external(self, trace_name: str, freq_hz: float,
                              panel_id: str = "") -> None:
        """
        Called when the user click-places a marker on a plot. The marker is
        scoped to the panel that emitted it — clicking on one plot should
        NOT drop a marker on the others. Use the marker's right-click menu
        to broaden scope to "all plots".
        """
        idx = len(self._markers) + 1
        color = MARKER_COLORS[(idx - 1) % len(MARKER_COLORS)]
        style = self.cb_style.currentText()
        label = self._unique_label(f"M{idx}")
        scope = "panel" if panel_id else "all"
        self._markers.append(Marker(
            label=label, kind=MarkerKind.NORMAL,
            trace_name=trace_name, freq_hz=freq_hz,
            color=color, style=style,
            scope=scope, panel_id=panel_id or "",
        ))
        self._refresh()

    def _on_marker_dragged_in(self, label: str, freq_hz: float) -> None:
        for m in self._markers:
            if m.label == label and m.kind == MarkerKind.NORMAL:
                m.freq_hz = float(freq_hz)
                break
        self._refresh()

    # ----------------------------------------------------------- target dB
    def target_db(self) -> float:
        return self._target_db

    def _on_target_changed(self, v: float) -> None:
        self._target_db = float(v)
        for m in self._markers:
            m.target_db = self._target_db
        self.target_db_changed.emit(self._target_db)
        self._refresh()

    # ------------------------------------------------------- context menus
    def _on_table_context(self, pos) -> None:
        owner = self._row_owner(self.tbl.indexAt(pos).row())
        if owner is None:
            return
        screen = self.tbl.viewport().mapToGlobal(pos)
        # Right-clicking either a primary or an extra row opens the
        # owning marker's menu — the user should manage the marker as
        # a whole even from one of its extras.
        self.show_marker_menu(owner[0], screen)

    def show_marker_menu(self, label: str, screen_pos, panel_id: str = "") -> None:
        """
        Open the marker-options context menu at `screen_pos`.

        Called from the marker table (no panel_id) and from a plot panel's
        right-click handler (with the panel's plot_id, so 'show on this
        plot only' has the right target).
        """
        m = next((x for x in self._markers if x.label == label), None)
        if m is None:
            return

        menu = QMenu(self)

        # ------ kind submenu
        kind_menu = menu.addMenu(f"Type — {MARKER_KIND_LABELS.get(m.kind, m.kind.value)}")
        for k in MarkerKind:
            act = kind_menu.addAction(MARKER_KIND_LABELS.get(k, k.value))
            act.setCheckable(True); act.setChecked(m.kind == k)
            act.triggered.connect(lambda _=False, kk=k, mk=m: self._set_kind(mk, kk))

        # ------ style submenu
        style_menu = menu.addMenu(f"Style ({m.style})")
        for s in MARKER_STYLES:
            act = style_menu.addAction(s)
            act.setCheckable(True); act.setChecked(m.style == s)
            act.triggered.connect(lambda _=False, ss=s, mk=m: self._set_style(mk, ss))

        # ------ scope
        scope_menu = menu.addMenu(f"Show on ({'all plots' if m.scope == 'all' else 'this plot only'})")
        a_all = scope_menu.addAction("All plots")
        a_all.setCheckable(True); a_all.setChecked(m.scope == "all")
        a_all.triggered.connect(lambda: self._set_scope(m, "all", ""))
        a_one = scope_menu.addAction("This plot only")
        a_one.setEnabled(bool(panel_id))
        a_one.setCheckable(True)
        a_one.setChecked(m.scope == "panel" and m.panel_id == panel_id)
        a_one.triggered.connect(lambda: self._set_scope(m, "panel", panel_id))

        # ------ trace submenu (the marker's primary trace)
        trace_menu = menu.addMenu(f"Trace ({m.trace_name})")
        for n in self.traces.names():
            act = trace_menu.addAction(n)
            act.setCheckable(True); act.setChecked(n == m.trace_name)
            act.triggered.connect(lambda _=False, nn=n, mk=m: self._set_trace(mk, nn))

        # ------ extras submenu — additional traces this marker should
        #        also read out + drop a dot on at the same frequency.
        n_extra = len(m.extra_traces)
        extras_menu = menu.addMenu(
            f"Also dot/read on traces"
            + (f" ({n_extra})" if n_extra else "")
        )
        names = [n for n in self.traces.names() if n != m.trace_name]
        if not names:
            none_act = extras_menu.addAction("(no other traces)")
            none_act.setEnabled(False)
        else:
            for n in names:
                act = extras_menu.addAction(n)
                act.setCheckable(True)
                act.setChecked(n in m.extra_traces)
                act.triggered.connect(
                    lambda checked, nn=n, mk=m: self._toggle_extra(mk, nn, checked)
                )

        # ------ value-on-dot toggle
        a_vals = menu.addAction("Show values on dots")
        a_vals.setCheckable(True)
        a_vals.setChecked(m.show_dot_values)
        a_vals.triggered.connect(
            lambda checked, mk=m: self._toggle_dot_values(mk, checked)
        )

        menu.addSeparator()

        # "Set frequency…" works for any marker that holds a user-set freq:
        # NORMAL is always editable; BW honors `anchor_freq_hz` so the user
        # can re-anchor an existing BW marker on a different resonance.
        if m.kind in (MarkerKind.NORMAL, MarkerKind.BW_M10DB):
            label_freq = ("Set anchor frequency…"
                          if m.kind == MarkerKind.BW_M10DB
                          else "Set frequency…")
            a_freq = menu.addAction(label_freq)
            a_freq.triggered.connect(lambda: self._edit_freq(m))

        a_color = menu.addAction("Change color…")
        a_color.triggered.connect(lambda: self._pick_color(m))

        a_label = menu.addAction("Rename…")
        a_label.triggered.connect(lambda: self._rename(m))

        menu.addSeparator()

        a_remove = menu.addAction("Remove marker")
        a_remove.triggered.connect(lambda: self._remove_marker(m))

        menu.exec(screen_pos)

    def _set_kind(self, m: Marker, k: MarkerKind) -> None:
        m.kind = k; self._refresh()

    def _set_style(self, m: Marker, s: str) -> None:
        m.style = s; self._refresh()

    def _set_scope(self, m: Marker, scope: str, panel_id: str) -> None:
        m.scope = scope
        m.panel_id = panel_id if scope == "panel" else ""
        self._refresh()

    def _set_trace(self, m: Marker, n: str) -> None:
        # Promoting a trace to primary should remove it from extras so we
        # don't end up with a duplicate dot/row for the same trace.
        if n in m.extra_traces:
            m.extra_traces = [t for t in m.extra_traces if t != n]
        m.trace_name = n
        self._refresh()

    def _toggle_extra(self, m: Marker, name: str, checked: bool) -> None:
        if checked:
            if name not in m.extra_traces and name != m.trace_name:
                m.extra_traces.append(name)
        else:
            m.extra_traces = [t for t in m.extra_traces if t != name]
        self._refresh()

    def _toggle_dot_values(self, m: Marker, checked: bool) -> None:
        m.show_dot_values = bool(checked)
        self._refresh()

    def _pick_color(self, m: Marker) -> None:
        c = QColorDialog.getColor(QColor(m.color), self, "Marker color")
        if c.isValid():
            m.color = c.name()
            self._refresh()

    def _edit_freq(self, m: Marker) -> None:
        # The freq we offer to edit depends on the marker kind: BW markers
        # carry their resonance anchor separately from `freq_hz` (which the
        # evaluator overwrites with the band's left edge each sweep).
        is_bw = m.kind == MarkerKind.BW_M10DB
        current_hz = (m.anchor_freq_hz if is_bw else m.freq_hz) or m.freq_hz
        prompt = ("New anchor frequency (locks BW to the resonance near it):"
                  if is_bw else "New frequency:")
        new, ok = QInputDialog.getText(
            self, "Marker frequency", prompt,
            text=format_freq_input(current_hz),
        )
        if not ok:
            return
        new_hz = parse_frequency(new, default_unit_hz=1e6)
        if new_hz is None:
            QMessageBox.warning(
                self, "Bad frequency",
                f"Couldn't parse '{new}'. Use forms like 2.4G, 915M, "
                "1.575 GHz, or a bare number (taken as MHz)."
            )
            return
        if is_bw:
            m.anchor_freq_hz = new_hz
        else:
            m.freq_hz = new_hz
        self._refresh()

    def _rename(self, m: Marker) -> None:
        new, ok = QInputDialog.getText(self, "Rename marker", "Label:", text=m.label)
        if ok and new.strip():
            m.label = self._unique_label(new.strip())
            self._refresh()

    def _remove_marker(self, m: Marker) -> None:
        if m in self._markers:
            self._markers.remove(m)
            self._refresh()

"""
Trace list panel — shows live and reference traces, with visibility toggles
and a button to load reference S2P files.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from ..paths import app_root
from ..trace import Trace, TraceManager, VNA_PARAMS


def _read_touchstone(path: str) -> List[Tuple[str, np.ndarray, np.ndarray]]:
    """
    Minimal Touchstone (.s1p / .s2p) parser. Returns list of
    (parameter_name, freq[N], complex_S[N]) tuples — one per S-parameter
    column (e.g. S11, S21, S12, S22 for a .s2p file).
    """
    p = Path(path)
    text = p.read_text(errors="replace")
    lines = text.splitlines()
    f_unit_mult = 1e9
    fmt = "MA"
    z0 = 50.0
    data_rows: List[List[float]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            toks = line.split()
            for t in toks[1:]:
                tu = t.upper()
                if tu in ("HZ", "KHZ", "MHZ", "GHZ"):
                    f_unit_mult = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}[tu]
                elif tu in ("MA", "DB", "RI"):
                    fmt = tu
                elif tu == "R":
                    pass  # next token is z0
                else:
                    try:
                        z0 = float(t)
                    except ValueError:
                        pass
            continue
        # tolerate inline comments
        if "!" in line:
            line = line.split("!", 1)[0]
        nums = [float(x) for x in line.replace(",", " ").split() if x.strip()]
        if not nums:
            continue
        data_rows.append(nums)

    if not data_rows:
        return []

    suffix = p.suffix.lower()
    n_ports = 1 if suffix == ".s1p" else 2 if suffix == ".s2p" else 1
    cols_per = 2 * (n_ports * n_ports)  # each S-param contributes (a, b)
    arr = np.asarray(data_rows, dtype=float)
    freq = arr[:, 0] * f_unit_mult
    pairs = arr[:, 1: 1 + cols_per].reshape(arr.shape[0], n_ports * n_ports, 2)

    def to_complex(ab: np.ndarray) -> np.ndarray:
        a, b = ab[:, 0], ab[:, 1]
        if fmt == "MA":
            return a * np.exp(1j * np.deg2rad(b))
        if fmt == "DB":
            return (10.0 ** (a / 20.0)) * np.exp(1j * np.deg2rad(b))
        # RI
        return a + 1j * b

    if n_ports == 1:
        return [("S11", freq, to_complex(pairs[:, 0, :]))]
    # .s2p column order in touchstone is S11, S21, S12, S22
    names = ["S11", "S21", "S12", "S22"]
    return [(names[i], freq, to_complex(pairs[:, i, :])) for i in range(4)]


def _color_swatch(hex_color: str, size: int = 14) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(QColor(hex_color))
    return QIcon(pix)


def _fit_list_to_contents(lst: QListWidget, min_rows: int = 1) -> None:
    """Resize a QListWidget so it's exactly tall enough for its rows."""
    rows = lst.count()
    row_h = lst.sizeHintForRow(0)
    if row_h <= 0:
        # Fallback before any item has been laid out.
        row_h = lst.fontMetrics().height() + 6
    visible_rows = max(min_rows, rows)
    h = visible_rows * row_h + 2 * lst.frameWidth() + 4
    lst.setFixedHeight(h)


class TracePanel(QGroupBox):
    """
    Lists every trace held by the TraceManager. Live traces are shown at
    the top; references are shown below.

    Emits no signals — uses the manager directly via toggle/remove.
    """

    save_s2p_requested = pyqtSignal()
    save_s1p_requested = pyqtSignal()
    references_loaded = pyqtSignal(list)   # list[str] — newly added trace names
    references_cleared = pyqtSignal(list)  # list[str] — names of refs just removed

    def __init__(self, traces: TraceManager, parent=None):
        super().__init__("Traces", parent)
        self.traces = traces
        self._build()
        # Trace list only needs to refresh when the SET changes
        # (added/removed/visibility/color). Data updates don't matter here.
        traces.traces_changed.connect(self._refresh)
        self._refresh()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 12, 8, 8)
        v.setSpacing(4)

        lbl_live = QLabel("Live:")
        lbl_live.setToolTip("Traces measured live from the VNA on every sweep.")
        v.addWidget(lbl_live)
        self.lst_live = QListWidget()
        self.lst_live.setToolTip(
            "Click to toggle visibility. Right-click for color.\n"
            "Live traces auto-update on every sweep."
        )
        # Size-to-content rather than greedy expansion — _fit_list_to_contents
        # below sets a fixed height after each refresh.
        self.lst_live.setSizePolicy(QSizePolicy.Policy.Preferred,
                                    QSizePolicy.Policy.Fixed)
        self.lst_live.itemChanged.connect(self._on_item_changed)
        self.lst_live.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lst_live.customContextMenuRequested.connect(self._ctx_menu_live)
        v.addWidget(self.lst_live)

        lbl_ref = QLabel("References:")
        lbl_ref.setToolTip("Reference traces loaded from .s2p / .s1p files.")
        v.addWidget(lbl_ref)
        self.lst_ref = QListWidget()
        self.lst_ref.setToolTip(
            "Reference traces are drawn dashed.\n"
            "Right-click to remove or recolor."
        )
        self.lst_ref.setSizePolicy(QSizePolicy.Policy.Preferred,
                                   QSizePolicy.Policy.Fixed)
        self.lst_ref.itemChanged.connect(self._on_item_changed)
        self.lst_ref.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lst_ref.customContextMenuRequested.connect(self._ctx_menu_ref)
        v.addWidget(self.lst_ref)

        # Two compact rows of buttons so nothing overflows.
        compact_btn_qss = "QPushButton { padding: 4px 6px; }"
        row_a = QHBoxLayout()
        self.btn_load_ref = QPushButton("Load Touchstone…")
        self.btn_load_ref.setStyleSheet(compact_btn_qss)
        self.btn_load_ref.setToolTip(
            "Import a Touchstone file (.s1p or .s2p) as a static overlay.\n"
            "Defaults to the project's s1p_s2p_files folder so saved measurements\n"
            "are one click away. References are drawn alongside live traces —\n"
            "handy for comparing the current sweep against a saved measurement\n"
            "or a known-good reference board. They never update on their own."
        )
        self.btn_load_ref.clicked.connect(self._load_reference)
        row_a.addWidget(self.btn_load_ref)
        self.btn_clear_ref = QPushButton("Clear refs")
        self.btn_clear_ref.setStyleSheet(compact_btn_qss)
        self.btn_clear_ref.setToolTip(
            "Remove all reference traces — and any plot overlays / markers\n"
            "attached to them. Asks for confirmation first."
        )
        self.btn_clear_ref.clicked.connect(self._clear_refs_with_confirm)
        row_a.addWidget(self.btn_clear_ref)
        v.addLayout(row_a)

        row_b = QHBoxLayout()
        self.btn_save_s1p = QPushButton("Save .s1p…")
        self.btn_save_s1p.setStyleSheet(compact_btn_qss)
        self.btn_save_s1p.setToolTip(
            "Export S₁₁ only as a 1-port Touchstone (.s1p) — usual for antennas."
        )
        self.btn_save_s1p.clicked.connect(lambda: self.save_s1p_requested.emit())
        row_b.addWidget(self.btn_save_s1p)
        self.btn_save_s2p = QPushButton("Save .s2p…")
        self.btn_save_s2p.setStyleSheet(compact_btn_qss)
        self.btn_save_s2p.setToolTip(
            "Export the full S₁₁/S₂₁/S₁₂/S₂₂ sweep as a 2-port Touchstone."
        )
        self.btn_save_s2p.clicked.connect(self.save_s2p_requested.emit)
        row_b.addWidget(self.btn_save_s2p)
        v.addLayout(row_b)

    # ------------------------------------------------------------- helpers
    def _refresh(self) -> None:
        self.lst_live.blockSignals(True)
        self.lst_ref.blockSignals(True)
        self.lst_live.clear()
        self.lst_ref.clear()
        for t in self.traces.live():
            it = QListWidgetItem(_color_swatch(t.color), t.name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if t.visible else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, t.name)
            self.lst_live.addItem(it)
        for t in self.traces.references():
            label = t.name + (f" — {t.parameter}" if t.parameter not in t.name else "")
            it = QListWidgetItem(_color_swatch(t.color), label)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if t.visible else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, t.name)
            self.lst_ref.addItem(it)
        self.lst_live.blockSignals(False)
        self.lst_ref.blockSignals(False)
        _fit_list_to_contents(self.lst_live, min_rows=1)
        _fit_list_to_contents(self.lst_ref, min_rows=1)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        self.traces.set_visible(name, item.checkState() == Qt.CheckState.Checked)

    def _ctx_menu_live(self, pos) -> None:
        it = self.lst_live.itemAt(pos)
        if it is None:
            return
        name = it.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        a_color = m.addAction("Change color…")
        a_color.triggered.connect(lambda: self._pick_color(name))
        m.exec(self.lst_live.mapToGlobal(pos))

    def _ctx_menu_ref(self, pos) -> None:
        it = self.lst_ref.itemAt(pos)
        if it is None:
            return
        name = it.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        a_color = m.addAction("Change color…")
        a_color.triggered.connect(lambda: self._pick_color(name))
        m.addSeparator()
        a_remove = m.addAction("Remove reference")
        a_remove.triggered.connect(lambda: self.traces.remove(name))
        m.exec(self.lst_ref.mapToGlobal(pos))

    def _pick_color(self, name: str) -> None:
        t = self.traces.get(name)
        if t is None:
            return
        c = QColorDialog.getColor(QColor(t.color), self, "Pick trace color")
        if c.isValid():
            self.traces.set_color(name, c.name())

    def _clear_refs_with_confirm(self) -> None:
        """Confirmation gate + cascade cleanup. Plots and markers attached
        to references are also removed (signaled to main window)."""
        refs = self.traces.references()
        if not refs:
            return
        n = len(refs)
        ans = QMessageBox.question(
            self, "Clear references",
            f"Remove all {n} reference trace{'s' if n != 1 else ''}?\n\n"
            "Reference plot lines, dots, and any markers attached to them "
            "will also be removed from every plot.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        names = [t.name for t in refs]
        self.traces.clear_references()
        # Tell the main window to prune assignments + markers that point
        # at these references — the trace manager only owns trace data.
        self.references_cleared.emit(names)

    def _default_touchstone_dir(self) -> str:
        """Folder the file dialog should open in — prefer the project's
        s1p_s2p_files folder so saved sweeps are one click away."""
        candidates = [
            app_root() / "s1p_s2p_files",   # vna_gui/s1p_s2p_files
            app_root().parent / "s1p_s2p_files",  # repo root
        ]
        for p in candidates:
            if p.exists() and p.is_dir():
                return str(p)
        # Create the canonical one so it exists for next time.
        try:
            target = app_root() / "s1p_s2p_files"
            target.mkdir(parents=True, exist_ok=True)
            return str(target)
        except OSError:
            return ""

    def _load_reference(self) -> None:
        # Multi-select: dropping a folder of antenna captures in at once is
        # the common case. Per-file errors don't abort the rest.
        fns, _ = QFileDialog.getOpenFileNames(
            self, "Load Touchstone reference(s)", self._default_touchstone_dir(),
            "Touchstone files (*.s1p *.s2p);;All files (*)"
        )
        if not fns:
            return
        added: List[str] = []
        failed: List[str] = []
        for fn in fns:
            try:
                entries = _read_touchstone(fn)
            except Exception as e:
                failed.append(f"{Path(fn).name}: {type(e).__name__}: {e}")
                continue
            if not entries:
                failed.append(f"{Path(fn).name}: no data parsed")
                continue
            base = Path(fn).stem
            for param, freq, s in entries:
                t = self.traces.add_reference(
                    name=f"{base}:{param}",
                    parameter=param,
                    freq=freq, s=s,
                    source_file=fn,
                )
                added.append(t.name)
        if added:
            self.references_loaded.emit(added)
        if failed:
            QMessageBox.warning(
                self, "Load failed",
                "Some files couldn't be loaded:\n  • " + "\n  • ".join(failed),
            )

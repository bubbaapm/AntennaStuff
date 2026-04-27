"""
Step-by-step calibration wizard.

Supports:
  • Port-1 SOL  (Open + Short + Load on port 1) — for S11 measurements
  • Port-2 SOL  (Open + Short + Load on port 2) — for S22 measurements
  • Through     (P1↔P2 thru) — for transmission
  • Full SOLT   (port1 SOL + port2 SOL + Through + isolation)

The dialog drives the device via the VnaController and a
CalMeasureWorker — the UI never blocks while the device measures.
After all steps complete the user can:
  • Activate the resulting cal type
  • Save to a .cal file
  • Apply and close
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from ..controller import VnaController
from ..worker import CalMeasureWorker


@dataclass
class CalStep:
    label: str          # "Open on Port 1"
    std_type: str       # OPEN/SHORT/LOAD/THROUGH/ISOLATION
    port: int           # 1 or 2; ignored for THROUGH/ISOLATION
    description: str    # tooltip help
    measurement_index: int = 0  # populated after VNA:CAL:ADD
    completed: bool = False


def make_steps(cal_type: str) -> List[CalStep]:
    if cal_type == "Port 1 (SOL)":
        return [
            CalStep("Open on Port 1",  "OPEN",  1, "Connect a calibration Open standard to Port 1."),
            CalStep("Short on Port 1", "SHORT", 1, "Connect a calibration Short standard to Port 1."),
            CalStep("Load on Port 1",  "LOAD",  1, "Connect a 50 Ω matched Load to Port 1."),
        ]
    if cal_type == "Port 2 (SOL)":
        return [
            CalStep("Open on Port 2",  "OPEN",  2, "Connect a calibration Open standard to Port 2."),
            CalStep("Short on Port 2", "SHORT", 2, "Connect a calibration Short standard to Port 2."),
            CalStep("Load on Port 2",  "LOAD",  2, "Connect a 50 Ω matched Load to Port 2."),
        ]
    if cal_type == "Through (P1↔P2)":
        return [
            CalStep("Through P1↔P2", "THROUGH", 0,
                    "Connect Port 1 directly to Port 2 with a known thru / barrel."),
        ]
    if cal_type == "Full SOLT":
        return [
            CalStep("Open on Port 1",  "OPEN",  1, "Connect Open on Port 1."),
            CalStep("Short on Port 1", "SHORT", 1, "Connect Short on Port 1."),
            CalStep("Load on Port 1",  "LOAD",  1, "Connect Load on Port 1."),
            CalStep("Open on Port 2",  "OPEN",  2, "Connect Open on Port 2."),
            CalStep("Short on Port 2", "SHORT", 2, "Connect Short on Port 2."),
            CalStep("Load on Port 2",  "LOAD",  2, "Connect Load on Port 2."),
            CalStep("Through P1↔P2",   "THROUGH", 0, "Direct P1 to P2."),
            CalStep("Isolation (loads on both)", "ISOLATION", 0,
                    "Optional: place Loads on BOTH ports to capture isolation."),
        ]
    return []


# Map our wizard label to the SCPI cal-type token for VNA:CAL:ACT
CAL_ACTIVATE_TOKEN = {
    "Port 1 (SOL)": "PORT1",
    "Port 2 (SOL)": "PORT2",
    "Through (P1↔P2)": "THROUGH",
    "Full SOLT": "SOLT",
}


class CalibrationDialog(QDialog):
    """Modal-ish wizard. Use exec() to run."""

    sweep_should_refresh = pyqtSignal()  # emitted after a cal load, so the
                                         # main window can pull the new range

    def __init__(self, controller: VnaController, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibration wizard")
        self.resize(560, 480)
        self.controller = controller
        self._steps: List[CalStep] = []
        self._cal_type: str = "Port 1 (SOL)"
        self._worker: Optional[CalMeasureWorker] = None
        self._thread: Optional[QThread] = None
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        intro = QLabel(
            "Step through each calibration standard. After all standards are\n"
            "measured, click <b>Activate</b> to apply the calibration. You can\n"
            "save the result to a .cal file for later.\n\n"
            "<i>Tip:</i> ensure the sweep range, points and IFBW are configured "
            "as you'll use them — the cal is valid only for that grid."
        )
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setStyleSheet("color:#aaa;")
        intro.setWordWrap(True)
        v.addWidget(intro)

        # cal-type selector
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Cal type:"))
        self.cb_type = QComboBox()
        self.cb_type.addItems(list(CAL_ACTIVATE_TOKEN.keys()))
        self.cb_type.currentTextChanged.connect(self._on_type_changed)
        self.cb_type.setToolTip(
            "Port 1 SOL — corrects S11 (single-port reflection on Port 1).\n"
            "Port 2 SOL — corrects S22.\n"
            "Through — calibrates only the P1↔P2 connection (S21/S12).\n"
            "Full SOLT — full 2-port: corrects S11/S21/S12/S22 plus isolation."
        )
        type_row.addWidget(self.cb_type, 1)
        v.addLayout(type_row)

        # steps list
        self.lst = QListWidget()
        self.lst.setStyleSheet("font-family: Consolas, monospace;")
        self.lst.itemSelectionChanged.connect(self._on_step_selected)
        v.addWidget(self.lst, 1)

        # current step description
        self.lbl_step = QLabel("Choose a cal type to begin.")
        self.lbl_step.setWordWrap(True)
        font = QFont(); font.setPointSize(10); font.setBold(True)
        self.lbl_step.setFont(font)
        v.addWidget(self.lbl_step)

        # action row
        actions = QHBoxLayout()
        self.btn_measure = QPushButton("Measure this step")
        self.btn_measure.setToolTip("Sends VNA:CAL:MEAS — do NOT touch the cabling until this finishes.")
        self.btn_measure.clicked.connect(self._measure_current)
        actions.addWidget(self.btn_measure)

        self.btn_skip = QPushButton("Mark done (no measure)")
        self.btn_skip.setToolTip("Skip this step (use only if it was already measured).")
        self.btn_skip.clicked.connect(self._mark_done)
        actions.addWidget(self.btn_skip)

        self.btn_reset = QPushButton("Reset cal")
        self.btn_reset.setToolTip("Clear all calibration measurements on the device.")
        self.btn_reset.clicked.connect(self._reset)
        actions.addWidget(self.btn_reset)
        v.addLayout(actions)

        # apply / save / load / close
        bottom = QHBoxLayout()
        self.btn_activate = QPushButton("Activate calibration")
        self.btn_activate.setToolTip("Apply the calibration as the active correction.")
        self.btn_activate.clicked.connect(self._activate)
        bottom.addWidget(self.btn_activate)

        self.btn_save = QPushButton("Save .cal…")
        self.btn_save.setToolTip("Persist the active cal to disk for later loading.")
        self.btn_save.clicked.connect(self._save)
        bottom.addWidget(self.btn_save)

        self.btn_load = QPushButton("Load .cal…")
        self.btn_load.setToolTip("Apply a previously saved calibration file.")
        self.btn_load.clicked.connect(self._load)
        bottom.addWidget(self.btn_load)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        bottom.addWidget(bb)
        v.addLayout(bottom)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#888;")
        v.addWidget(self.lbl_status)

        self._on_type_changed(self.cb_type.currentText())

    # --------------------------------------------------------- step setup
    def _on_type_changed(self, text: str) -> None:
        self._cal_type = text
        self.controller.cal_reset()
        self._steps = make_steps(text)
        self._populate_list()
        for s in self._steps:
            s.measurement_index = self.controller.cal_add(s.std_type, port=s.port)
        self._refresh_list()

    def _populate_list(self) -> None:
        self.lst.clear()
        for s in self._steps:
            it = QListWidgetItem(f"  ◯  {s.label}")
            it.setToolTip(s.description)
            self.lst.addItem(it)
        if self.lst.count() > 0:
            self.lst.setCurrentRow(0)

    def _refresh_list(self) -> None:
        for i, s in enumerate(self._steps):
            it = self.lst.item(i)
            if it is None:
                continue
            mark = "●" if s.completed else "◯"
            it.setText(f"  {mark}  {s.label}")
            color = "#00e0b4" if s.completed else "#e0e0e0"
            it.setForeground(self.palette().text() if not s.completed else self.palette().link())
            it.setToolTip(s.description)
        # auto-advance
        for i, s in enumerate(self._steps):
            if not s.completed:
                self.lst.setCurrentRow(i)
                break

    def _on_step_selected(self) -> None:
        i = self.lst.currentRow()
        if 0 <= i < len(self._steps):
            s = self._steps[i]
            self.lbl_step.setText(f"{s.label} — {s.description}")

    # --------------------------------------------------------- measure
    def _measure_current(self) -> None:
        if not self.controller.connected:
            QMessageBox.warning(self, "Not connected", "Connect to the SCPI server first.")
            return
        i = self.lst.currentRow()
        if not (0 <= i < len(self._steps)):
            return
        step = self._steps[i]
        if step.measurement_index <= 0:
            step.measurement_index = self.controller.cal_add(step.std_type, port=step.port)
            if step.measurement_index <= 0:
                QMessageBox.warning(self, "Failed", "Could not register cal step.")
                return
        self._set_busy(True, f"Measuring {step.label}…")
        self._worker = CalMeasureWorker(self.controller.client,
                                        [step.measurement_index],
                                        description=step.label)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda m: self.lbl_status.setText(m))
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda ok, st=step: self._on_measure_finished(ok, st))
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_measure_finished(self, ok: bool, step: CalStep) -> None:
        self._set_busy(False, "Done." if ok else "Failed.")
        if ok:
            step.completed = True
        self._refresh_list()

    def _on_worker_error(self, msg: str) -> None:
        self.lbl_status.setText(f"Error: {msg}")
        self.lbl_status.setStyleSheet("color:#ff5252;")

    def _mark_done(self) -> None:
        i = self.lst.currentRow()
        if 0 <= i < len(self._steps):
            self._steps[i].completed = True
        self._refresh_list()

    # ----------------------------------------------------------- finalize
    def _activate(self) -> None:
        token = CAL_ACTIVATE_TOKEN.get(self._cal_type, "")
        if not token:
            return
        self.controller.cal_activate(token)
        self.lbl_status.setText(f"Activated: {token}")
        self.lbl_status.setStyleSheet("color:#00e0b4;")

    def _save(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Save calibration",
                                            "calibration.cal",
                                            "LibreVNA calibration (*.cal);;All files (*)")
        if fn:
            self.controller.cal_save(fn)
            self.lbl_status.setText(f"Saved: {fn}")

    def _load(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(self, "Load calibration", "",
                                            "LibreVNA calibration (*.cal);;All files (*)")
        if fn:
            ok = self.controller.cal_load(fn)
            self.lbl_status.setText(f"Loaded: {fn}" if ok else f"Load failed: {fn}")
            if ok:
                # Cal files carry a sweep grid. Tell the main window to
                # pull it back from the device so the UI reflects reality.
                self.sweep_should_refresh.emit()

    def _reset(self) -> None:
        if QMessageBox.question(self, "Reset cal", "Discard all cal measurements?") != QMessageBox.StandardButton.Yes:
            return
        self.controller.cal_reset()
        for s in self._steps:
            s.completed = False
            s.measurement_index = self.controller.cal_add(s.std_type, port=s.port)
        self._refresh_list()
        self.lbl_status.setText("Calibration reset.")

    # ----------------------------------------------------------- helpers
    def _set_busy(self, busy: bool, msg: str = "") -> None:
        self.btn_measure.setEnabled(not busy)
        self.btn_skip.setEnabled(not busy)
        self.btn_reset.setEnabled(not busy)
        self.btn_activate.setEnabled(not busy)
        self.cb_type.setEnabled(not busy)
        if msg:
            self.lbl_status.setText(msg)
            self.lbl_status.setStyleSheet("color:#ffd34d;" if busy else "color:#00e0b4;")

    def closeEvent(self, ev) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        super().closeEvent(ev)

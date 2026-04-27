"""
Sweep configuration panel.

Lets the user set start/stop (or center/span), points, IF bandwidth,
averaging, power level. Has Run / Stop / Single Sweep buttons and shows
averaging progress.
"""
from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QRadioButton,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from ..controller import SweepConfig


_IFBW_PRESETS_HZ = (10, 30, 100, 300, 1_000, 3_000, 10_000, 30_000, 100_000)


def _hz_to_str(hz: float) -> str:
    if hz >= 1e9:
        return f"{hz/1e9:.6g} GHz"
    if hz >= 1e6:
        return f"{hz/1e6:.6g} MHz"
    if hz >= 1e3:
        return f"{hz/1e3:.6g} kHz"
    return f"{hz:.0f} Hz"


def _str_to_hz(s: str) -> float:
    s = s.strip().lower()
    if not s:
        return 0.0
    mults = {"ghz": 1e9, "mhz": 1e6, "khz": 1e3, "hz": 1.0,
             "g": 1e9, "m": 1e6, "k": 1e3}
    for suf, mul in mults.items():
        if s.endswith(suf):
            return float(s[:-len(suf)].strip()) * mul
    return float(s)


class FreqEdit(QWidget):
    """Frequency entry: spin box + GHz/MHz/kHz/Hz unit combo."""

    valueChanged = pyqtSignal(float)

    def __init__(self, default_hz: float = 1e9, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        self.sp = QDoubleSpinBox()
        self.sp.setDecimals(6)
        self.sp.setRange(0.0, 99_999.999_999)
        # Ignored width policy lets the layout shrink this past sizeHint.
        # No explicit minimumWidth — that would override Ignored.
        self.sp.setSizePolicy(QSizePolicy.Policy.Ignored,
                              QSizePolicy.Policy.Preferred)
        h.addWidget(self.sp, 1)
        self.cb = QComboBox()
        self.cb.addItems(["Hz", "kHz", "MHz", "GHz"])
        self.cb.setMinimumContentsLength(3)
        self.cb.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        h.addWidget(self.cb)
        self.sp.valueChanged.connect(self._emit)
        self.cb.currentTextChanged.connect(self._unit_changed)
        self.set_value_hz(default_hz)

    def _unit_for_hz(self, hz: float) -> str:
        if hz >= 1e9: return "GHz"
        if hz >= 1e6: return "MHz"
        if hz >= 1e3: return "kHz"
        return "Hz"

    def set_value_hz(self, hz: float) -> None:
        unit = self._unit_for_hz(max(hz, 1.0))
        mult = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}[unit]
        self.cb.blockSignals(True)
        self.cb.setCurrentText(unit)
        self.cb.blockSignals(False)
        self.sp.blockSignals(True)
        self.sp.setValue(hz / mult)
        self.sp.blockSignals(False)

    def value_hz(self) -> float:
        mult = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}[self.cb.currentText()]
        return self.sp.value() * mult

    def _emit(self, _v: float) -> None:
        self.valueChanged.emit(self.value_hz())

    def _unit_changed(self, _u: str) -> None:
        self.valueChanged.emit(self.value_hz())


class SweepPanel(QGroupBox):
    """Sweep config + acquisition control."""

    sweep_changed = pyqtSignal(object)        # SweepConfig
    run_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    single_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Sweep", parent)
        self._mode = "start_stop"
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 12, 10, 10)
        v.setSpacing(6)

        mode_row = QHBoxLayout()
        self.rb_ss = QRadioButton("Start/Stop")
        self.rb_cs = QRadioButton("Center/Span")
        self.rb_ss.setChecked(True)
        self.bg_mode = QButtonGroup(self)
        self.bg_mode.addButton(self.rb_ss)
        self.bg_mode.addButton(self.rb_cs)
        self.rb_ss.toggled.connect(self._sync_mode)
        for rb in (self.rb_ss, self.rb_cs):
            rb.setSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.Preferred)
        mode_row.addWidget(self.rb_ss)
        mode_row.addWidget(self.rb_cs)
        mode_row.addStretch(1)
        v.addLayout(mode_row)

        f = QFormLayout()
        f.setHorizontalSpacing(6)
        f.setVerticalSpacing(6)

        self.fr_start = FreqEdit(100e6)
        self.fr_start.setToolTip("Sweep start frequency (low end).")
        self.fr_stop = FreqEdit(6e9)
        self.fr_stop.setToolTip("Sweep stop frequency (high end). LibreVNA goes to 6 GHz.")
        self.fr_center = FreqEdit(2.45e9)
        self.fr_center.setToolTip("Center of the sweep range. Used in 'Center / Span' mode.")
        self.fr_span = FreqEdit(2e9)
        self.fr_span.setToolTip("Total sweep width.")

        f.addRow("Start:", self.fr_start)
        f.addRow("Stop:", self.fr_stop)
        f.addRow("Center:", self.fr_center)
        f.addRow("Span:", self.fr_span)

        self.sp_points = QSpinBox()
        self.sp_points.setRange(2, 4501)
        self.sp_points.setValue(501)
        self.sp_points.setToolTip(
            "Number of sample points across the sweep.\n"
            "More points = finer resolution but slower sweep. 401–801 is a good antenna default."
        )
        f.addRow("Points:", self.sp_points)

        self.cb_ifbw = QComboBox()
        for hz in _IFBW_PRESETS_HZ:
            self.cb_ifbw.addItem(_hz_to_str(hz), userData=hz)
        self.cb_ifbw.setCurrentIndex(_IFBW_PRESETS_HZ.index(10_000))
        self.cb_ifbw.setToolTip(
            "IF bandwidth — narrower = lower noise floor, slower sweep.\n"
            "1–10 kHz works well for antenna S11 measurements."
        )
        f.addRow("IF BW:", self.cb_ifbw)

        self.sp_avg = QSpinBox()
        self.sp_avg.setRange(1, 1000)
        self.sp_avg.setValue(1)
        self.sp_avg.setToolTip(
            "Number of sweeps averaged together.\n"
            "Higher reduces trace jitter; trade-off is response time."
        )
        f.addRow("Avg:", self.sp_avg)

        self.sp_power = QDoubleSpinBox()
        self.sp_power.setRange(-40.0, 10.0)
        self.sp_power.setSingleStep(0.5)
        self.sp_power.setValue(-10.0)
        self.sp_power.setSuffix(" dBm")
        self.sp_power.setToolTip(
            "Stimulus power at the source port. Default −10 dBm is safe for antennas.\n"
            "Be careful with sensitive DUTs (LNAs, diode detectors)."
        )
        f.addRow("Power:", self.sp_power)
        v.addLayout(f)

        # Run / Stop / Single — compact padding
        compact_btn = "QPushButton { padding: 4px 6px; }"
        btns = QHBoxLayout()
        self.btn_run = QPushButton("▶ Run")
        self.btn_run.setStyleSheet(compact_btn)
        self.btn_run.setToolTip("Start continuous sweeping.")
        self.btn_run.clicked.connect(self.run_requested.emit)
        btns.addWidget(self.btn_run)
        self.btn_stop = QPushButton("■ Stop")
        self.btn_stop.setStyleSheet(compact_btn)
        self.btn_stop.setToolTip("Halt sweeping.")
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        btns.addWidget(self.btn_stop)
        self.btn_single = QPushButton("▷ Single")
        self.btn_single.setStyleSheet(compact_btn)
        self.btn_single.setToolTip("Trigger one sweep, then stop.")
        self.btn_single.clicked.connect(self.single_requested.emit)
        btns.addWidget(self.btn_single)
        v.addLayout(btns)

        self.bar_progress = QProgressBar()
        self.bar_progress.setRange(0, 1)
        self.bar_progress.setFormat("Avg %v / %m")
        self.bar_progress.setVisible(False)
        v.addWidget(self.bar_progress)

        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setStyleSheet("QPushButton { padding: 5px 10px; }")
        self.btn_apply.setToolTip("Push start/stop/points/IFBW/averaging/power to the device.")
        self.btn_apply.clicked.connect(self._emit_sweep)
        v.addWidget(self.btn_apply)

        # changes auto-sync center/span vs start/stop
        self.fr_start.valueChanged.connect(self._propagate_from_ss)
        self.fr_stop.valueChanged.connect(self._propagate_from_ss)
        self.fr_center.valueChanged.connect(self._propagate_from_cs)
        self.fr_span.valueChanged.connect(self._propagate_from_cs)
        self._sync_mode()

    # --------------------------------------------------------------- API
    def read_config(self) -> SweepConfig:
        return SweepConfig(
            start_hz=self.fr_start.value_hz(),
            stop_hz=self.fr_stop.value_hz(),
            points=int(self.sp_points.value()),
            ifbw_hz=float(self.cb_ifbw.currentData() or 10_000),
            averaging=int(self.sp_avg.value()),
            power_dbm=float(self.sp_power.value()),
        )

    def write_config(self, cfg: SweepConfig) -> None:
        self.fr_start.set_value_hz(cfg.start_hz)
        self.fr_stop.set_value_hz(cfg.stop_hz)
        self.sp_points.setValue(int(cfg.points))
        # nearest IFBW preset
        if cfg.ifbw_hz:
            for i in range(self.cb_ifbw.count()):
                if abs(self.cb_ifbw.itemData(i) - cfg.ifbw_hz) < 0.5:
                    self.cb_ifbw.setCurrentIndex(i)
                    break
        self.sp_avg.setValue(int(cfg.averaging))
        self.sp_power.setValue(float(cfg.power_dbm))
        self._propagate_from_ss()

    def set_progress(self, current: int, target: int) -> None:
        if target <= 1:
            self.bar_progress.setVisible(False)
            return
        self.bar_progress.setVisible(True)
        self.bar_progress.setRange(0, target)
        self.bar_progress.setValue(current)

    def quick_set_band(self, start_hz: float, stop_hz: float,
                       points: Optional[int] = None) -> None:
        self.fr_start.set_value_hz(start_hz)
        self.fr_stop.set_value_hz(stop_hz)
        if points is not None:
            self.sp_points.setValue(int(points))
        self._propagate_from_ss()

    # ----------------------------------------------------------- helpers
    def _emit_sweep(self) -> None:
        self.sweep_changed.emit(self.read_config())

    def _sync_mode(self) -> None:
        self._mode = "start_stop" if self.rb_ss.isChecked() else "center_span"
        ss_visible = self._mode == "start_stop"
        self.fr_start.setEnabled(ss_visible)
        self.fr_stop.setEnabled(ss_visible)
        self.fr_center.setEnabled(not ss_visible)
        self.fr_span.setEnabled(not ss_visible)

    def _propagate_from_ss(self, *args) -> None:
        s = self.fr_start.value_hz()
        e = self.fr_stop.value_hz()
        c = 0.5 * (s + e)
        sp = max(0.0, e - s)
        self.fr_center.blockSignals(True)
        self.fr_span.blockSignals(True)
        self.fr_center.set_value_hz(c)
        self.fr_span.set_value_hz(sp)
        self.fr_center.blockSignals(False)
        self.fr_span.blockSignals(False)

    def _propagate_from_cs(self, *args) -> None:
        c = self.fr_center.value_hz()
        sp = self.fr_span.value_hz()
        s = max(0.0, c - 0.5 * sp)
        e = c + 0.5 * sp
        self.fr_start.blockSignals(True)
        self.fr_stop.blockSignals(True)
        self.fr_start.set_value_hz(s)
        self.fr_stop.set_value_hz(e)
        self.fr_start.blockSignals(False)
        self.fr_stop.blockSignals(False)

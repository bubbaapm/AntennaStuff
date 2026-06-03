"""Focused Qt control panels for the radar GUI."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .device_backends import list_serial_ports
from .models import RadarConfig, SweepConfig


class FreqEdit(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, default_hz: float, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.value = QDoubleSpinBox()
        self.value.setDecimals(6)
        self.value.setRange(0.0, 99_999.999_999)
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.unit = QComboBox()
        self.unit.addItems(["Hz", "kHz", "MHz", "GHz"])
        layout.addWidget(self.value, 1)
        layout.addWidget(self.unit)
        self.value.valueChanged.connect(lambda _v: self.valueChanged.emit(self.hz()))
        self.unit.currentTextChanged.connect(lambda _u: self.valueChanged.emit(self.hz()))
        self.set_hz(default_hz)

    def set_hz(self, hz: float) -> None:
        unit = "GHz" if hz >= 1e9 else "MHz" if hz >= 1e6 else "kHz" if hz >= 1e3 else "Hz"
        mult = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}[unit]
        self.unit.blockSignals(True)
        self.value.blockSignals(True)
        self.unit.setCurrentText(unit)
        self.value.setValue(float(hz) / mult)
        self.value.blockSignals(False)
        self.unit.blockSignals(False)

    def hz(self) -> float:
        return self.value.value() * {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}[self.unit.currentText()]


class ConnectionPanel(QGroupBox):
    connect_requested = pyqtSignal(str, str)
    disconnect_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Connection", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        form = QFormLayout()
        self.backend = QComboBox()
        self.backend.addItems(["LiteVNA / NanoVNA V2", "NanoVNA Shell"])
        form.addRow("Backend:", self.backend)
        port_row = QHBoxLayout()
        self.port = QComboBox()
        self.port.setEditable(True)
        self.btn_refresh = QToolButton()
        self.btn_refresh.setText("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.port, 1)
        port_row.addWidget(self.btn_refresh)
        form.addRow("COM:", port_row)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.btn_connect = QPushButton("Connect")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_connect.clicked.connect(self._emit_connect)
        self.btn_disconnect.clicked.connect(self.disconnect_requested.emit)
        row.addWidget(self.btn_connect)
        row.addWidget(self.btn_disconnect)
        layout.addLayout(row)
        self.status = QLabel("disconnected")
        self.status.setStyleSheet("color:#888;")
        layout.addWidget(self.status)
        self.refresh_ports()

    def refresh_ports(self) -> None:
        current = self.port.currentText().strip()
        self.port.clear()
        ports = list_serial_ports()
        for port in ports:
            self.port.addItem(port.label(), userData=port.port)
        if current:
            self.port.setCurrentText(current)

    def selected_port(self) -> str:
        return str(self.port.currentData() or self.port.currentText()).strip()

    def selected_backend(self) -> str:
        return self.backend.currentText()

    def set_connected(self, connected: bool, message: str = "") -> None:
        self.btn_connect.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        self.backend.setEnabled(not connected)
        self.port.setEnabled(not connected)
        self.status.setText(message or ("connected" if connected else "disconnected"))
        self.status.setStyleSheet("color:#00e0b4;" if connected else "color:#888;")

    def set_status(self, message: str, warn: bool = False) -> None:
        self.status.setText(message)
        self.status.setStyleSheet("color:#ffd34d;" if warn else "color:#b8d7ff;")

    def _emit_connect(self) -> None:
        self.connect_requested.emit(self.selected_backend(), self.selected_port())


class SweepPanel(QGroupBox):
    preset_chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Sweep", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        form = QFormLayout()
        self.start = FreqEdit(5.0e9)
        self.stop = FreqEdit(5.4e9)
        self.points = QSpinBox()
        self.points.setRange(11, 65535)
        self.points.setValue(501)
        self.poll_delay = QDoubleSpinBox()
        self.poll_delay.setRange(0.0, 5.0)
        self.poll_delay.setDecimals(3)
        self.poll_delay.setSingleStep(0.01)
        self.poll_delay.setValue(0.02)
        self.poll_delay.setSuffix(" s")
        form.addRow("Start:", self.start)
        form.addRow("Stop:", self.stop)
        form.addRow("VNA sweep pts:", self.points)
        form.addRow("Poll delay:", self.poll_delay)
        layout.addLayout(form)
        preset_row = QHBoxLayout()
        for label in ("Room Scan", "Close Range", "Max Distance"):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, name=label: self.apply_preset(name))
            preset_row.addWidget(btn)
        layout.addLayout(preset_row)

    def config(self) -> SweepConfig:
        return SweepConfig(
            start_hz=self.start.hz(),
            stop_hz=self.stop.hz(),
            points=int(self.points.value()),
            poll_delay_s=float(self.poll_delay.value()),
        )

    def set_config(self, config: SweepConfig) -> None:
        self.start.set_hz(config.start_hz)
        self.stop.set_hz(config.stop_hz)
        self.points.setValue(int(config.points))
        self.poll_delay.setValue(float(config.poll_delay_s))

    def apply_preset(self, name: str) -> None:
        presets = {
            "Room Scan": SweepConfig(5.0e9, 5.4e9, 501, poll_delay_s=0.02),
            "Close Range": SweepConfig(5.0e9, 6.0e9, 801, poll_delay_s=0.02),
            "Max Distance": SweepConfig(4.5e9, 5.5e9, 1001, poll_delay_s=0.04),
        }
        self.set_config(presets[name])
        self.preset_chosen.emit(name)


class RadarPanel(QGroupBox):
    config_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Radar DSP", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        form = QFormLayout()
        self.ema = QSlider(Qt.Orientation.Horizontal)
        self.ema.setRange(1, 100)
        self.ema.setValue(25)
        self.ema_label = QLabel("0.25")
        ema_row = QHBoxLayout()
        ema_row.addWidget(self.ema, 1)
        ema_row.addWidget(self.ema_label)
        self.ema.valueChanged.connect(self._ema_changed)
        form.addRow("EMA alpha:", ema_row)
        self.window = QComboBox()
        self.window.addItems(["hann", "hamming", "rectangular"])
        form.addRow("Window:", self.window)
        self.tvg = QCheckBox("Enable range compensation")
        form.addRow("", self.tvg)
        self.range_min = QDoubleSpinBox()
        self.range_min.setRange(0.0, 10_000.0)
        self.range_min.setValue(0.0)
        self.range_min.setSuffix(" m")
        self.range_max = QDoubleSpinBox()
        self.range_max.setRange(0.01, 10_000.0)
        self.range_max.setValue(10.0)
        self.range_max.setSuffix(" m")
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.0, 1e9)
        self.threshold.setDecimals(8)
        self.threshold.setSingleStep(0.0001)
        self.ascope_bins = QSpinBox()
        self.ascope_bins.setRange(64, 65536)
        self.ascope_bins.setSingleStep(256)
        self.ascope_bins.setValue(2048)
        self.ascope_bins.setToolTip(
            "Display/DSP interpolation bins for the A-scope IFFT.\n"
            "This does not change the VNA sweep points."
        )
        form.addRow("Range min:", self.range_min)
        form.addRow("Range max:", self.range_max)
        form.addRow("Peak threshold:", self.threshold)
        form.addRow("A-scope bins:", self.ascope_bins)
        layout.addLayout(form)
        for widget in (self.window, self.tvg, self.range_min, self.range_max, self.threshold, self.ascope_bins):
            if hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(self.config_changed.emit)
            if hasattr(widget, "toggled"):
                widget.toggled.connect(self.config_changed.emit)
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self.config_changed.emit)

    def _ema_changed(self, value: int) -> None:
        self.ema_label.setText(f"{value / 100.0:.2f}")
        self.config_changed.emit()

    def config(self, background_id: str = "") -> RadarConfig:
        return RadarConfig(
            background_id=background_id,
            ema_alpha=self.ema.value() / 100.0,
            window=self.window.currentText(),
            tvg_enabled=self.tvg.isChecked(),
            range_min_m=float(self.range_min.value()),
            range_max_m=float(self.range_max.value()),
            peak_threshold=float(self.threshold.value()),
            peak_prominence=float(self.threshold.value()) * 0.25 if self.threshold.value() > 0 else 0.0,
            range_fft_points=int(self.ascope_bins.value()),
        )


class BackgroundPanel(QGroupBox):
    acquire_requested = pyqtSignal(int)
    save_requested = pyqtSignal()
    load_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Background", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        row = QHBoxLayout()
        self.sweeps = QSpinBox()
        self.sweeps.setRange(1, 500)
        self.sweeps.setValue(10)
        row.addWidget(QLabel("Sweeps:"))
        row.addWidget(self.sweeps, 1)
        layout.addLayout(row)
        self.current = QLabel("none")
        self.current.setStyleSheet("color:#888;")
        layout.addWidget(self.current)
        row2 = QHBoxLayout()
        self.btn_acquire = QPushButton("Acquire")
        self.btn_save = QPushButton("Save")
        self.btn_load = QPushButton("Load")
        self.btn_clear = QPushButton("Clear")
        row2.addWidget(self.btn_acquire)
        row2.addWidget(self.btn_save)
        row2.addWidget(self.btn_load)
        row2.addWidget(self.btn_clear)
        layout.addLayout(row2)
        self.btn_acquire.clicked.connect(lambda: self.acquire_requested.emit(int(self.sweeps.value())))
        self.btn_save.clicked.connect(self.save_requested.emit)
        self.btn_load.clicked.connect(self.load_requested.emit)
        self.btn_clear.clicked.connect(self.clear_requested.emit)

    def set_name(self, name: str) -> None:
        self.current.setText(name or "none")
        self.current.setStyleSheet("color:#00e0b4;" if name else "color:#888;")


class CapturePanel(QGroupBox):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    replay_load_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Capture / Replay", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        row = QHBoxLayout()
        self.btn_start = QPushButton("Start Capture")
        self.btn_stop = QPushButton("Stop + Save")
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)
        layout.addLayout(row)
        self.btn_load = QPushButton("Load Replay")
        layout.addWidget(self.btn_load)
        self.status = QLabel("not recording")
        self.status.setStyleSheet("color:#888;")
        layout.addWidget(self.status)
        self.btn_start.clicked.connect(self.start_requested.emit)
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        self.btn_load.clicked.connect(self.replay_load_requested.emit)

    def set_recording(self, recording: bool, count: int = 0) -> None:
        self.btn_start.setEnabled(not recording)
        self.btn_stop.setEnabled(recording)
        self.status.setText(f"recording {count} sweeps" if recording else "not recording")
        self.status.setStyleSheet("color:#ffcf5a;" if recording else "color:#888;")

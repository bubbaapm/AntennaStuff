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
    load_cal_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Connection", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        form = QFormLayout()

        # Connection type selector
        self.conn_type = QComboBox()
        self.conn_type.addItems(["Serial (LiteVNA / NanoVNA)", "TCP/SCPI (LibreVNA)"])
        self.conn_type.currentIndexChanged.connect(self._update_conn_fields)
        form.addRow("Type:", self.conn_type)

        # Backend selector
        self.backend = QComboBox()
        self.backend.addItems(["LiteVNA / NanoVNA V2", "NanoVNA Shell", "LibreVNA (SCPI)"])
        form.addRow("Backend:", self.backend)

        # Serial port row (shown for Serial type)
        self._serial_widget = QWidget()
        port_row = QHBoxLayout(self._serial_widget)
        port_row.setContentsMargins(0, 0, 0, 0)
        port_row.setSpacing(2)
        self.port = QComboBox()
        self.port.setEditable(True)
        self.btn_refresh = QToolButton()
        self.btn_refresh.setText("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.port, 1)
        port_row.addWidget(self.btn_refresh)
        form.addRow("COM:", self._serial_widget)

        # TCP/SCPI host row (shown for LibreVNA type)
        self.scpi_host = QLineEdit("localhost:19542")
        self.scpi_host.setPlaceholderText("host:port, e.g. localhost:19542")
        form.addRow("SCPI Host:", self.scpi_host)

        # Auto-launch checkbox (LibreVNA only)
        self.auto_launch = QCheckBox("Auto-launch LibreVNA-GUI")
        self.auto_launch.setChecked(True)
        self.auto_launch.setToolTip(
            "Automatically launch LibreVNA-GUI if the SCPI\n"
            "port is not already open when connecting."
        )
        form.addRow("", self.auto_launch)

        layout.addLayout(form)

        # Connect/Disconnect buttons
        row = QHBoxLayout()
        self.btn_connect = QPushButton("Connect")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_connect.clicked.connect(self._emit_connect)
        self.btn_disconnect.clicked.connect(self.disconnect_requested.emit)
        row.addWidget(self.btn_connect)
        row.addWidget(self.btn_disconnect)
        layout.addLayout(row)

        # Load Calibration button (LibreVNA only)
        self.btn_load_cal = QPushButton("Load Calibration (.cal)")
        self.btn_load_cal.setToolTip("Load a saved .cal file onto the LibreVNA device.")
        self.btn_load_cal.clicked.connect(self.load_cal_requested.emit)
        layout.addWidget(self.btn_load_cal)

        # Status label
        self.status = QLabel("disconnected")
        self.status.setStyleSheet("color:#888;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        # Keep references for visibility toggling
        self._form = form
        self._serial_label: Optional[QLabel] = None
        self._tcp_label: Optional[QLabel] = None
        self._autolaunch_label: Optional[QLabel] = None
        # Find QFormLayout labels for our rows
        for i in range(form.rowCount()):
            item = form.itemAt(i, QFormLayout.ItemRole.FieldRole)
            label = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            if item and label:
                widget = item.widget()
                if widget is self._serial_widget:
                    self._serial_label = label.widget()
                elif widget is self.scpi_host:
                    self._tcp_label = label.widget()

        self.refresh_ports()
        self._update_conn_fields()

    def is_tcp_mode(self) -> bool:
        return self.conn_type.currentIndex() == 1

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
        self.conn_type.setEnabled(not connected)
        self.port.setEnabled(not connected)
        self.scpi_host.setEnabled(not connected)
        self.btn_load_cal.setEnabled(connected and self.is_tcp_mode())
        mode_tag = "SCPI" if self.is_tcp_mode() else "Serial"
        default = f"connected ({mode_tag})" if connected else "disconnected"
        self.status.setText(message or default)
        self.status.setStyleSheet("color:#00e0b4;" if connected else "color:#888;")

    def set_status(self, message: str, warn: bool = False) -> None:
        self.status.setText(message)
        self.status.setStyleSheet("color:#ffd34d;" if warn else "color:#b8d7ff;")

    def clear_error_status(self) -> None:
        if self.btn_disconnect.isEnabled():
            mode_tag = "SCPI" if self.is_tcp_mode() else "Serial"
            self.status.setText(f"connected ({mode_tag})")
            self.status.setStyleSheet("color:#00e0b4;")

    def _update_conn_fields(self) -> None:
        is_tcp = self.is_tcp_mode()
        # Show/hide serial vs TCP widgets
        self._serial_widget.setVisible(not is_tcp)
        if self._serial_label:
            self._serial_label.setVisible(not is_tcp)
        self.scpi_host.setVisible(is_tcp)
        if self._tcp_label:
            self._tcp_label.setVisible(is_tcp)
        self.auto_launch.setVisible(is_tcp)
        self.btn_load_cal.setVisible(is_tcp)
        # Auto-select matching backend
        if is_tcp:
            self.backend.setCurrentText("LibreVNA (SCPI)")
        elif self.backend.currentText() == "LibreVNA (SCPI)":
            self.backend.setCurrentText("LiteVNA / NanoVNA V2")

    def _emit_connect(self) -> None:
        if self.is_tcp_mode():
            self.connect_requested.emit(
                self.selected_backend(), self.scpi_host.text().strip()
            )
        else:
            self.connect_requested.emit(
                self.selected_backend(), self.selected_port()
            )


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

        # LibreVNA-specific fields
        self.ifbw = QDoubleSpinBox()
        self.ifbw.setRange(10.0, 1_000_000.0)
        self.ifbw.setDecimals(0)
        self.ifbw.setSingleStep(1000)
        self.ifbw.setValue(10_000)
        self.ifbw.setSuffix(" Hz")
        self.ifbw.setToolTip(
            "IF bandwidth — lower = less noise but slower sweeps.\n"
            "Only applies to LibreVNA."
        )
        form.addRow("IFBW:", self.ifbw)

        self.power_dbm = QDoubleSpinBox()
        self.power_dbm.setRange(-42.0, 0.0)
        self.power_dbm.setDecimals(1)
        self.power_dbm.setSingleStep(1.0)
        self.power_dbm.setValue(-10.0)
        self.power_dbm.setSuffix(" dBm")
        self.power_dbm.setToolTip(
            "Stimulus power level.\n"
            "Only applies to LibreVNA."
        )
        form.addRow("Power:", self.power_dbm)

        layout.addLayout(form)

        # Find labels for visibility toggling
        self._ifbw_label: Optional[QLabel] = None
        self._power_label: Optional[QLabel] = None
        for i in range(form.rowCount()):
            item = form.itemAt(i, QFormLayout.ItemRole.FieldRole)
            label = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            if item and label:
                widget = item.widget()
                if widget is self.ifbw:
                    self._ifbw_label = label.widget()
                elif widget is self.power_dbm:
                    self._power_label = label.widget()

        preset_row = QHBoxLayout()
        for label in ("Room Scan", "Close Range", "Max Distance"):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, name=label: self.apply_preset(name))
            preset_row.addWidget(btn)
        layout.addLayout(preset_row)

        # Default: hide LibreVNA fields
        self.show_librevna_fields(False)

    def show_librevna_fields(self, visible: bool) -> None:
        """Show or hide LibreVNA-specific sweep fields (IFBW, Power)."""
        self.ifbw.setVisible(visible)
        self.power_dbm.setVisible(visible)
        if self._ifbw_label:
            self._ifbw_label.setVisible(visible)
        if self._power_label:
            self._power_label.setVisible(visible)

    def config(self) -> SweepConfig:
        backend_options = {}
        if self.ifbw.isVisible():
            backend_options["ifbw_hz"] = float(self.ifbw.value())
            backend_options["power_dbm"] = float(self.power_dbm.value())
        return SweepConfig(
            start_hz=self.start.hz(),
            stop_hz=self.stop.hz(),
            points=int(self.points.value()),
            poll_delay_s=float(self.poll_delay.value()),
            backend_options=backend_options,
        )

    def set_config(self, config: SweepConfig) -> None:
        self.start.set_hz(config.start_hz)
        self.stop.set_hz(config.stop_hz)
        self.points.setValue(int(config.points))
        self.poll_delay.setValue(float(config.poll_delay_s))
        if "ifbw_hz" in config.backend_options:
            self.ifbw.setValue(float(config.backend_options["ifbw_hz"]))
        if "power_dbm" in config.backend_options:
            self.power_dbm.setValue(float(config.backend_options["power_dbm"]))

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

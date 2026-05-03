"""
Connection panel — host/port, device selection, connect/launch buttons,
SCPI status indicator.
"""
from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
    QToolButton,
)


class StatusLED(QFrame):
    """Tiny circle that shows connection state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = QColor("#666")

    def paintEvent(self, ev):
        from PyQt6.QtGui import QPainter, QBrush, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(self._color))
        p.setPen(QPen(QColor("#000"), 1))
        p.drawEllipse(0, 0, 13, 13)

    def set_state(self, kind: str) -> None:
        self._color = {
            "off": QColor("#666"),
            "warn": QColor("#ffd34d"),
            "ok": QColor("#00e0b4"),
            "err": QColor("#ff5252"),
        }.get(kind, QColor("#666"))
        self.update()


class ConnectionPanel(QGroupBox):
    """
    Group-box widget with connection settings and device selector.

    Signals:
      connect_requested(host, port, auto_launch)
      disconnect_requested()
      device_chosen(serial)              # empty string = first/auto
      browse_librevna(path or "")
    """

    connect_requested = pyqtSignal(str, int, bool)
    disconnect_requested = pyqtSignal()
    device_chosen = pyqtSignal(str)
    refresh_devices = pyqtSignal()
    browse_librevna = pyqtSignal(str)

    def __init__(self, host: str, port: int, librevna_path: str = "",
                 parent=None):
        super().__init__("Connection", parent)
        self._build(host, port, librevna_path)

    def _build(self, host: str, port: int, librevna_path: str) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 12, 8, 8)
        v.setSpacing(4)

        # SCPI host/port — tight row
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Host:"))
        self.le_host = QLineEdit(host)
        self.le_host.setToolTip("LibreVNA-GUI SCPI server address. Usually 'localhost'.")
        row1.addWidget(self.le_host, 1)
        row1.addWidget(QLabel("Port:"))
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535); self.sp_port.setValue(port)
        self.sp_port.setMaximumWidth(70)
        self.sp_port.setToolTip("Default LibreVNA SCPI port is 19542.")
        row1.addWidget(self.sp_port)
        v.addLayout(row1)

        # LibreVNA-GUI path
        row_path = QHBoxLayout()
        row_path.addWidget(QLabel("Exe:"))
        self.le_path = QLineEdit(librevna_path)
        self.le_path.setReadOnly(True)
        self.le_path.setToolTip(
            "Path to LibreVNA-GUI.exe — auto-discovered.\n"
            "Click … to override; the choice is saved next to the app."
        )
        self.le_path.setStyleSheet("color:#aaa;")
        row_path.addWidget(self.le_path, 1)
        self.btn_browse = QToolButton()
        self.btn_browse.setText("…")
        self.btn_browse.setToolTip("Browse for LibreVNA-GUI executable")
        self.btn_browse.clicked.connect(self._browse)
        row_path.addWidget(self.btn_browse)
        v.addLayout(row_path)

        # Connect / disconnect — single row
        compact = "QPushButton { padding: 4px 6px; }"
        row2 = QHBoxLayout()
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setStyleSheet(compact)
        self.btn_connect.setSizePolicy(QSizePolicy.Policy.Preferred,
                                       QSizePolicy.Policy.Preferred)
        self.btn_connect.setToolTip(
            "Connect to LibreVNA-GUI's SCPI server.\n"
            "If the server isn't running, the app launches it in the background."
        )
        self.btn_connect.clicked.connect(self._on_connect)
        row2.addWidget(self.btn_connect)
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setStyleSheet(compact)
        self.btn_disconnect.setSizePolicy(QSizePolicy.Policy.Ignored,
                                          QSizePolicy.Policy.Preferred)
        self.btn_disconnect.setToolTip("Drop the SCPI connection (keeps the server running).")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_requested.emit)
        row2.addWidget(self.btn_disconnect)
        v.addLayout(row2)

        # Status LED + label, on its own row so a long IDN can use the space.
        row_status = QHBoxLayout()
        self.led = StatusLED()
        row_status.addWidget(self.led)
        self.lbl_status = QLabel("disconnected")
        self.lbl_status.setStyleSheet("color:#888;")
        self.lbl_status.setWordWrap(False)
        # Don't let a long IDN dominate panel min width.
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        row_status.addWidget(self.lbl_status, 1)
        v.addLayout(row_status)

        # Device row — compact
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Dev:"))
        self.cb_dev = QComboBox()
        self.cb_dev.setToolTip("Connected LibreVNA hardware. Empty = first device found.")
        self.cb_dev.setMinimumContentsLength(6)
        self.cb_dev.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        row3.addWidget(self.cb_dev, 1)
        self.btn_dev_refresh = QToolButton(); self.btn_dev_refresh.setText("⟳")
        self.btn_dev_refresh.setToolTip("Re-scan for connected LibreVNA devices")
        self.btn_dev_refresh.clicked.connect(self.refresh_devices.emit)
        row3.addWidget(self.btn_dev_refresh)
        self.btn_dev_use = QToolButton(); self.btn_dev_use.setText("Use")
        self.btn_dev_use.setToolTip("Tell LibreVNA-GUI to use the selected hardware.")
        self.btn_dev_use.clicked.connect(self._use_selected_device)
        row3.addWidget(self.btn_dev_use)
        v.addLayout(row3)

    # ----------------------------------------------------------- handlers
    def _browse(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(
            self, "Locate LibreVNA-GUI", "",
            "LibreVNA-GUI executable (LibreVNA-GUI.exe LibreVNA-GUI);;All files (*)"
        )
        if fn:
            self.le_path.setText(fn)
            self.browse_librevna.emit(fn)

    def _on_connect(self) -> None:
        self.connect_requested.emit(
            self.le_host.text().strip() or "localhost",
            int(self.sp_port.value()),
            True,
        )

    def _use_selected_device(self) -> None:
        text = self.cb_dev.currentText().strip()
        # If "(any)" is selected we send empty serial
        if text.startswith("("):
            text = ""
        self.device_chosen.emit(text)

    # -------------------------------------------------------------- state
    def set_connected(self, ok: bool, message: str = "") -> None:
        self.btn_connect.setEnabled(not ok)
        self.btn_disconnect.setEnabled(ok)
        self.led.set_state("ok" if ok else "off")
        text = message or ("connected" if ok else "disconnected")
        # elide so a long IDN doesn't blow up the panel width
        if len(text) > 26:
            self.lbl_status.setToolTip(text)
            text = text[:23] + "…"
        else:
            self.lbl_status.setToolTip("")
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet("color:#00e0b4;" if ok else "color:#888;")

    def set_status(self, kind: str, text: str) -> None:
        self.led.set_state(kind)
        self.lbl_status.setText(text)
        col = {"off": "#888", "warn": "#ffd34d", "ok": "#00e0b4", "err": "#ff5252"}
        self.lbl_status.setStyleSheet(f"color:{col.get(kind, '#888')};")

    def set_device_list(self, serials: list[str], selected: str = "") -> None:
        self.cb_dev.blockSignals(True)
        self.cb_dev.clear()
        self.cb_dev.addItem("(any)")
        for s in serials:
            self.cb_dev.addItem(s)
        if selected and selected in serials:
            self.cb_dev.setCurrentText(selected)
        self.cb_dev.blockSignals(False)

    def set_librevna_path(self, p: str) -> None:
        self.le_path.setText(p)

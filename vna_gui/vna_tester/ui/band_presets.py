"""
Band-preset buttons. One-click sweep configuration for common antenna bands.
"""
from __future__ import annotations
from typing import Dict, List, Tuple

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QPushButton, QToolButton, QVBoxLayout, QWidget, QFileDialog,
)


# (label, start_hz, stop_hz, suggested_points, hint)
BUILTIN_PRESETS: List[Tuple[str, float, float, int, str]] = [
    ("Wide 10M–6G", 10e6, 6e9, 1001, "Broadband sanity sweep (10 MHz – 6 GHz)"),
    ("ISM 433",     410e6, 460e6, 401, "433 MHz LPD / LoRa band"),
    ("ISM 868",     850e6, 880e6, 401, "EU 868 MHz LoRa / Sigfox"),
    ("ISM 915",     902e6, 928e6, 401, "US 915 MHz ISM / LoRa"),
    ("GPS L1",      1.5e9, 1.65e9, 401, "GNSS L1 (1575.42 MHz)"),
    ("GSM 1800",    1.7e9, 1.9e9, 401, "DCS 1800 / 4G B3"),
    ("WiFi 2.4G",   2.3e9, 2.5e9, 401, "2.4 GHz Wi-Fi / BLE / Zigbee"),
    ("WiFi 5G",     5.0e9, 6.0e9, 501, "5 GHz Wi-Fi / Wi-Fi 6E lower"),
    ("UWB low",     3.1e9, 5.0e9, 601, "UWB sub-band 3.1–5.0 GHz"),
    ("LTE B1",      1.92e9, 2.17e9, 401, "LTE B1 / 5G n1 (1.92–2.17 GHz)"),
    ("LTE B7",      2.5e9, 2.7e9, 401, "LTE B7 / 5G n7 (2.5–2.7 GHz)"),
    ("LTE B41",     2.5e9, 2.7e9, 401, "LTE B41 / n41 (2.5–2.7 GHz)"),
]


class BandPresets(QGroupBox):
    """Grid of buttons that emit (start, stop, points)."""

    preset_chosen = pyqtSignal(float, float, int)

    def __init__(self, custom: Dict[str, dict] = None, parent=None):
        super().__init__("Band presets", parent)
        self._custom = dict(custom or {})
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 12, 10, 10)
        v.setSpacing(4)

        info = QLabel("Quick-set sweep range:")
        info.setStyleSheet("color:#888;")
        v.addWidget(info)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(4)
        v.addWidget(self._grid_host)

        actions = QHBoxLayout()
        self.btn_save_current = QPushButton("Save preset…")
        self.btn_save_current.setStyleSheet("QPushButton { padding: 4px 6px; }")
        self.btn_save_current.setToolTip("Save the current sweep range as a custom preset.")
        self.btn_save_current.clicked.connect(self._save_current_request)
        actions.addWidget(self.btn_save_current)
        v.addLayout(actions)

        self._populate()

    def _populate(self) -> None:
        # clear grid
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        all_presets: List[Tuple[str, float, float, int, str]] = list(BUILTIN_PRESETS)
        for name, p in self._custom.items():
            all_presets.append((name, p["start"], p["stop"], p.get("points", 401), p.get("hint", "(custom)")))
        cols = 2
        compact = "QPushButton { padding: 4px 6px; }"
        for i, (label, s, e, pts, hint) in enumerate(all_presets):
            b = QPushButton(label)
            b.setStyleSheet(compact)
            b.setToolTip(f"{label}\n{s/1e9:.4g} – {e/1e9:.4g} GHz · {pts} points\n{hint}")
            b.clicked.connect(lambda _=False, s=s, e=e, p=pts: self.preset_chosen.emit(s, e, p))
            r, c = divmod(i, cols)
            self._grid.addWidget(b, r, c)

    def add_custom(self, name: str, start_hz: float, stop_hz: float,
                   points: int, hint: str = "") -> None:
        self._custom[name] = {"start": start_hz, "stop": stop_hz,
                              "points": points, "hint": hint}
        self._populate()

    def custom_presets(self) -> Dict[str, dict]:
        return dict(self._custom)

    def restore_custom(self, custom: Dict[str, dict]) -> None:
        self._custom = dict(custom or {})
        self._populate()

    def _save_current_request(self) -> None:
        # The main window will catch this & ask the user. We just expose
        # a public hook by emitting a signal — but to keep things tight,
        # the main window connects directly to preset_chosen for restore
        # and calls add_custom_for_save() back here.
        # Simplify: open the input dialog here, but the main window
        # supplies the (start,stop,points) via add_custom() afterwards.
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Save preset",
            "Use the menu File → Save current sweep as preset.\n"
            "(The main window has the active sweep settings.)"
        )

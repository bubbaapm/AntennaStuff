"""
Image export dialog — pick file, format, resolution, and what to export.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
    QWidget, QRadioButton, QGroupBox, QButtonGroup,
)


COMMON_RESOLUTIONS = [
    ("HD 1280×720", (1280, 720)),
    ("FHD 1920×1080", (1920, 1080)),
    ("QHD 2560×1440", (2560, 1440)),
    ("4K 3840×2160", (3840, 2160)),
    ("Print 300 DPI A4 (3508×2480)", (3508, 2480)),
    ("Custom…", None),
]


class ExportDialog(QDialog):
    """
    What to export:
      • A single plot (user picks from a list)
      • The whole window (composite — re-renders each plot at high res)
      • Plain screenshot (matches what you see)
    """

    def __init__(self, panel_titles: list[str], default_dir: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export image")
        self.resize(640, 540)
        self.setMinimumSize(480, 460)
        self._panels = list(panel_titles)
        self._default_dir = default_dir
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        gb_what = QGroupBox("What to export")
        gv = QVBoxLayout(gb_what)
        self.rb_panel = QRadioButton("A single plot panel")
        self.rb_window = QRadioButton("Whole window (high-res composite)")
        self.rb_window.setToolTip(
            "Re-renders each plot at high resolution, then composites them in their\n"
            "current grid position. Output is sharp at any chosen resolution."
        )
        self.rb_screenshot = QRadioButton("Plain screenshot (what you see)")
        self.rb_screenshot.setToolTip(
            "Grabs the window pixels at native resolution.\n"
            "Use only when you want the screen exactly as it is — output won't scale up sharply."
        )
        self.rb_window.setChecked(True)
        self.bg = QButtonGroup(self)
        self.bg.addButton(self.rb_panel)
        self.bg.addButton(self.rb_window)
        self.bg.addButton(self.rb_screenshot)
        gv.addWidget(self.rb_panel)
        gv.addWidget(self.rb_window)
        gv.addWidget(self.rb_screenshot)

        # Panel selector (active when rb_panel selected)
        sub = QHBoxLayout()
        sub.addWidget(QLabel("    Plot:"))
        self.cb_panel = QComboBox()
        self.cb_panel.addItems(self._panels)
        self.cb_panel.setEnabled(False)
        sub.addWidget(self.cb_panel, 1)
        gv.addLayout(sub)
        self.rb_panel.toggled.connect(lambda on: self.cb_panel.setEnabled(on))
        v.addWidget(gb_what)

        # Resolution
        gb_res = QGroupBox("Resolution")
        gf = QFormLayout(gb_res)
        self.cb_res = QComboBox()
        for label, _ in COMMON_RESOLUTIONS:
            self.cb_res.addItem(label)
        self.cb_res.setCurrentIndex(1)
        self.cb_res.currentIndexChanged.connect(self._sync_custom_enabled)
        gf.addRow("Preset:", self.cb_res)

        row = QHBoxLayout()
        self.sp_w = QSpinBox()
        self.sp_w.setRange(64, 16384)
        self.sp_w.setValue(1920)
        self.sp_h = QSpinBox()
        self.sp_h.setRange(64, 16384)
        self.sp_h.setValue(1080)
        row.addWidget(QLabel("W:"))
        row.addWidget(self.sp_w)
        row.addWidget(QLabel("H:"))
        row.addWidget(self.sp_h)
        gf.addRow("Custom:", row)
        v.addWidget(gb_res)

        # File path
        gb_file = QGroupBox("Destination")
        gh = QHBoxLayout(gb_file)
        self.le_path = QLineEdit(self._default_dir)
        self.le_path.setPlaceholderText("output.png")
        gh.addWidget(self.le_path, 1)
        b = QPushButton("…")
        b.setFixedWidth(28)
        b.clicked.connect(self._browse)
        gh.addWidget(b)
        v.addWidget(gb_file)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bb.button(QDialogButtonBox.StandardButton.Save).setText("Export")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        self._sync_custom_enabled()

    def _sync_custom_enabled(self) -> None:
        is_custom = COMMON_RESOLUTIONS[self.cb_res.currentIndex()][1] is None
        self.sp_w.setEnabled(is_custom)
        self.sp_h.setEnabled(is_custom)
        if not is_custom:
            wh = COMMON_RESOLUTIONS[self.cb_res.currentIndex()][1]
            self.sp_w.setValue(wh[0])
            self.sp_h.setValue(wh[1])

    def _browse(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(
            self, "Save image as", self.le_path.text() or "output.png",
            "PNG (*.png);;JPEG (*.jpg);;SVG vector (*.svg);;PDF (*.pdf)"
        )
        if fn:
            self.le_path.setText(fn)

    def selection(self) -> dict:
        what = "panel" if self.rb_panel.isChecked() else (
            "window" if self.rb_window.isChecked() else "screenshot"
        )
        wh = (int(self.sp_w.value()), int(self.sp_h.value()))
        path = self.le_path.text().strip()
        if not path:
            path = "vna_export.png"
        if not Path(path).suffix:
            path += ".png"
        return {
            "what": what,
            "panel": self.cb_panel.currentText(),
            "size": wh,
            "path": path,
            "fmt": Path(path).suffix.lstrip(".").lower(),
        }

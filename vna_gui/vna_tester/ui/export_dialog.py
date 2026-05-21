"""
Image export dialog — pick file, format, resolution, and what to export.
"""
from __future__ import annotations
import datetime
from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
    QWidget, QRadioButton, QGroupBox, QButtonGroup,
)

from ..paths import default_export_dir


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
        self.resize(640, 560)
        self.setMinimumSize(520, 500)
        self._panels = list(panel_titles)
        # Resolve default dir: prefer user-saved, else <app>/Images.
        if default_dir:
            self._default_dir = Path(default_dir)
        else:
            self._default_dir = default_export_dir()
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        gb_what = QGroupBox("What to export")
        gv = QVBoxLayout(gb_what)
        self.rb_panel = QRadioButton("A single plot panel")
        gv.addWidget(self.rb_panel)

        # Panel selector goes directly under its radio button so the user
        # sees them grouped. Disabled until "A single plot panel" is chosen.
        sub = QHBoxLayout()
        sub.addWidget(QLabel("    Plot:"))
        self.cb_panel = QComboBox()
        self.cb_panel.addItems(self._panels)
        self.cb_panel.setEnabled(False)
        sub.addWidget(self.cb_panel, 1)
        gv.addLayout(sub)

        self.rb_window = QRadioButton("Whole window (high-res composite)")
        self.rb_window.setToolTip(
            "Re-renders each plot at high resolution, then composites them in their\n"
            "current grid position. Output is sharp at any chosen resolution."
        )
        gv.addWidget(self.rb_window)

        self.rb_screenshot = QRadioButton("Plain screenshot (upscaled)")
        self.rb_screenshot.setToolTip(
            "Grabs the window pixels and bitmap-scales to the chosen resolution.\n"
            "Faster than 'Whole window' but slightly less crisp — text and lines\n"
            "are stretched, not re-rendered."
        )
        gv.addWidget(self.rb_screenshot)

        self.rb_window.setChecked(True)
        self.bg = QButtonGroup(self)
        self.bg.addButton(self.rb_panel)
        self.bg.addButton(self.rb_window)
        self.bg.addButton(self.rb_screenshot)
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

        # File path — folder + filename split for clarity.
        gb_file = QGroupBox("Destination")
        gv = QVBoxLayout(gb_file)

        # Folder row
        row_folder = QHBoxLayout()
        row_folder.addWidget(QLabel("Folder:"))
        self.le_folder = QLineEdit(str(self._default_dir))
        self.le_folder.setToolTip(
            "Folder where the image is saved.\n"
            "Default: <app>/Images (created on first export)."
        )
        row_folder.addWidget(self.le_folder, 1)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._browse_folder)
        row_folder.addWidget(btn_browse)
        gv.addLayout(row_folder)

        # Filename row
        row_name = QHBoxLayout()
        row_name.addWidget(QLabel("Filename:"))
        # Build a sensible default name: vna_<YYYYMMDD-HHMMSS>
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.le_name = QLineEdit(f"vna_{ts}")
        self.le_name.setToolTip(
            "Filename (without extension — that's set by the format below)."
        )
        row_name.addWidget(self.le_name, 1)
        gv.addLayout(row_name)

        # Format row
        row_fmt = QHBoxLayout()
        row_fmt.addWidget(QLabel("Format:"))
        self.cb_fmt = QComboBox()
        self.cb_fmt.addItems(["png", "jpg", "svg", "pdf"])
        self.cb_fmt.setToolTip(
            "PNG = sharp raster (default).  SVG/PDF = vector (matplotlib panels only).\n"
            "JPG = smaller file, lossy."
        )
        row_fmt.addWidget(self.cb_fmt)
        row_fmt.addStretch(1)
        gv.addLayout(row_fmt)
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

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose export folder",
            self.le_folder.text() or str(self._default_dir)
        )
        if folder:
            self.le_folder.setText(folder)

    def selection(self) -> dict:
        what = "panel" if self.rb_panel.isChecked() else (
            "window" if self.rb_window.isChecked() else "screenshot"
        )
        wh = (int(self.sp_w.value()), int(self.sp_h.value()))
        folder = Path(self.le_folder.text().strip() or self._default_dir)
        # Make sure the folder exists; we'll write into it.
        folder.mkdir(parents=True, exist_ok=True)
        name = self.le_name.text().strip() or "vna_export"
        fmt = self.cb_fmt.currentText().lower()
        # Strip any extension the user typed and re-apply the chosen one.
        stem = Path(name).stem or "vna_export"
        path = folder / f"{stem}.{fmt}"
        return {
            "what": what,
            "panel": self.cb_panel.currentText(),
            "size": wh,
            "path": str(path),
            "fmt": fmt,
        }

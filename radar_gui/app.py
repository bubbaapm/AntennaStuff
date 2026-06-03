"""QApplication bootstrap and shared visual theme."""
from __future__ import annotations

import sys

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


DARK_QSS = """
QWidget { background: #232629; color: #e7e7e7; }
QGroupBox {
    border: 1px solid #3e454b; margin-top: 10px; padding-top: 10px;
    color: #00e0b4; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidget, QListWidget {
    background: #181b1f; color: #f0f0f0; border: 1px solid #3e454b;
    padding: 3px; selection-background-color: #008a6e;
}
QPushButton {
    background: #00b894; color: #0a0a0a; border: none;
    padding: 6px 10px; font-weight: bold; border-radius: 4px;
}
QPushButton:hover { background: #00d1a8; }
QPushButton:disabled { background: #3a3f44; color: #888; }
QToolButton {
    background: #30363b; color: #e7e7e7; border: 1px solid #3e454b;
    padding: 4px 6px; border-radius: 3px;
}
QTabBar::tab {
    background: #30363b; color: #cfd3d6; padding: 8px 14px;
    border: 1px solid #3e454b; border-bottom: none;
}
QTabBar::tab:selected { background: #00b894; color: #0a0a0a; }
QStatusBar, QMenuBar, QMenu { background: #181b1f; color: #e7e7e7; }
QHeaderView::section {
    background: #30363b; color: #e7e7e7; padding: 4px; border: 1px solid #3e454b;
}
QSlider::groove:horizontal { background: #181b1f; height: 5px; }
QSlider::handle:horizontal { background: #00e0b4; width: 14px; margin: -5px 0; }
"""


def _apply_palette(app: QApplication) -> None:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#232629"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#e7e7e7"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#181b1f"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#30363b"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#e7e7e7"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#30363b"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#e7e7e7"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#00b894"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#0a0a0a"))
    app.setPalette(pal)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Radar VNA Workbench")
    app.setOrganizationName("AntennaStuff")
    app.setStyle("Fusion")
    _apply_palette(app)
    app.setStyleSheet(DARK_QSS)
    import pyqtgraph as pg

    pg.setConfigOption("background", "#111418")
    pg.setConfigOption("foreground", "#e7e7e7")

    from .main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec()

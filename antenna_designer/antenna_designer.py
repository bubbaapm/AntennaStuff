"""
Elite Antenna Designer — entry point.

Usage:
    python antenna_designer.py
"""
from __future__ import annotations
import os
import sys

# Make sibling packages (antennas, calculators, plotting, ui) importable when
# this script is run from an arbitrary cwd, or when frozen with PyInstaller.
if getattr(sys, "frozen", False):
    _HERE = os.path.dirname(sys.executable)
else:
    _HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt

from ui import MainWindow


DARK_QSS = """
QWidget { background: #242424; color: #e0e0e0; }
QTabWidget::pane { border: 1px solid #3a3a3a; }
QTabBar::tab {
    background: #2e2e2e; color: #c0c0c0;
    padding: 7px 14px; border: 1px solid #3a3a3a; border-bottom: none;
}
QTabBar::tab:selected { background: #00b894; color: #0a0a0a; font-weight: bold; }
QTabBar::tab:hover:!selected { background: #383838; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
    background: #1d1d1d; color: #e8e8e8;
    border: 1px solid #3a3a3a; padding: 4px; selection-background-color: #00b894;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #00e0b4; }
QPushButton {
    background: #00b894; color: #0a0a0a; border: none;
    padding: 7px 14px; font-weight: bold; border-radius: 4px;
}
QPushButton:hover  { background: #00d1a8; }
QPushButton:pressed{ background: #008a6e; }
QGroupBox {
    border: 1px solid #3a3a3a; margin-top: 8px; padding-top: 8px;
    color: #00e0b4; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QStatusBar, QMenuBar, QMenu { background: #1f1f1f; color: #e0e0e0; }
QMenuBar::item:selected, QMenu::item:selected { background: #00b894; color: #0a0a0a; }
QScrollBar:vertical {
    background: #1d1d1d; width: 12px; margin: 0;
}
QScrollBar::handle:vertical { background: #4a4a4a; border-radius: 3px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #00b894; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #1f1f1f; color: #e0e0e0; border: 1px solid #00e0b4; padding: 4px; }
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Fusion dark palette (backs up the QSS)
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,        QColor("#242424"))
    pal.setColor(QPalette.ColorRole.WindowText,    QColor("#e0e0e0"))
    pal.setColor(QPalette.ColorRole.Base,          QColor("#1d1d1d"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#2a2a2a"))
    pal.setColor(QPalette.ColorRole.Text,          QColor("#e0e0e0"))
    pal.setColor(QPalette.ColorRole.Button,        QColor("#2e2e2e"))
    pal.setColor(QPalette.ColorRole.ButtonText,    QColor("#e0e0e0"))
    pal.setColor(QPalette.ColorRole.Highlight,     QColor("#00b894"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#0a0a0a"))
    pal.setColor(QPalette.ColorRole.ToolTipBase,   QColor("#1f1f1f"))
    pal.setColor(QPalette.ColorRole.ToolTipText,   QColor("#e0e0e0"))
    app.setPalette(pal)
    app.setStyleSheet(DARK_QSS)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

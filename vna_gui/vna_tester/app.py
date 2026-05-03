"""
QApplication setup, dark stylesheet, and main() entry point.
"""
from __future__ import annotations
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


# Same palette as the Antenna Designer so the two apps feel like a family.
DARK_QSS = """
QWidget { background: #242424; color: #e0e0e0; }
QGroupBox {
    border: 1px solid #3a3a3a; margin-top: 10px; padding-top: 10px;
    color: #00e0b4; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QListWidget,
QTableWidget, QPlainTextEdit {
    background: #1d1d1d; color: #e8e8e8; border: 1px solid #3a3a3a;
    padding: 3px; selection-background-color: #00b894;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #00e0b4;
}
QComboBox::drop-down { border: none; width: 18px; }
QPushButton {
    background: #00b894; color: #0a0a0a; border: none;
    padding: 6px 12px; font-weight: bold; border-radius: 4px;
}
QPushButton:hover  { background: #00d1a8; }
QPushButton:pressed{ background: #008a6e; }
QPushButton:disabled { background: #3a3a3a; color: #888; }
QToolButton {
    background: #2e2e2e; color: #e0e0e0; border: 1px solid #3a3a3a;
    padding: 3px 6px; border-radius: 3px;
}
QToolButton:hover { background: #383838; border-color: #00e0b4; }
QStatusBar, QMenuBar, QMenu { background: #1f1f1f; color: #e0e0e0; }
QMenuBar::item:selected, QMenu::item:selected { background: #00b894; color: #0a0a0a; }
QTabWidget::pane { border: 1px solid #3a3a3a; }
QTabBar::tab {
    background: #2e2e2e; color: #c0c0c0;
    padding: 7px 14px; border: 1px solid #3a3a3a; border-bottom: none;
}
QTabBar::tab:selected { background: #00b894; color: #0a0a0a; font-weight: bold; }
QTabBar::tab:hover:!selected { background: #383838; }
QScrollBar:vertical { background: #1d1d1d; width: 12px; margin: 0; }
QScrollBar::handle:vertical {
    background: #4a4a4a; border-radius: 3px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #00b894; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #1d1d1d; height: 12px; margin: 0; }
QScrollBar::handle:horizontal {
    background: #4a4a4a; border-radius: 3px; min-width: 20px;
}
QScrollBar::handle:horizontal:hover { background: #00b894; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QToolTip {
    background: #1f1f1f; color: #e0e0e0;
    border: 1px solid #00e0b4; padding: 5px;
}
QHeaderView::section {
    background: #2e2e2e; color: #e0e0e0;
    padding: 4px; border: 1px solid #3a3a3a; font-weight: bold;
}
QListWidget::item:selected, QTableWidget::item:selected {
    background: #008a6e; color: #ffffff;
}
QProgressBar {
    border: 1px solid #3a3a3a; background: #1d1d1d; text-align: center;
    color: #e0e0e0;
}
QProgressBar::chunk { background: #00b894; }
QRadioButton, QCheckBox { color: #e0e0e0; }
QRadioButton::indicator, QCheckBox::indicator {
    width: 14px; height: 14px;
}
"""


def _apply_palette(app: QApplication) -> None:
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
    pal.setColor(QPalette.ColorRole.Link,          QColor("#00e0b4"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#888888"))
    app.setPalette(pal)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("VNA Tester")
    app.setOrganizationName("AntennaStuff")
    app.setStyle("Fusion")
    _apply_palette(app)
    app.setStyleSheet(DARK_QSS)

    # Import lazily so a syntax error in a UI module shows on stderr.
    from .ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec()

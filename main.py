"""Coc-Bot: start the window.  Run:  python main.py"""

import os
import sys

os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot  # noqa: E402,F401  (sets DPI awareness before Qt starts)
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.main_window import MainWindow  # noqa: E402

STYLE = """
QWidget { font-size: 10pt; }
QGroupBox { font-weight: bold; border: 1px solid #ccd; border-radius: 6px; margin-top: 10px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QPushButton { padding: 6px 12px; }
QPushButton#start { background: #2e9d4f; color: white; font-weight: bold; border-radius: 5px; }
QPushButton#start:disabled { background: #9cc9a9; }
QPushButton#stop { background: #c94040; color: white; font-weight: bold; border-radius: 5px; }
QPushButton#stop:disabled { background: #e0a8a8; }
QTabBar::tab { padding: 8px 16px; }
"""


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

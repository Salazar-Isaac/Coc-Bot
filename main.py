"""Coc-Bot: start the window.  Run:  python main.py"""

import ctypes
import importlib
import os
import sys

os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

importlib.import_module("bot")  # sets DPI awareness before Qt starts
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui import theme  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402


def apply_theme(app):
    """Dark theme, fonts, style sheet and app icon (also used by off-screen UI checks)."""
    theme.apply_theme(app)


def main():
    try:   # own taskbar group + icon instead of python.exe's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CocBot.Window")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("Coc-Bot")
    apply_theme(app)
    w = MainWindow()
    w.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

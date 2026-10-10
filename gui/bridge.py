"""Thread-safe link between the bot thread and the window (Qt signals), plus hotkeys."""

import logging
import os
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, Signal

from bot import paths


class Bridge(QObject):
    log = Signal(str, int)          # message, level
    status = Signal(dict)
    finished = Signal(str)          # "finished" / "stopped" / "error"
    hotkey = Signal(str)            # "continue" / "pause" / "stop"
    task_done = Signal(str, object)  # background helper results (name, result)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.bridge.log.emit(msg, record.levelno)
        except Exception:  # noqa: BLE001
            pass


def setup_logging(bridge):
    log = logging.getLogger("bot")
    log.setLevel(logging.DEBUG)
    ui = QtLogHandler(bridge)
    ui.setLevel(logging.INFO)
    log.addHandler(ui)
    f = RotatingFileHandler(os.path.join(paths.LOGS, "bot.log"), maxBytes=2_000_000, backupCount=3,
                            encoding="utf-8")
    f.setLevel(logging.DEBUG)
    f.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(f)


class Hotkeys:
    """Global F8/F9/F10 (configurable) that work while the game is in front."""

    def __init__(self, bridge):
        self.bridge = bridge
        self._listener = None

    def start(self, keys):
        from pynput import keyboard

        self.stop()
        mapping = {}
        for action in ("continue", "pause", "stop"):
            k = (keys.get(action) or "").strip().lower()
            if k:
                mapping[f"<{k}>" if len(k) > 1 else k] = (lambda a=action: self.bridge.hotkey.emit(a))
        if mapping:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

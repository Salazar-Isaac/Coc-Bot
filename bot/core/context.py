"""The bot context: one object every action and mode works with.

It wraps the device with Stop/Pause checks, gives "wait for this screen" helpers
that always time out (no endless loops), and keeps status for the window.
"""

import logging
import os
import random
import time
from datetime import datetime

import cv2

from .. import paths
from . import vision
from .control import control
from .layout import layout

log = logging.getLogger("bot")


class BotError(Exception):
    """Something went wrong that the mode can recover from (usually by going home)."""


class Bot:
    def __init__(self, device, settings, accounts, on_status=None):
        self.device = device
        self.settings = settings
        self.accounts = accounts
        self.layout = layout
        self.frame = None
        self.on_status = on_status or (lambda **kw: None)
        self.current_account = None
        self.stats = {"attacks": 0, "searches": 0, "loot": {"gold": 0, "elixir": 0, "dark": 0}}

    # --- status --------------------------------------------------------------------------
    def status(self, **fields):
        counters = {k: v for k, v in self.stats.items() if isinstance(v, int)}
        self.on_status(stats=counters, **fields)

    # --- screen ----------------------------------------------------------------------------
    def shot(self):
        control.checkpoint()
        self.frame = self.device.capture()
        return self.frame

    def find(self, key, fresh=True, **kw):
        if not vision.templates.has(key):
            return None
        frame = self.shot() if fresh or self.frame is None else self.frame
        return vision.find(frame, key, **kw)

    def exists(self, key, fresh=True, **kw):
        return self.find(key, fresh=fresh, **kw) is not None

    def wait_any(self, keys, timeout=15.0, interval=0.4):
        """Wait until one of the templates appears. Returns (key, match) or (None, None)."""
        keys = [k for k in ([keys] if isinstance(keys, str) else keys) if vision.templates.has(k)]
        end = time.monotonic() + timeout
        while True:
            frame = self.shot()
            for k in keys:
                m = vision.find(frame, k)
                if m:
                    return k, m
            if time.monotonic() >= end:
                return None, None
            control.sleep(interval)

    def wait(self, key, timeout=15.0, interval=0.4):
        return self.wait_any([key], timeout, interval)[1]

    def wait_gone(self, key, timeout=15.0, interval=0.4):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self.find(key):
                return True
            control.sleep(interval)
        return False

    # --- input -----------------------------------------------------------------------------
    def tap(self, x, y, jitter=3, times=1, interval=0.08):
        for i in range(times):
            control.checkpoint()
            if i:
                time.sleep(interval)
            j = jitter
            self.device.tap(x + (random.randint(-j, j) if j else 0), y + (random.randint(-j, j) if j else 0))

    def tap_point(self, name, **kw):
        x, y = self.layout.point(name)
        self.tap(x, y, **kw)

    def tap_match(self, m, **kw):
        self.tap(m.x, m.y, **kw)

    def tap_template(self, key, timeout=10.0, after=0.4):
        """Wait for a template and tap it. Returns True if it was tapped."""
        m = self.wait(key, timeout)
        if not m:
            return False
        self.tap_match(m)
        control.sleep(after)
        return True

    def swipe(self, a, b, ms=500):
        control.checkpoint()
        self.device.swipe(a[0], a[1], b[0], b[1], ms)

    def key(self, k):
        control.checkpoint()
        return self.device.key(k)

    def sleep(self, seconds):
        control.sleep(seconds)

    # --- reading ---------------------------------------------------------------------------
    def read_number(self, region_name, retries=3, frame=None):
        """Read a number in a named region; retries on a new frame if unreadable."""
        region = self.layout.region(region_name)
        for attempt in range(retries):
            f = frame if (frame is not None and attempt == 0) else self.shot()
            value = vision.digits.read(f, region)
            if value is not None:
                return value
            control.sleep(0.3)
        return None

    # --- diagnostics -------------------------------------------------------------------------
    def save_error(self, label):
        if not self.settings.get("save_error_screenshots", True):
            return None
        try:
            frame = self.device.capture()
        except Exception:
            return None
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{label}.png"
        path = os.path.join(paths.ERROR_SHOTS, name)
        cv2.imencode(".png", frame)[1].tofile(path)
        log.info("Saved screenshot logs/errors/%s", name)
        return path

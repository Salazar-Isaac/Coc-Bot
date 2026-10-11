"""Device backends: where screenshots come from and where taps go.

  PcDevice   Google Play Games on Windows (PrintWindow capture + real mouse/keyboard)
  AdbDevice  Any Android over ADB: BlueStacks, LDPlayer, MuMu, Nox or a USB/Wi-Fi phone

The bot works in "game space" (see space.py): the device image scaled uniformly
to the profile's height (1080), so any window size or aspect ratio works.
"""

import logging
import shutil
import subprocess
import threading
import time

import cv2
import numpy as np
import win32api

from .space import space
from .window import GameWindow

log = logging.getLogger("bot")

COC_PACKAGE = "com.supercell.clashofclans"


class Device:
    kind = "device"
    supports_keys = False

    def __init__(self):
        self._native = None   # (w, h)

    # --- implemented by backends (native pixels) ------------------------------------
    def _capture_native(self):
        raise NotImplementedError

    def _tap_native(self, x, y):
        raise NotImplementedError

    def _swipe_native(self, x1, y1, x2, y2, ms):
        raise NotImplementedError

    def key(self, name):
        """Press a key. Returns False if this device has no keyboard."""
        return False

    def type_text(self, text):
        """Type text into the focused text box."""
        return False

    def zoom_out(self):
        raise NotImplementedError

    def prepare(self):
        """Called before every input; e.g. bring the window to the front."""

    def is_connected(self):
        return True

    def is_game_running(self):
        raise NotImplementedError

    def launch_game(self):
        raise NotImplementedError

    def close_game(self):
        raise NotImplementedError

    def describe(self):
        return self.kind

    # --- game-space API used by the bot ------------------------------------------------
    def capture(self):
        frame = self._capture_native()
        h, w = frame.shape[:2]
        self._native = (w, h)
        gw, gh = space.update(w, h)
        if (w, h) != (gw, gh):
            interp = cv2.INTER_AREA if w > gw else cv2.INTER_LINEAR
            frame = cv2.resize(frame, (gw, gh), interpolation=interp)
        return frame

    def native_size(self):
        if self._native is None:
            self.capture()
        return self._native

    def to_native(self, x, y):
        self.native_size()
        return round(x * space.scale), round(y * space.scale)

    def tap(self, x, y):
        self.prepare()
        self._tap_native(*self.to_native(x, y))

    def swipe(self, x1, y1, x2, y2, ms=500):
        self.prepare()
        a, b = self.to_native(x1, y1)
        c, d = self.to_native(x2, y2)
        self._swipe_native(a, b, c, d, ms)


# =============================================================================
# Google Play Games (Windows)
# =============================================================================

class PcDevice(Device):
    kind = "pc"
    supports_keys = True

    def __init__(self, shortcut_path="", title_prefix="Clash of Clans"):
        super().__init__()
        import pyautogui
        from pynput.keyboard import Controller, Key

        pyautogui.PAUSE = 0.05
        pyautogui.FAILSAFE = True   # slam the mouse into a screen corner to abort
        self._pg = pyautogui
        self._kb = Controller()
        self._Key = Key
        self.window = GameWindow(title_prefix, shortcut_path)
        self._viewport = None        # (x, y, w, h) of the game inside the window's client area
        self._viewport_for = None    # client size it was measured for

    def describe(self):
        return "Google Play Games (PC)"

    @staticmethod
    def find_viewport(img):
        """The game picture inside the window. In windowed mode Google Play Games draws its
        own dark title bar and sidebar inside the client area; strip those off."""
        h, w = img.shape[:2]
        dark = img.max(axis=2) < 45
        col = dark[h // 6: h * 5 // 6].mean(axis=0)
        row = dark[:, w // 6: w * 5 // 6].mean(axis=1)

        def edge(fr, limit, rev=False):
            idx = range(len(fr) - 1, len(fr) - 1 - limit, -1) if rev else range(limit)
            n = 0
            for i in idx:
                if fr[i] < 0.8:
                    break
                n += 1
            return n

        left, right = edge(col, w // 4), edge(col, w // 4, rev=True)
        top, bottom = edge(row, h // 4), edge(row, h // 4, rev=True)
        left, right = (left if left >= 30 else 0), (right if right >= 30 else 0)    # sidebar is ~80 px
        top, bottom = (top if top >= 20 else 0), (bottom if bottom >= 20 else 0)    # title bar ~45 px
        vw, vh = w - left - right, h - top - bottom
        if vw < w * 0.5 or vh < h * 0.5 or not (1.2 <= vw / vh <= 2.4):
            return 0, 0, w, h
        return left, top, vw, vh

    def _screen(self, x, y):
        left, top, _, _ = self.window.client_rect()
        vx, vy = (self._viewport or (0, 0, 0, 0))[:2]
        return left + vx + x, top + vy + y

    def prepare(self):
        if not self.window.is_foreground():
            self.window.focus()

    def _capture_native(self):
        img = self.window.capture()
        h, w = img.shape[:2]
        # (re)measure the game area when the window size changes; skip dark frames
        # (loading / black screens) so a black picture is not mistaken for chrome
        if self._viewport_for != (w, h) and img.mean() > 40:
            sw, sh = win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)
            # fullscreen has no Google Play Games chrome; only windowed mode does
            self._viewport = (0, 0, w, h) if (w, h) == (sw, sh) else self.find_viewport(img)
            self._viewport_for = (w, h)
            if self._viewport != (0, 0, w, h):
                log.info("Game area inside the window: %s (window %dx%d)", self._viewport, w, h)
        if self._viewport_for != (w, h) or not self._viewport:
            return img
        x, y, vw, vh = self._viewport
        return img[y:y + vh, x:x + vw]

    def _tap_native(self, x, y):
        self._pg.click(*self._screen(x, y))

    def _swipe_native(self, x1, y1, x2, y2, ms):
        self._pg.moveTo(*self._screen(x1, y1))
        self._pg.mouseDown()
        try:
            time.sleep(0.08)
            self._pg.moveTo(*self._screen(x2, y2), duration=ms / 1000)
            time.sleep(0.08)
        finally:
            self._pg.mouseUp()

    def key(self, name):
        self.prepare()
        k = getattr(self._Key, name) if len(name) > 1 else name
        self._kb.press(k)
        self._kb.release(k)
        return True

    def type_text(self, text):
        self.prepare()
        self._kb.type(text)
        return True

    def zoom_out(self, steps=10):
        self.prepare()
        w, h = self.native_size()
        self._pg.moveTo(*self._screen(w // 2, h // 2))
        for _ in range(steps):
            self._pg.scroll(-500)
            time.sleep(0.03)

    def is_connected(self):
        return True

    def is_game_running(self):
        return self.window.find() is not None

    def launch_game(self):
        self.window.launch()

    def close_game(self):
        self.window.close()

    def focus(self):
        return self.window.focus()


# =============================================================================
# ADB (emulators and phones)
# =============================================================================

def find_adb(preferred=""):
    for p in (preferred, shutil.which("adb"), r"C:\platform-tools\adb.exe", r"C:\scrcpy\adb.exe"):
        if p and shutil.which(p):
            return shutil.which(p)
    return None


def list_adb_devices(adb):
    out = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=10).stdout
    return [line.split("\t")[0] for line in out.splitlines()[1:] if line.strip().endswith("\tdevice")]


# Common emulator ADB addresses, for the "Detect" button in Settings.
EMULATOR_PORTS = {
    "BlueStacks 5": "127.0.0.1:5555",
    "LDPlayer 9": "127.0.0.1:5555",
    "MuMu 12": "127.0.0.1:16384",
    "MuMu 6": "127.0.0.1:7555",
    "Nox": "127.0.0.1:62001",
    "MEmu": "127.0.0.1:21503",
}

ANDROID_KEYS = {"back": 4, "esc": 4, "home": 3, "enter": 66, "space": 62, "backspace": 67, "end": 123}


class AdbDevice(Device):
    """Android over ADB. Touches use a persistent `adb shell`; zoom-out uses a
    two-finger pinch through the scrcpy server when scrcpy is available."""

    kind = "adb"

    def __init__(self, serial, adb_path="", scrcpy_dir=r"C:\scrcpy", package=COC_PACKAGE):
        super().__init__()
        self.adb = find_adb(adb_path)
        if not self.adb:
            raise RuntimeError("adb.exe not found (set its path in Settings)")
        self.serial = serial
        self.package = package
        self.scrcpy_dir = scrcpy_dir
        self._shell = None
        self._lock = threading.Lock()
        self._touch = None          # ScrcpyTouch, created on first pinch
        self.connect()

    def describe(self):
        return f"ADB {self.serial}"

    # --- plumbing ---------------------------------------------------------------------
    def _run(self, *args, timeout=15, binary=False):
        cmd = [self.adb, "-s", self.serial, *args]
        r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.stdout if binary else r.stdout.decode(errors="replace")

    def connect(self):
        if ":" in self.serial:   # network device / emulator
            subprocess.run([self.adb, "connect", self.serial], capture_output=True, timeout=15,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if self.serial not in list_adb_devices(self.adb):
            raise RuntimeError(f"ADB device {self.serial} is not connected")

    def is_connected(self):
        try:
            return self.serial in list_adb_devices(self.adb)
        except Exception:
            return False

    def _sh(self, command):
        """Run a command in a long-lived `adb shell` (no process start-up cost per tap)."""
        with self._lock:
            if self._shell is None or self._shell.poll() is not None:
                self._shell = subprocess.Popen(
                    [self.adb, "-s", self.serial, "shell"], stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            self._shell.stdin.write((command + "\n").encode())
            self._shell.stdin.flush()

    # --- device API ----------------------------------------------------------------------
    def _capture_native(self):
        raw = self._run("exec-out", "screencap", binary=True, timeout=20)
        if len(raw) < 16:
            raise RuntimeError("screencap returned no data")
        w = int.from_bytes(raw[0:4], "little")
        h = int.from_bytes(raw[4:8], "little")
        header = len(raw) - w * h * 4          # 12 bytes on old Android, 16 on Android 10+
        rgba = np.frombuffer(raw, dtype=np.uint8, offset=header).reshape(h, w, 4)
        return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)

    def _tap_native(self, x, y):
        self._sh(f"input tap {x} {y}")
        time.sleep(0.05)

    def _swipe_native(self, x1, y1, x2, y2, ms):
        self._sh(f"input swipe {x1} {y1} {x2} {y2} {int(ms)}")
        time.sleep(ms / 1000 + 0.1)

    def key(self, name):
        code = ANDROID_KEYS.get(name)
        if code is None:
            return False
        self._sh(f"input keyevent {code}")
        return True

    def type_text(self, text):
        safe = "".join(ch if ch.isalnum() else ("%s" if ch == " " else "") for ch in text)
        if safe:
            self._sh(f"input text '{safe}'")
        return True

    def zoom_out(self, steps=3):
        from .scrcpy_touch import ScrcpyTouch
        try:
            if self._touch is None:
                self._touch = ScrcpyTouch(self.adb, self.serial, self.scrcpy_dir)
            w, h = self.native_size()
            for _ in range(steps):
                self._touch.pinch_in(w // 2, h // 2, start=int(h * 0.42), end=int(h * 0.05), native=(w, h))
                time.sleep(0.2)
        except Exception as e:
            log.warning("Zoom-out over ADB failed (%s). Zoom out manually once; the game keeps it.", e)
            self._touch = None

    def is_game_running(self):
        return bool(self._run("shell", "pidof", self.package).strip())

    def launch_game(self):
        self._run("shell", "monkey", "-p", self.package, "-c", "android.intent.category.LAUNCHER", "1")

    def close_game(self):
        self._run("shell", "am", "force-stop", self.package)

    def close(self):
        if self._touch:
            self._touch.close()
        if self._shell and self._shell.poll() is None:
            self._shell.kill()


def make_device(settings):
    """Create the device chosen in Settings."""
    d = settings["device"]
    if d["type"] == "adb":
        return AdbDevice(d["adb_serial"], d.get("adb_path", ""), d.get("scrcpy_dir", r"C:\scrcpy"))
    return PcDevice(d.get("shortcut_path", ""), d.get("window_title", "Clash of Clans"))

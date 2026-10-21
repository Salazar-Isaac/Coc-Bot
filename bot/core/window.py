"""Win32 helpers: find, focus, launch, capture and send input to the PC game window."""

import ctypes
import os
import time

import numpy as np
import win32api
import win32con
import win32gui
import win32process
import win32ui

PW_CLIENTONLY_FULLCONTENT = 3  # PW_CLIENTONLY | PW_RENDERFULLCONTENT


def bring_to_front(hwnd):
    """Make `hwnd` the foreground window. Returns True on success."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.4)
    if win32gui.GetForegroundWindow() != hwnd:
        # Windows only lets the foreground process hand over focus; a synthetic
        # Alt press lifts that restriction for our process.
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        finally:
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.15)
    return win32gui.GetForegroundWindow() == hwnd


def capture_window(hwnd):
    """Client area of `hwnd` as a BGR array. Works even when other windows cover it."""
    _, _, w, h = win32gui.GetClientRect(hwnd)
    if w <= 0 or h <= 0:
        raise RuntimeError("Game window is minimized")
    hdc = win32gui.GetWindowDC(hwnd)
    mfc = win32ui.CreateDCFromHandle(hdc)
    mem = mfc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    try:
        bmp.CreateCompatibleBitmap(mfc, w, h)
        mem.SelectObject(bmp)
        ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), PW_CLIENTONLY_FULLCONTENT)
        raw = bmp.GetBitmapBits(True)
        return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)[:, :, :3].copy()
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mem.DeleteDC()
        mfc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hdc)


class GameWindow:
    def __init__(self, title_prefix="Clash of Clans", shortcut_path=""):
        self.title_prefix = title_prefix
        self.shortcut_path = shortcut_path
        self._hwnd = None

    def find(self):
        if self._hwnd and win32gui.IsWindow(self._hwnd):
            return self._hwnd
        found = []

        def cb(h, _):
            if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h).startswith(self.title_prefix):
                found.append(h)

        win32gui.EnumWindows(cb, None)
        self._hwnd = found[0] if found else None
        return self._hwnd

    def require(self):
        hwnd = self.find()
        if not hwnd:
            raise RuntimeError(f"Window '{self.title_prefix}' not found")
        return hwnd

    def client_rect(self):
        """(left, top, width, height) of the client area in screen pixels."""
        hwnd = self.require()
        _, _, w, h = win32gui.GetClientRect(hwnd)
        x, y = win32gui.ClientToScreen(hwnd, (0, 0))
        return x, y, w, h

    def is_foreground(self):
        return self.find() is not None and win32gui.GetForegroundWindow() == self._hwnd

    def focus(self):
        return bring_to_front(self.find())

    @staticmethod
    def _packed_point(x, y):
        packed = (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
        return ctypes.c_int32(packed).value

    def _input_target(self, x, y):
        """Return the deepest child window at a client-area point and its client coordinates."""
        hwnd = self.require()
        screen_point = win32gui.ClientToScreen(hwnd, (int(x), int(y)))
        target = hwnd
        point = (int(x), int(y))
        flags = (win32con.CWP_SKIPINVISIBLE | win32con.CWP_SKIPDISABLED |
                 win32con.CWP_SKIPTRANSPARENT)
        while True:
            child = win32gui.ChildWindowFromPointEx(target, point, flags)
            if child == target:
                break
            target = child
            point = win32gui.ScreenToClient(target, screen_point)
        return target, point, screen_point

    def post_mouse(self, message, x, y, buttons=0):
        """Post a client-coordinate mouse message without moving or clicking the system cursor."""
        target, point, _ = self._input_target(x, y)
        win32gui.PostMessage(target, message, buttons, self._packed_point(*point))

    def post_mouse_wheel(self, x, y, delta):
        """Post a wheel message to the game window; wheel coordinates are screen-relative."""
        target, _, screen_point = self._input_target(x, y)
        wparam = (int(delta) & 0xFFFF) << 16
        win32gui.PostMessage(target, win32con.WM_MOUSEWHEEL, wparam,
                             self._packed_point(*screen_point))

    def post_key(self, key, key_up=False, point=None):
        """Post a key message to the game window without changing foreground focus."""
        target = self.require()
        if point is not None:
            target, _, _ = self._input_target(*point)
        scan = win32api.MapVirtualKey(key, 0)
        lparam = 1 | (scan << 16)
        message = win32con.WM_KEYDOWN
        if key_up:
            lparam |= (1 << 30) | (1 << 31)
            message = win32con.WM_KEYUP
        win32gui.PostMessage(target, message, key, lparam)

    def post_char(self, char, point=None):
        """Post one UTF-16 character to the game window."""
        target = self.require()
        if point is not None:
            target, _, _ = self._input_target(*point)
        win32gui.PostMessage(target, win32con.WM_CHAR, char, 1)

    def capture(self):
        return capture_window(self.require())

    def launch(self):
        if not self.shortcut_path or not os.path.exists(self.shortcut_path):
            raise RuntimeError(f"Game shortcut not found: {self.shortcut_path!r} (set it in Settings)")
        os.startfile(self.shortcut_path)

    def close(self):
        hwnd = self.find()
        if hwnd:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        self._hwnd = None


STORE_TITLE = "Google Play Games"


def close_store_window():
    """Starting the game through Google Play Games also opens its store window (client.exe).
    Close that window only - the game itself runs in its own window and keeps running.
    Returns how many windows were closed."""
    import psutil
    found = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == STORE_TITLE:
            try:
                name = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower()
            except Exception:  # noqa: BLE001 - the process just ended
                return
            if name == "client.exe":
                found.append(hwnd)

    win32gui.EnumWindows(cb, None)
    for hwnd in found:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    return len(found)

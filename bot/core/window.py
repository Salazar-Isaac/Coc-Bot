"""Win32 helpers: find, focus, launch and capture a window (used by the PC device)."""

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


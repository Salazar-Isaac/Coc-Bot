"""Check that Coc-Bot is ready to run, and optionally create a desktop shortcut.

    python tools/check_setup.py            check everything
    python tools/check_setup.py --shortcut also put a "Coc-Bot" shortcut on the desktop
"""

import importlib
import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

OK, WARN, FAIL = "  OK  ", " WARN ", " FAIL "
problems = 0


def line(tag, text):
    global problems
    if tag == FAIL:
        problems += 1
    print(f"[{tag}] {text}")


def check_python():
    v = sys.version_info
    if platform.system() != "Windows":
        line(FAIL, f"Windows is required (this is {platform.system()})")
    if v < (3, 9):
        line(FAIL, f"Python {v.major}.{v.minor} is too old: install Python 3.10 or newer")
    else:
        line(OK, f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")


def check_packages():
    mods = [("PySide6", "PySide6"), ("cv2", "opencv-python"), ("numpy", "numpy"), ("pyautogui", "pyautogui"),
            ("pynput", "pynput"), ("win32gui", "pywin32"), ("rapidocr_onnxruntime", "rapidocr_onnxruntime")]
    for mod, pkg in mods:
        try:
            m = importlib.import_module(mod)
            line(OK, f"{pkg} {getattr(m, '__version__', '')}".rstrip())
        except Exception as e:  # noqa: BLE001
            line(FAIL, f"{pkg} missing or broken ({e}). Run setup.bat again.")


def check_ocr():
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
        t = time.perf_counter()
        RapidOCR()(np.full((40, 120, 3), 255, np.uint8))
        line(OK, f"Text reader (RapidOCR) loads in {time.perf_counter() - t:.1f} s - no PaddleOCR needed")
    except Exception as e:  # noqa: BLE001
        line(FAIL, f"Text reader does not start: {e}")


def check_bot_files():
    import bot  # noqa: F401  (DPI awareness)
    from bot import catalog, config
    from bot.core import vision
    from bot.core.profile import profile
    s = config.load_settings()
    profile.use(s.get("profile", profile.name))
    vision.templates.reload()
    missing = [k for k in catalog.REQUIRED if not vision.templates.has(k)]
    if missing:
        line(WARN, f"Templates not captured yet ({len(missing)}): capture them on the Templates page")
    else:
        line(OK, f"All {len(catalog.REQUIRED)} required templates captured (profile {profile.name})")
    vision.digits.reload()
    line(OK if vision.digits.ready else WARN,
         "Digit images complete" if vision.digits.ready else "Digit images missing: use Templates > Teach digits")
    accs = config.load_accounts()
    line(OK if accs else WARN, f"{len(accs)} accounts in the Accounts page" if accs
         else "No accounts yet: Accounts page > Read names from the game")
    d = s["device"]
    if d["type"] == "pc":
        p = d.get("shortcut_path", "")
        line(OK if os.path.exists(p) else WARN,
             f"Game shortcut found: {p}" if os.path.exists(p) else
             f"Game shortcut not found ({p or 'not set'}): set it on the Device page")
    else:
        from bot.core.devices import find_adb
        adb = find_adb(d.get("adb_path", ""))
        line(OK if adb else FAIL, f"adb: {adb}" if adb else "adb.exe not found: set its path on the Device page")


def check_display():
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        pass
    u = ctypes.windll.user32
    w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    dc = u.GetDC(0)
    dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
    u.ReleaseDC(0, dc)
    line(OK, f"Screen {w}x{h}, Windows scaling {round(dpi / 96 * 100)}% (any size works; 16:9 matches best)")


def make_shortcut():
    try:
        import win32com.client
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])  # noqa: F841
        from gui.theme import app_icon
        ico = os.path.join(ROOT, "gui", "assets", "coc-bot.ico")
        os.makedirs(os.path.dirname(ico), exist_ok=True)
        app_icon().pixmap(256, 256).save(ico, "ICO")
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        shell = win32com.client.Dispatch("WScript.Shell")
        desktop = shell.SpecialFolders("Desktop")
        lnk = shell.CreateShortcut(os.path.join(desktop, "Coc-Bot.lnk"))
        lnk.TargetPath = pythonw if os.path.exists(pythonw) else sys.executable
        lnk.Arguments = f'"{os.path.join(ROOT, "main.py")}"'
        lnk.WorkingDirectory = ROOT
        if os.path.exists(ico):
            lnk.IconLocation = ico
        lnk.Description = "Clash of Clans bot"
        lnk.Save()
        line(OK, f"Desktop shortcut created: {os.path.join(desktop, 'Coc-Bot.lnk')}")
    except Exception as e:  # noqa: BLE001
        line(WARN, f"Could not create the desktop shortcut ({e}); use run.bat instead")


def main():
    print("Coc-Bot setup check\n")
    check_python()
    check_packages()
    if problems == 0:
        check_ocr()
        check_bot_files()
        check_display()
        if "--shortcut" in sys.argv:
            make_shortcut()
    print()
    if problems:
        print(f"{problems} problem(s) found. Fix them and run setup.bat again.")
        return 1
    print("Ready. Start the bot with run.bat or the desktop shortcut.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

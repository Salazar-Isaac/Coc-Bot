"""Build the Windows desktop app as a self-contained onedir executable."""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist", "Coc-Bot")
STAGE = os.path.join(BUILD, "release")
ICON = os.path.join(BUILD, "coc-bot.ico")


def main():
    os.chdir(ROOT)
    os.makedirs(BUILD, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from gui.theme import app_icon

    app = QApplication.instance() or QApplication([])
    if not app_icon().pixmap(256, 256).save(ICON, "ICO"):
        raise RuntimeError(f"Could not generate the executable icon: {ICON}")

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onedir",
        "--contents-directory", ".",
        "--name", "Coc-Bot",
        "--distpath", STAGE,
        "--workpath", os.path.join(BUILD, "pyinstaller"),
        "--specpath", BUILD,
        "--icon", ICON,
        "--add-data", f"{os.path.join(ROOT, 'assets')};assets",
        "--add-data", f"{os.path.join(ROOT, 'gui', 'assets')};gui/assets",
        "--add-data", f"{ICON};gui/assets",
        "--collect-all", "rapidocr_onnxruntime",
        "--collect-all", "onnxruntime",
        os.path.join(ROOT, "main.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    staged_app = os.path.join(STAGE, "Coc-Bot")
    if os.path.isdir(DIST):
        for name in ("config", "logs"):
            source = os.path.join(DIST, name)
            if os.path.isdir(source):
                shutil.copytree(source, os.path.join(staged_app, name), dirs_exist_ok=True)
        profiles = os.path.join(DIST, "assets", "profiles")
        if os.path.isdir(profiles):
            shutil.copytree(profiles, os.path.join(staged_app, "assets", "profiles"),
                            dirs_exist_ok=True)

    config_out = os.path.join(staged_app, "config")
    os.makedirs(config_out, exist_ok=True)
    for name in ("settings.json", "accounts.json", "attack_plans.json"):
        source = os.path.join(ROOT, "config", name)
        destination = os.path.join(config_out, name)
        if os.path.isfile(source) and not os.path.exists(destination):
            shutil.copy2(source, destination)

    shutil.copytree(staged_app, DIST, dirs_exist_ok=True)

    print(f"\nBuilt app: {os.path.join(DIST, 'Coc-Bot.exe')}")


if __name__ == "__main__":
    main()

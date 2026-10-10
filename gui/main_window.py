"""Main window: tabs, settings persistence, starting/stopping the bot."""

import json
import logging
import os
import threading

import win32gui
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog, QMainWindow, QMessageBox, QTabWidget

from bot import config, paths
from bot.actions.account import scan_accounts
from bot.core import vision
from bot.core.context import Bot
from bot.core.control import control
from bot.core.devices import make_device
from bot.core.layout import layout
from bot.core.profile import profile
from bot.core.window import bring_to_front
from bot.modes.common import cancel_shutdown
from bot.runner import Runner, missing_templates
from gui.accounts_tab import AccountsTab
from gui.bridge import Bridge, Hotkeys, setup_logging
from gui.device_tab import DeviceTab
from gui.donate_tab import DonateTab
from gui.loot_tab import LootTab
from gui.run_tab import RunTab
from gui.templates_tab import TemplatesTab

log = logging.getLogger("bot")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Coc-Bot")
        self.resize(1280, 820)
        self.bridge = Bridge()
        setup_logging(self.bridge)
        self.settings = config.load_settings()
        self.accounts = config.load_accounts()
        profile.use(self.settings.get("profile", profile.name))
        vision.templates.reload()
        layout.reload()
        self.runner = None

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.run_tab = RunTab()
        self.accounts_tab = AccountsTab()
        self.loot_tab = LootTab()
        self.donate_tab = DonateTab()
        self.device_tab = DeviceTab()
        self.templates_tab = TemplatesTab()
        self.pages = [self.run_tab, self.accounts_tab, self.loot_tab, self.donate_tab, self.device_tab]
        self.tabs.addTab(self.run_tab, "Run")
        self.tabs.addTab(self.accounts_tab, "Accounts")
        self.tabs.addTab(self.loot_tab, "Loot Settings")
        self.tabs.addTab(self.donate_tab, "Donate")
        self.tabs.addTab(self.device_tab, "Device && Settings")
        self.tabs.addTab(self.templates_tab, "Templates")

        for p in self.pages:
            p.load(self.settings, self.accounts)
            p.changed.connect(self._schedule_save)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save)

        rt = self.run_tab
        rt.start_clicked.connect(self.start)
        rt.stop_clicked.connect(self.stop)
        rt.pause_clicked.connect(self.toggle_pause)
        rt.continue_clicked.connect(self.continue_)
        rt.cancel_shutdown_clicked.connect(self._cancel_shutdown)
        self.accounts_tab.scan_requested.connect(self.scan_accounts)
        self.device_tab.test_requested.connect(self.test_device)
        self.device_tab.new_profile_requested.connect(self.new_profile)
        self.templates_tab.screenshot_requested.connect(self.take_screenshot)

        self.bridge.log.connect(rt.append_log)
        self.bridge.status.connect(rt.update_status)
        self.bridge.finished.connect(self._finished)
        self.bridge.hotkey.connect(self._hotkey)
        self.bridge.task_done.connect(self._task_done)

        self.hotkeys = Hotkeys(self.bridge)
        self.hotkeys.start(self.settings["hotkeys"])
        log.info("Ready. Profile: %s. %s", profile.name,
                 "All required templates captured." if not missing_templates()
                 else f"Missing templates: {', '.join(missing_templates())}")

    # ----------------------------------------------------------------- settings
    def _schedule_save(self):
        self._save_timer.start(400)

    def collect(self):
        for p in self.pages:
            p.apply(self.settings, self.accounts)

    def save(self):
        self.collect()
        config.save_settings(self.settings)
        config.save_accounts(self.accounts)
        if profile.name != self.settings.get("profile"):
            profile.use(self.settings["profile"])
            vision.templates.reload()
            vision.digits.reload()
            layout.reload()
            self.templates_tab.refresh()
        self.run_tab.set_accounts(self.accounts)
        self.hotkeys.start(self.settings["hotkeys"])

    # ----------------------------------------------------------------- run control
    def _set_running(self, running):
        for p in (*self.pages, self.templates_tab):
            p.set_running(running) if hasattr(p, "set_running") else None
        self.run_tab.set_running(running)

    def start(self):
        if self.runner and self.runner.is_alive():
            return
        self.save()
        missing = missing_templates()
        if missing:
            QMessageBox.warning(self, "Templates missing",
                                "Capture these in the Templates tab first:\n\n" + "\n".join(missing))
            self.tabs.setCurrentWidget(self.templates_tab)
            return
        mode = self.settings["mode"]
        roles = [r for r, on in self.settings["loot"].get("roles", {}).items() if on]
        if mode == "loot_all" and not [a for a in self.accounts if a.get("enabled") and a.get("role") in roles]:
            QMessageBox.information(self, "No accounts", "Add your accounts in the Accounts tab first "
                                    "(or use \"Read names from the game\").")
            self.tabs.setCurrentWidget(self.accounts_tab)
            return
        self._set_running(True)
        status = lambda **kw: self.bridge.status.emit(kw)  # noqa: E731
        self.runner = Runner(mode, self.settings, self.accounts, status,
                             lambda reason: self.bridge.finished.emit(reason), resume=self.run_tab.resume.isChecked())
        self.bridge.status.emit({"device": "Google Play Games (PC)" if self.settings["device"]["type"] == "pc"
                                 else f"ADB {self.settings['device']['adb_serial']}"})
        self.runner.start()
        if self.settings.get("minimize_on_start") and self.settings["device"]["type"] == "pc":
            self.showMinimized()

    def stop(self):
        control.stop()

    def toggle_pause(self):
        if not (self.runner and self.runner.is_alive()):
            return
        control.toggle_pause()
        self.run_tab.set_paused(control.paused)
        log.info("Paused - you can use the game. Press Resume (F9) to continue." if control.paused else "Resumed")

    def continue_(self):
        control.resume_from_wait()

    def _hotkey(self, action):
        if action == "stop":
            self.stop()
        elif action == "pause":
            self.toggle_pause()
        elif action == "continue":
            self.continue_()

    def _finished(self, reason):
        self._set_running(False)
        config.save_accounts(self.accounts)     # Town Hall levels learned during the run
        self.accounts_tab.load(self.settings, self.accounts)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _cancel_shutdown(self):
        cancel_shutdown()
        self.run_tab.cancel_shutdown_btn.hide()
        log.info("Shutdown cancelled")

    # ----------------------------------------------------------------- helpers
    def _device(self):
        self.collect()
        return make_device(self.settings)

    def _run_task(self, name, fn):
        def work():
            try:
                result = fn()
            except Exception as e:  # noqa: BLE001
                log.exception("%s failed", name)
                result = e
            self.bridge.task_done.emit(name, result)
        threading.Thread(target=work, daemon=True).start()

    def _task_done(self, name, result):
        if isinstance(result, Exception):
            QMessageBox.warning(self, name, f"{name} failed:\n{result}")
            if name == "Read names":
                self._set_running(False)
            return
        if name == "Screenshot":
            self.templates_tab.set_frame(result)
        elif name == "Test connection":
            device, frame = result
            self.device_tab.test_result.setText(
                f"OK: {device.describe()}, screen {frame.shape[1]}x{frame.shape[0]} "
                f"(profile {profile.name} is {profile.width}x{profile.height})")
        elif name == "Read names":
            self._set_running(False)
            added = self.accounts_tab.merge_scanned(result)
            self.save()
            QMessageBox.information(self, "Accounts", f"Found {len(result)} accounts, added {added} new.")

    def take_screenshot(self):
        self._run_task("Screenshot", lambda: self._device().capture())

    def test_device(self):
        def work():
            d = self._device()
            return d, d.capture()
        self._run_task("Test connection", work)

    def scan_accounts(self):
        if self.runner and self.runner.is_alive():
            return
        self.save()
        missing = [k for k in ("home/attack_button", "home/settings_button", "settings/title",
                               "sid/switch_id_label") if not vision.templates.has(k)]
        if missing:
            QMessageBox.warning(self, "Templates missing", "Capture first:\n" + "\n".join(missing))
            return
        self._set_running(True)
        control.reset()
        previous = win32gui.GetForegroundWindow()

        def work():
            try:
                bot = Bot(make_device(self.settings), self.settings, self.accounts)
                return scan_accounts(bot)
            finally:
                bring_to_front(previous)
        self._run_task("Read names", work)

    def new_profile(self):
        name, ok = QInputDialog.getText(self, "New profile", "Name for the new profile (e.g. bluestacks-1600x900):")
        if not ok or not name.strip():
            return

        try:
            frame = self._device()._capture_native()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "New profile", f"Could not read the device screen:\n{e}")
            return
        d = os.path.join(paths.PROFILES, name.strip())
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "profile.json"), "w", encoding="utf-8") as f:
            json.dump({"width": frame.shape[1], "height": frame.shape[0]}, f)
        self.device_tab.reload_profiles(name.strip())
        self._schedule_save()
        QMessageBox.information(self, "New profile",
                                f"Profile '{name}' ({frame.shape[1]}x{frame.shape[0]}) created. Capture its "
                                "templates and digits in the Templates tab.")

    def closeEvent(self, e):
        if self.runner and self.runner.is_alive():
            if QMessageBox.question(self, "Quit", "The bot is running. Stop it and quit?") != QMessageBox.Yes:
                e.ignore()
                return
            control.stop()
            self.runner.join(5)
        self.save()
        self.hotkeys.stop()
        e.accept()

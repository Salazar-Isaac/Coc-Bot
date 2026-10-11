"""Main window: sidebar navigation, settings persistence, starting/stopping the bot."""

import json
import logging
import os
import threading

import win32gui
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup, Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow, QVBoxLayout,
                               QWidget)

from bot import config, paths
from bot.actions.account import scan_accounts
from bot.core import vision
from bot.core.context import Bot
from bot.core.control import control
from bot.core.devices import make_device
from bot.core.layout import layout
from bot.core.profile import profile
from bot.core.window import bring_to_front
from bot.modes import MODES
from bot.modes.common import cancel_shutdown
from bot.runner import Runner, missing_templates
from gui import theme as T
from gui.accounts_tab import AccountsTab
from gui.bridge import Bridge, Hotkeys, setup_logging
from gui.components import Pill, label
from gui.device_tab import DeviceTab
from gui.donate_tab import DonateTab
from gui.logs_tab import LogsTab
from gui.loot_tab import LootTab
from gui.nav import AnimatedStack, Sidebar
from gui.run_tab import RunTab
from gui.templates_tab import TemplatesTab
from gui.toast import ToastManager

log = logging.getLogger("bot")

# nav title, icon, page title, subtitle
PAGES = [
    ("Dashboard", "dashboard", "Dashboard", "Pick a mode, press Start and watch the bot work."),
    ("Accounts", "users", "Accounts", "Your Supercell ID accounts in switching order, with role and limits."),
    ("Loot", "swords", "Loot settings", "When an account is full, which bases to attack and how to attack."),
    ("Donate", "gift", "Donate", "Clan Castle requests and what your Main account donates."),
    ("Device", "monitor", "Device & settings", "Where the game runs, screen profile, hotkeys and behaviour."),
    ("Templates", "scan", "Templates", "Images the bot recognises. Re-capture one when Supercell changes a button."),
    ("Logs", "terminal", "Logs", "Everything the bot reported in this session."),
]


class Header(QWidget):
    """Page title + subtitle; on the right a 'locked while running' tag and an auto-save indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(30, 22, 30, 14)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = label("", "h1")
        self.title.setFont(T.font(19, QFont.DemiBold, display=True))
        self.subtitle = label("", "subtitle")
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        lay.addLayout(col, 1)
        self.lock = Pill("Locked while the bot runs", T.AMBER)
        self.lock.hide()
        lay.addWidget(self.lock, 0, Qt.AlignVCenter)
        self.saved = QLabel()
        self.saved.setTextFormat(Qt.RichText)
        self.saved.setText(f"<span style='color:{T.GREEN}; font-size:9pt; font-weight:600'>✓ Saved</span>")
        self._fx = QGraphicsOpacityEffect(self.saved)
        self._fx.setOpacity(0.0)
        self.saved.setGraphicsEffect(self._fx)
        lay.addWidget(self.saved, 0, Qt.AlignVCenter)
        self._flash = QSequentialAnimationGroup(self)
        fade_in = QPropertyAnimation(self._fx, b"opacity", self)
        fade_in.setDuration(180)
        fade_in.setEndValue(1.0)
        fade_out = QPropertyAnimation(self._fx, b"opacity", self)
        fade_out.setDuration(600)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._flash.addAnimation(fade_in)
        self._flash.addPause(1300)
        self._flash.addAnimation(fade_out)

    def set_page(self, title, subtitle):
        self.title.setText(title)
        self.subtitle.setText(subtitle)

    def flash_saved(self):
        self._flash.stop()
        self._flash.start()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Coc-Bot")
        self.setWindowIcon(T.app_icon())
        self._fit(1280, 820)
        self.setMinimumSize(1180, 700)
        self.bridge = Bridge()
        setup_logging(self.bridge)
        self.settings = config.load_settings()
        self.accounts = config.load_accounts()
        profile.use(self.settings.get("profile", profile.name))
        vision.templates.reload()
        layout.reload()
        self.runner = None
        self._wait_toast = None
        self._styled = False
        self._hotkeys_now = None
        self._unseen = 0
        self._unseen_level = 0
        self._running = False

        self.run_tab = RunTab()
        self.accounts_tab = AccountsTab()
        self.loot_tab = LootTab()
        self.donate_tab = DonateTab()
        self.device_tab = DeviceTab()
        self.templates_tab = TemplatesTab()
        self.logs_tab = LogsTab()
        self.pages = [self.run_tab, self.accounts_tab, self.loot_tab, self.donate_tab, self.device_tab]
        self.views = [*self.pages, self.templates_tab, self.logs_tab]

        # ---------------- layout: sidebar | header + animated pages ----------------
        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = Sidebar([(p[0], p[1]) for p in PAGES])
        h.addWidget(self.sidebar)
        content = QWidget()
        content.setObjectName("Content")
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = Header()
        v.addWidget(self.header)
        self.stack = AnimatedStack()
        for view in self.views:
            self.stack.addWidget(view)
        body = QVBoxLayout()
        body.setContentsMargins(30, 4, 30, 24)
        body.addWidget(self.stack)
        v.addLayout(body, 1)
        h.addWidget(content, 1)
        self.setCentralWidget(root)
        self.toasts = ToastManager(content)
        self.sidebar.nav.currentChanged.connect(self._nav)
        self._nav(0)
        for i in range(len(self.views)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.go(self.views[i]))

        for p in self.pages:
            p.load(self.settings, self.accounts)
            p.changed.connect(self._schedule_save)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._autosave)

        rt = self.run_tab
        rt.start_clicked.connect(self.start)
        rt.stop_clicked.connect(self.stop)
        rt.pause_clicked.connect(self.toggle_pause)
        rt.continue_clicked.connect(self.continue_)
        rt.cancel_shutdown_clicked.connect(self._cancel_shutdown)
        rt.show_log_clicked.connect(lambda: self.go(self.logs_tab))
        self.accounts_tab.scan_requested.connect(self.scan_accounts)
        self.accounts_tab.changed.connect(self._update_badges)
        self.device_tab.test_requested.connect(self.test_device)
        self.device_tab.new_profile_requested.connect(self.new_profile)
        self.donate_tab.templates_requested.connect(lambda: self.go(self.templates_tab))
        self.templates_tab.screenshot_requested.connect(self.take_screenshot)
        self.templates_tab.templates_changed.connect(self._update_badges)
        self.logs_tab.seen.connect(self._logs_seen)

        self.bridge.log.connect(rt.append_log)
        self.bridge.log.connect(self.logs_tab.append_log)
        self.bridge.log.connect(self._count_log)
        self.bridge.status.connect(rt.update_status)
        self.bridge.status.connect(self._on_status)
        self.bridge.finished.connect(self._finished)
        self.bridge.hotkey.connect(self._hotkey)
        self.bridge.task_done.connect(self._task_done)

        self.hotkeys = Hotkeys(self.bridge)
        self._start_hotkeys()
        self.templates_tab.set_extra_items(self.settings.get("donate", {}).get("items", []))
        self._update_badges()
        log.info("Ready. Profile: %s. %s", profile.name,
                 "All required templates captured." if not missing_templates()
                 else f"Missing templates: {', '.join(missing_templates())}")

    def _fit(self, w, h):
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w, h = min(w, avail.width() - 40), min(h, avail.height() - 40)
        self.resize(w, h)

    def showEvent(self, e):
        if not self._styled:
            self._styled = True
            T.style_window(self)
            QTimer.singleShot(700, self._warm_up)
        super().showEvent(e)

    def _warm_up(self, i=0):
        """Polish and lay out the hidden pages one by one in idle time, so the first visit is instant."""
        hidden = [v for v in self.views if v is not self.stack.currentWidget()]
        if i < len(hidden):
            hidden[i].grab()
            QTimer.singleShot(80, lambda: self._warm_up(i + 1))

    # ----------------------------------------------------------------- navigation
    def _nav(self, i):
        self.stack.slide_to(i)
        self.header.set_page(PAGES[i][2], PAGES[i][3])
        self._update_lock()

    def go(self, view):
        i = self.views.index(view)
        self.sidebar.nav.setCurrentIndex(i)
        self._nav(i)

    def _update_lock(self):
        self.header.lock.setVisible(self._running and self.stack.currentWidget() in self.pages[1:])

    def _update_badges(self):
        missing = len(missing_templates())
        self.sidebar.nav.set_badge(5, str(missing) if missing else "", T.RED)
        n = self.accounts_tab.count()
        self.sidebar.nav.set_badge(1, str(n) if n else "", T.TEXT_MUTED)

    def _count_log(self, _msg, level):
        if level >= logging.WARNING and self.stack.currentWidget() is not self.logs_tab:
            self._unseen += 1
            self._unseen_level = max(self._unseen_level, level)
            self.sidebar.nav.set_badge(6, str(min(self._unseen, 99)),
                                       T.RED if self._unseen_level >= logging.ERROR else T.AMBER)

    def _logs_seen(self):
        self._unseen = 0
        self._unseen_level = 0
        self.sidebar.nav.set_badge(6, "")

    # ----------------------------------------------------------------- settings
    def _schedule_save(self):
        self._save_timer.start(400)

    def _autosave(self):
        self.save(quiet=False)

    def collect(self):
        for p in self.pages:
            p.apply(self.settings, self.accounts)

    def save(self, quiet=True):
        self.collect()
        try:
            config.save_settings(self.settings)
            config.save_accounts(self.accounts)
        except OSError as e:
            log.warning("Could not save the settings: %s", e)
            self.toasts.show("error", "Settings not saved", str(e), 8000)
        else:
            if not quiet:
                self.header.flash_saved()
        if profile.name != self.settings.get("profile"):
            profile.use(self.settings["profile"])
            vision.templates.reload()
            vision.digits.reload()
            layout.reload()
            self.templates_tab.refresh()
        self.run_tab.set_accounts(self.accounts)
        self._start_hotkeys()
        self.templates_tab.set_extra_items(self.settings.get("donate", {}).get("items", []))
        self._update_badges()

    def _start_hotkeys(self):
        keys = dict(self.settings["hotkeys"])
        if keys != self._hotkeys_now:
            self._hotkeys_now = keys
            self.hotkeys.start(keys)
        self.run_tab.set_hotkeys(keys)
        self.sidebar.set_hotkeys(keys)

    # ----------------------------------------------------------------- run control
    def _set_running(self, running):
        self._running = running
        for p in (*self.pages, self.templates_tab):
            p.set_running(running) if hasattr(p, "set_running") else None
        self.run_tab.set_running(running)
        self._update_lock()

    def start(self):
        if self.runner and self.runner.is_alive():
            return
        self.save()
        missing = missing_templates()
        if missing:
            more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
            self.toasts.show("warning", "Templates missing", "Capture these on the Templates page first: "
                             + ", ".join(missing[:5]) + more + ".", 8000)
            self.templates_tab.show_missing()
            self.go(self.templates_tab)
            return
        mode = self.settings["mode"]
        roles = [r for r, on in self.settings["loot"].get("roles", {}).items() if on]
        if mode == "loot_all" and not [a for a in self.accounts if a.get("enabled") and a.get("role") in roles]:
            self.toasts.show("info", "No accounts to loot", "Add your accounts on the Accounts page (or use “Read "
                             "names from the game”) and check the roles ticked in Loot settings.", 7000)
            self.go(self.accounts_tab)
            return
        self._set_running(True)
        status = lambda **kw: self.bridge.status.emit(kw)  # noqa: E731
        self.runner = Runner(mode, self.settings, self.accounts, status,
                             lambda reason: self.bridge.finished.emit(reason), resume=self.run_tab.resume.isChecked())
        device = ("Google Play Games (PC)" if self.settings["device"]["type"] == "pc"
                  else f"ADB {self.settings['device']['adb_serial']}")
        self.bridge.status.emit({"device": device})
        self.runner.start()
        title = MODES[mode].title if mode in MODES else mode
        self.sidebar.status.set_state("running", title)
        self.sidebar.status.start_clock()
        self._update_lock()
        self.toasts.show("success", "Run started", f"{title} on {device}.", 3500)
        if self.settings.get("minimize_on_start") and self.settings["device"]["type"] == "pc":
            self.showMinimized()

    def stop(self):
        control.stop()

    def toggle_pause(self):
        if not (self.runner and self.runner.is_alive()):
            return
        control.toggle_pause()
        self.run_tab.set_paused(control.paused)
        if control.paused:
            self.sidebar.status.set_state("paused")
            log.info("Paused - you can use the game. Press Resume (F9) to continue.")
        else:
            self.sidebar.status.set_state("waiting" if control.waiting_for_user else "running")
            log.info("Resumed")

    def continue_(self):
        control.resume_from_wait()

    def _hotkey(self, action):
        if action == "stop":
            self.stop()
        elif action == "pause":
            self.toggle_pause()
        elif action == "continue":
            self.continue_()

    def _on_status(self, st):
        chip = self.sidebar.status
        if "mode" in st and st["mode"] and chip.state in ("running", "paused", "waiting"):
            chip.set_state(chip.state, st["mode"])
        if st.get("waiting"):
            chip.set_state("waiting")
            key = (self.settings["hotkeys"].get("continue") or "").upper()
            if self._wait_toast is None or self._wait_toast.closing:
                self._wait_toast = self.toasts.show(
                    "warning", "Waiting for you", f"{st.get('action') or 'The account is full'}. Spend the resources "
                    f"in the game, then press Continue{f' ({key})' if key else ''}.", timeout=0,
                    action=("Continue", self.continue_))
            if not self.testAttribute(Qt.WA_DontShowOnScreen):
                QApplication.alert(self)
        elif st.get("waiting") is False:
            self._dismiss_wait()
            if chip.state == "waiting":
                chip.set_state("paused" if control.paused else "running")
        if st.get("shutdown_pending"):
            self.toasts.show("warning", "Shutting down in 60 seconds", "The run has ended and “Shut down the PC” "
                             "was selected.", timeout=60000, action=("Cancel shutdown", self._cancel_shutdown))

    def _dismiss_wait(self):
        t, self._wait_toast = self._wait_toast, None
        if t is not None and not t.closing:
            t.dismiss()

    def _finished(self, reason):
        self._set_running(False)
        config.save_accounts(self.accounts)     # Town Hall levels learned during the run
        self.accounts_tab.load(self.settings, self.accounts)
        self._dismiss_wait()
        chip = self.sidebar.status
        chip.stop_clock()
        chip.set_state("idle", {"finished": "Last run finished", "stopped": "Last run stopped",
                                "error": "Last run hit an error"}.get(reason, "Ready"))
        self._update_lock()
        if reason == "error":
            self.toasts.show("error", "The bot stopped because of an error", "The log has the details; a screenshot "
                             "was saved in logs/errors.", 10000, action=("Open log", lambda: self.go(self.logs_tab)))
        elif reason == "stopped":
            self.toasts.show("info", "Run stopped", "", 4000)
        else:
            self.toasts.show("success", "Run finished", "All done.", 5000)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _cancel_shutdown(self):
        cancel_shutdown()
        self.run_tab.hide_shutdown()
        self.toasts.clear("warning")
        self.toasts.show("success", "Shutdown cancelled", "", 3000)
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
            self.toasts.show("error", f"{name} failed", str(result) or type(result).__name__, 8000)
            if name == "Test connection":
                self.device_tab.set_result(f"Failed: {result}", ok=False)
            if name == "Read names":
                self._set_running(False)
                self.sidebar.status.set_state("idle", "Ready")
            return
        if name == "Screenshot":
            self.templates_tab.set_frame(result)
            self.toasts.show("success", "Screenshot taken", f"{result.shape[1]}×{result.shape[0]}", 2500)
        elif name == "Test connection":
            device, frame = result
            text = (f"OK: {device.describe()}, screen {frame.shape[1]}×{frame.shape[0]} "
                    f"(profile {profile.name} is {profile.width}×{profile.height})")
            self.device_tab.set_result(text, ok=True)
            self.toasts.show("success", "Connected", text, 5000)
        elif name == "Read names":
            self._set_running(False)
            self.sidebar.status.set_state("idle", "Ready")
            added = self.accounts_tab.merge_scanned(result)
            self.save()
            self.toasts.show("success", f"Found {len(result)} accounts", f"{added} new added to the list.", 6000)

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
            self.toasts.show("warning", "Templates missing", "Capture first: " + ", ".join(missing), 8000)
            self.go(self.templates_tab)
            return
        self._set_running(True)
        self.sidebar.status.set_state("busy", "Reading account names")
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
        name = T.ask_text(self, "New profile", "Name for the new profile (e.g. bluestacks-1600x900):")
        if not name or not name.strip():
            return
        try:
            frame = self._device()._capture_native()
        except Exception as e:  # noqa: BLE001
            self.toasts.show("error", "Could not read the device screen", str(e), 8000)
            return
        d = os.path.join(paths.PROFILES, name.strip())
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "profile.json"), "w", encoding="utf-8") as f:
            json.dump({"width": frame.shape[1], "height": frame.shape[0]}, f)
        self.device_tab.reload_profiles(name.strip())
        self._schedule_save()
        self.toasts.show("success", f"Profile “{name.strip()}” created",
                         f"{frame.shape[1]}×{frame.shape[0]}. Capture its templates and digits on the Templates page.",
                         7000)

    def closeEvent(self, e):
        if self.runner and self.runner.is_alive():
            if not T.ask(self, "Quit", "The bot is running. Stop it and quit?"):
                e.ignore()
                return
            control.stop()
            self.runner.join(5)
        self.save()
        self.hotkeys.stop()
        e.accept()


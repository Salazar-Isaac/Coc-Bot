"""Main window: one screen. Top bar (run controls, status, Templates / Full log), the flow on the left, every
setting on the right, the live status line and log at the bottom. Settings persistence, starting/stopping."""

import json
import logging
import os
import threading

import win32gui
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSequentialAnimationGroup, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow,
                               QSplitter, QSplitterHandle, QVBoxLayout, QWidget)

from bot import config, paths
from bot.actions.account import scan_accounts
from bot.core import vision
from bot.core.context import Bot
from bot.core.control import control
from bot.core.devices import make_device
from bot.core.layout import layout
from bot.core.profile import profile
from bot.core.window import bring_to_front
from bot.flow import BY_KEY
from bot.modes.common import cancel_shutdown
from bot.runner import Runner, missing_templates
from gui import theme as T
from gui.bridge import Bridge, Hotkeys, setup_logging
from gui.components import Banner, Button, Pill, label
from gui.flow_panel import FlowPanel
from gui.logs_tab import LogsTab
from gui.nav import AnimatedStack, Logo
from gui.run_tab import Badged, LivePanel, RunControls, StatusPill
from gui.settings_panel import SettingsPanel
from gui.templates_tab import TemplatesTab
from gui.toast import ToastManager

log = logging.getLogger("bot")

MAIN, TEMPLATES, LOGS = range(3)


class TopBar(QFrame):
    """Logo, run controls, status pill; on the right "locked while running" / "✓ Saved", Templates, Full log."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 6, 12, 6)
        lay.setSpacing(10)
        lay.addWidget(Logo(34), 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = label("Coc-Bot")
        name.setFont(T.font(13, QFont.Bold, display=True))
        self.tagline = label("Clash of Clans assistant", "small")
        col.addStretch(1)
        col.addWidget(name)
        col.addWidget(self.tagline)
        col.addStretch(1)
        lay.addLayout(col)
        lay.addSpacing(14)
        self.controls = RunControls()
        lay.addWidget(self.controls, 0, Qt.AlignVCenter)
        lay.addSpacing(4)
        self.status = StatusPill()
        lay.addWidget(self.status, 1, Qt.AlignVCenter)
        lay.addStretch(0)
        self.lock = Pill("Locked while running", T.AMBER)
        self.lock.setToolTip("Settings are locked while the bot runs")
        self.lock.hide()
        lay.addWidget(self.lock, 0, Qt.AlignVCenter)
        self.saved = QLabel()
        self.saved.setTextFormat(Qt.RichText)
        self.saved.setText(f"<span style='color:{T.GREEN}; font-size:9pt; font-weight:600'>✓ Saved</span>")
        self._fx = QGraphicsOpacityEffect(self.saved)
        self._fx.setOpacity(0.0)
        self.saved.setGraphicsEffect(self._fx)
        lay.addWidget(self.saved, 0, Qt.AlignVCenter)
        self.templates_btn = Button("Templates", "scan", "secondary", "sm")
        self.templates_btn.setToolTip("Images the bot recognises (Ctrl+T)")
        self.log_btn = Button("Full log", "terminal", "secondary", "sm")
        self.log_btn.setToolTip("Everything the bot reported in this session (Ctrl+L)")
        self.templates = Badged(self.templates_btn)
        self.logs = Badged(self.log_btn)
        lay.addWidget(self.templates, 0, Qt.AlignVCenter)
        lay.addWidget(self.logs, 0, Qt.AlignVCenter)

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
        self._compact = None

    def flash_saved(self):
        if not self.lock.isVisible():
            self._flash.stop()
            self._flash.start()

    def set_locked(self, locked):
        self.lock.setVisible(locked)
        self.saved.setVisible(not locked)

    def set_page(self, page):
        self.templates_btn.set_variant("outline" if page == TEMPLATES else "secondary")
        self.log_btn.set_variant("outline" if page == LOGS else "secondary")

    def resizeEvent(self, e):
        w = self.width()
        compact = w < 1240                   # no key caps on the run buttons
        if compact != self._compact:
            self._compact = compact
            self.controls.set_compact(compact)
        self.tagline.setVisible(w >= 1440)
        super().resizeEvent(e)


class OverlayPage(QWidget):
    """Templates or the full log, shown instead of the main screen, with a Back button."""

    back = Signal()

    def __init__(self, title, subtitle, view, parent=None):
        super().__init__(parent)
        self.view = view
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 18)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(16)
        back = Button("Back", "arrow-left", "secondary", "sm")
        back.setToolTip("Back to the flow (Esc)")
        back.clicked.connect(self.back)
        head.addWidget(back, 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = label(title)
        t.setFont(T.font(16, QFont.DemiBold, display=True))
        col.addWidget(t)
        col.addWidget(label(subtitle, "subtitle"))
        head.addLayout(col, 1)
        lay.addLayout(head)
        lay.addWidget(view, 1)


class _Handle(QSplitterHandle):
    """Splitter handle: a thin line with a small grip in the middle."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setCursor(Qt.SizeVerCursor)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(T.GOLD if self._hover else T.BORDER_STRONG)
        cy = self.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(self.width() / 2 - 22, cy - 2, 44, 4), 2, 2)


class _Splitter(QSplitter):
    def createHandle(self):
        return _Handle(self.orientation(), self)


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
        self._split_set = False
        self._hotkeys_now = None
        self._unseen = 0
        self._unseen_level = 0
        self._running = False

        # ---------------- parts
        self.top = TopBar()
        self.controls = self.top.controls
        self.status_pill = self.top.status
        self.flow_panel = FlowPanel()
        self.settings_panel = SettingsPanel()
        self.live = LivePanel()
        self.templates_tab = TemplatesTab()
        self.logs_tab = LogsTab()
        sp = self.settings_panel
        self.accounts_tab, self.device_tab, self.donate_tab = sp.accounts, sp.device, sp.donate
        self.general = sp.general
        self.pages = [self.flow_panel, self.settings_panel]       # load / apply / changed / set_running

        # ---------------- layout: top bar / (flow | settings) over the live panel
        root = QWidget()
        root.setObjectName("Root")
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.top)
        content = QWidget()
        content.setObjectName("Content")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.shutdown_banner = Banner("<b>The PC shuts down in 60 seconds.</b>  The run has ended and “Shut down "
                                      "the PC” was selected.", "warning")
        self.shutdown_banner.add_button(Button("Cancel shutdown", "x-circle", "danger", "sm")).clicked.connect(
            self._cancel_shutdown)
        self.shutdown_banner.hide()
        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.setContentsMargins(16, 10, 16, 0)
        bl.addWidget(self.shutdown_banner)
        self.banner_box = bw
        bw.hide()
        cv.addWidget(bw)

        body = QWidget()
        h = QHBoxLayout(body)
        h.setContentsMargins(16, 14, 8, 6)
        h.setSpacing(16)
        h.addWidget(self.flow_panel)
        h.addWidget(self.settings_panel, 1)
        bottom = QWidget()
        b = QVBoxLayout(bottom)
        b.setContentsMargins(16, 2, 16, 14)
        b.addWidget(self.live)
        bottom.setMinimumHeight(118)
        self.splitter = _Splitter(Qt.Vertical)
        self.splitter.setHandleWidth(10)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(body)
        self.splitter.addWidget(bottom)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        body.setMinimumHeight(320)

        self.stack = AnimatedStack()
        self.stack.addWidget(self.splitter)
        self.templates_page = OverlayPage("Templates", "Images the bot recognises. Re-capture one when Supercell "
                                          "changes a button.", self.templates_tab)
        self.logs_page = OverlayPage("Full log", "Everything the bot reported in this session.", self.logs_tab)
        self.stack.addWidget(self.templates_page)
        self.stack.addWidget(self.logs_page)
        cv.addWidget(self.stack, 1)
        v.addWidget(content, 1)
        self.setCentralWidget(root)
        self.toasts = ToastManager(content)

        # ---------------- settings
        for p in self.pages:
            p.load(self.settings, self.accounts)
        self.settings_panel.set_flow(self.flow_panel.keys())
        self._refresh_details()
        for p in self.pages:
            p.changed.connect(self._schedule_save)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._autosave)

        # ---------------- wiring
        fp = self.flow_panel
        fp.changed.connect(self._flow_changed)
        fp.step_clicked.connect(self.settings_panel.show_step)
        fp.cleared.connect(self.settings_panel.clear_peek)
        fp.preset_chosen.connect(self._preset_accounts)
        sp.add_requested.connect(self._add_to_flow)
        sp.changed.connect(self._refresh_details)
        ct = self.controls
        ct.start_clicked.connect(self.start)
        ct.stop_clicked.connect(self.stop)
        ct.pause_clicked.connect(self.toggle_pause)
        ct.continue_clicked.connect(self.continue_)
        self.top.templates_btn.clicked.connect(lambda: self.go(TEMPLATES if self.stack.currentIndex() != TEMPLATES
                                                               else MAIN))
        self.top.log_btn.clicked.connect(lambda: self.go(LOGS if self.stack.currentIndex() != LOGS else MAIN))
        self.templates_page.back.connect(lambda: self.go(MAIN))
        self.logs_page.back.connect(lambda: self.go(MAIN))
        self.live.show_log_clicked.connect(lambda: self.go(LOGS))
        self.accounts_tab.scan_requested.connect(self.scan_accounts)
        self.device_tab.test_requested.connect(self.test_device)
        self.device_tab.new_profile_requested.connect(self.new_profile)
        self.donate_tab.templates_requested.connect(lambda: self.go(TEMPLATES))
        self.templates_tab.screenshot_requested.connect(self.take_screenshot)
        self.templates_tab.templates_changed.connect(self._update_badges)
        self.logs_tab.seen.connect(self._logs_seen)
        QShortcut(QKeySequence("Ctrl+T"), self, activated=lambda: self.go(TEMPLATES))
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.go(LOGS))
        self._esc = QShortcut(QKeySequence("Esc"), self, activated=lambda: self.go(MAIN))
        self._esc.setEnabled(False)          # only on Templates / Full log (Esc keeps working in editors)

        self.bridge.log.connect(self.live.append_log)
        self.bridge.log.connect(self.logs_tab.append_log)
        self.bridge.log.connect(self._count_log)
        self.bridge.status.connect(self.controls.update_status)
        self.bridge.status.connect(self.live.update_status)
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
        if not self._split_set:
            QTimer.singleShot(0, self._initial_split)

    def _initial_split(self):
        if self._split_set:
            return
        self._split_set = True
        total = sum(self.splitter.sizes())
        bottom = 214 if self.height() >= 900 else 180
        self.splitter.setSizes([max(320, total - bottom), bottom])

    def resizeEvent(self, e):
        self.flow_panel.setFixedWidth(420 if self.width() >= 1700 else 392)
        super().resizeEvent(e)

    def _warm_up(self, i=0):
        """Polish and lay out the hidden pages one by one in idle time, so the first visit is instant."""
        hidden = [p for p in (self.templates_page, self.logs_page) if p is not self.stack.currentWidget()]
        if i < len(hidden):
            hidden[i].grab()
            QTimer.singleShot(80, lambda: self._warm_up(i + 1))

    # ----------------------------------------------------------------- navigation
    def go(self, page):
        self.stack.slide_to(page)
        self.top.set_page(page)
        self._esc.setEnabled(page != MAIN)

    def _update_badges(self):
        missing = len(missing_templates())
        self.top.templates.set_badge(str(missing) if missing else "", T.RED)
        self.top.templates_btn.setToolTip(f"{missing} required template{'s' if missing != 1 else ''} missing (Ctrl+T)"
                                          if missing else "Images the bot recognises (Ctrl+T)")

    def _count_log(self, _msg, level):
        if level >= logging.WARNING and self.stack.currentIndex() != LOGS:
            self._unseen += 1
            self._unseen_level = max(self._unseen_level, level)
            self.top.logs.set_badge(str(min(self._unseen, 99)),
                                    T.RED if self._unseen_level >= logging.ERROR else T.AMBER)

    def _logs_seen(self):
        self._unseen = 0
        self._unseen_level = 0
        self.top.logs.set_badge("")

    # ----------------------------------------------------------------- flow
    def _flow_changed(self):
        self.settings_panel.set_flow(self.flow_panel.keys())
        self._refresh_details()

    def _preset_accounts(self, roles):
        """A preset also sets which accounts its steps work on, from the roles on the Accounts list
        (Loot + Donate: only the Main and the Looters loot - the others request)."""
        from bot.flow import preset_accounts
        self.collect()                                  # keep everything else as it is on screen
        for key, spec in preset_accounts(roles, self.accounts).items():
            self.settings.setdefault("steps", {}).setdefault(key, {})["accounts"] = spec
        self.settings_panel.load(self.settings, self.accounts)
        self._schedule_save()

    def _add_to_flow(self, key):
        self.flow_panel.append(key)
        self.flow_panel.set_current(key)
        self.settings_panel.scroll_to(key)

    def _refresh_details(self):
        self.flow_panel.set_details(self.settings_panel.details())

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
                self.top.flash_saved()
        if profile.name != self.settings.get("profile"):
            profile.use(self.settings["profile"])
            vision.templates.reload()
            vision.digits.reload()
            layout.reload()
            self.templates_tab.refresh()
        self._start_hotkeys()
        self.templates_tab.set_extra_items(self.settings.get("donate", {}).get("items", []))
        self._update_badges()

    def _start_hotkeys(self):
        keys = dict(self.settings["hotkeys"])
        if keys != self._hotkeys_now:
            self._hotkeys_now = keys
            self.hotkeys.start(keys)
        self.controls.set_hotkeys(keys)
        self.live.set_hotkeys(keys)

    # ----------------------------------------------------------------- run control
    def _set_running(self, running, run=True):
        """running: settings locked (a run, or reading the account names). run: a real run of the flow."""
        self._running = running
        for p in (*self.pages, self.templates_tab):
            p.set_running(running)
        self.controls.set_running(running)
        if run or not running:
            self.live.set_running(running and run)
        self.top.set_locked(running)
        if not running:
            self.flow_panel.set_running_key(None)

    def _flow_title(self):
        keys = [k for k in self.settings.get("flow", []) if k in BY_KEY]
        if len(keys) <= 2:
            return " → ".join(BY_KEY[k].title for k in keys)
        return f"Flow · {len(keys)} steps"

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
            self.go(TEMPLATES)
            return
        if not [k for k in self.settings.get("flow", []) if k in BY_KEY]:
            self.toasts.show("info", "Add functions to the flow first", "Drag them from Functions into the Flow box "
                             "(or double-click one), or pick a preset.", 7000)
            self.go(MAIN)
            self.flow_panel.flash_flow()
            return
        self._set_running(True)
        status = lambda **kw: self.bridge.status.emit(kw)  # noqa: E731
        self.runner = Runner("flow", self.settings, self.accounts, status,
                             lambda reason: self.bridge.finished.emit(reason), resume=self.general.resume.isChecked())
        device = ("Google Play Games (PC)" if self.settings["device"]["type"] == "pc"
                  else f"ADB {self.settings['device']['adb_serial']}")
        self.bridge.status.emit({"device": device})
        self.runner.start()
        title = self._flow_title()
        self.status_pill.set_state("running", title)
        self.status_pill.start_clock()
        self.toasts.show("success", "Run started", f"{title} on {device}.", 3500)
        if self.settings.get("minimize_on_start") and self.settings["device"]["type"] == "pc":
            self.showMinimized()

    def stop(self):
        control.stop()

    def toggle_pause(self):
        if not (self.runner and self.runner.is_alive()):
            return
        control.toggle_pause()
        self.controls.set_paused(control.paused)
        self.live.set_paused(control.paused)
        if control.paused:
            self.status_pill.set_state("paused")
            log.info("Paused - you can use the game. Press Resume (F9) to continue.")
        else:
            self.status_pill.set_state("waiting" if control.waiting_for_user else "running")
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
        pill = self.status_pill
        if st.get("waiting"):
            pill.set_state("waiting")
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
            if pill.state == "waiting":
                pill.set_state("paused" if control.paused else "running")
        if st.get("shutdown_pending"):
            self.banner_box.show()
            self.shutdown_banner.show()
            self.toasts.show("warning", "Shutting down in 60 seconds", "The run has ended and “Shut down the PC” "
                             "was selected.", timeout=60000, action=("Cancel shutdown", self._cancel_shutdown))
        if self._running and ("action" in st or "step" in st):
            self.flow_panel.set_running_key(self.live.current_step())

    def _dismiss_wait(self):
        t, self._wait_toast = self._wait_toast, None
        if t is not None and not t.closing:
            t.dismiss()

    def _finished(self, reason):
        self._set_running(False)
        config.save_accounts(self.accounts)     # Town Hall levels learned during the run
        self.accounts_tab.load(self.settings, self.accounts)
        self._dismiss_wait()
        pill = self.status_pill
        pill.stop_clock()
        pill.set_state("idle", {"finished": "Last run finished", "stopped": "Last run stopped",
                                "error": "Last run hit an error"}.get(reason, "Ready"))
        if reason == "error":
            self.toasts.show("error", "The bot stopped because of an error", "The log has the details; a screenshot "
                             "was saved in logs/errors.", 10000, action=("Open log", lambda: self.go(LOGS)))
        elif reason == "stopped":
            self.toasts.show("info", "Run stopped", "", 4000)
        else:
            self.toasts.show("success", "Run finished", "All done.", 5000)
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _cancel_shutdown(self):
        cancel_shutdown()
        self.shutdown_banner.hide()
        self.banner_box.hide()
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
                self.status_pill.set_state("idle", "Ready")
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
            self.status_pill.set_state("idle", "Ready")
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
            self.go(TEMPLATES)
            return
        self._set_running(True, run=False)
        self.status_pill.set_state("busy", "Reading account names")
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

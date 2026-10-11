"""Dashboard: choose a mode and options, start/pause/stop, watch live stats and the log."""

import math
import re
import time

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from bot.modes import MODES, load_all
from gui import icons
from gui import theme as T
from gui.components import (AnimatedBar, Avatar, Banner, Button, Card, ChoiceCard, CountLabel, ElidedLabel, IconButton,
                            Pill, ResourceIcon, SettingRow, Toggle, divider, fmt_int, fmt_short, hbox, label, scroll)
from gui.logs_tab import LogView
from gui.widgets import Combo, Spin

WHEN_FULL = [("switch", "Switch account", "Go on with the next account in the list"),
             ("wait", "Wait for me", "Stay on the full account: spend the resources yourself, then press Continue"),
             ("stop", "Stop the run", "End the run as soon as an account is full")]
WHEN_DONE = [("nothing", "Do nothing", "Leave the game open"),
             ("close_game", "Close the game", "Close Clash of Clans when the run ends"),
             ("shutdown", "Shut down the PC", "Shut down 60 seconds after the run (can be cancelled)"),
             ("sleep", "Put the PC to sleep", "Sleep when the run ends")]

MODE_LOOK = {"loot_all": ("swords", T.GOLD), "loot_current": ("user", "#5cc8ff"),
             "loot_donate": ("gift", T.ELIXIR_HI), "donate_only": ("heart", "#ff7f9f"),
             "builder_only": ("boat", "#8c9bff")}
# titles for the small two-column mode tiles (other modes use their own title)
MODE_SHORT = {"loot_all": "Loot all", "loot_current": "Loot current", "loot_donate": "Loot + Donate",
              "donate_only": "Donate only", "builder_only": "Builder Base"}
LOOT_MODES = ("loot_all", "loot_current", "loot_donate")    # can visit the Builder Base after looting

# "This run" counters: key, label, short label (narrow window). A counter is listed when the selected mode
# does that work, or once it is > 0.
STATS = [("attacks", "Attacks", "Attacks"), ("searches", "Searches", "Searches"), ("donated", "Donated", "Donated"),
         ("bb_attacks", "Builder Base attacks", "BB attacks"), ("upgrades", "Upgrades", "Upgrades"),
         ("research", "Research", "Research")]
MODE_STATS = {"loot_all": ("attacks", "searches", "upgrades"), "loot_current": ("attacks", "searches"),
              "loot_donate": ("attacks", "searches", "donated"), "donate_only": ("donated",),
              "builder_only": ("bb_attacks",)}

# mode list density: (card height, gap, columns). The first that fits without scrolling the setup column wins;
# the last one (two columns of small tiles) is for small windows.
MODE_DENSITY = [(58, 8, 1), (50, 6, 1), (42, 8, 2)]
MAX_OPTION_ROWS = 4      # the most option rows any mode shows (see _mode_changed)


def _clean(desc):
    return re.sub(r"\s*\((coming next|coming soon)\)\.?\s*$", "", desc or "", flags=re.I).strip()


def _frame():
    f = QFrame()
    f.setObjectName("Card")
    return f


class ResourceCard(QFrame):
    """Gold / Elixir / Dark: current value, animated bar towards "full at"."""

    def __init__(self, res, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.res = res
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        self.full_pill = Pill("FULL", T.GREEN, strong=True)
        self.full_pill.hide()
        lay.addLayout(hbox(ResourceIcon(res, 22), label(T.RESOURCE_NAME[res].upper(), "caption"), None,
                           self.full_pill, spacing=8))
        self.value = CountLabel()
        lay.addWidget(self.value)
        self.bar = AnimatedBar(T.RESOURCE_BAR[res], 7)
        lay.addWidget(self.bar)
        self.sub = label("Not read yet", "small")
        lay.addWidget(self.sub)

    def reset(self):
        self.value.set_value(None)
        self.bar.set_value(0)
        self.full_pill.hide()
        self.sub.setText("Not read yet")

    def set_plain(self, v, watched=False):
        self.value.set_value(v)
        if not watched:
            self.bar.set_value(0)
            self.full_pill.hide()
            self.sub.setText("Not watched")

    def set_fullness(self, v, cap, full):
        self.value.set_value(v)
        if cap:
            frac = (v or 0) / cap
            self.bar.set_value(frac, full)
            self.sub.setText(f"of {cap:,}  ·  {min(999, int(frac * 100))}%")
        else:
            self.bar.set_value(0)
            self.sub.setText("No limit set for this Town Hall")
        self.full_pill.setVisible(bool(full))


class RunTab(QWidget):
    start_clicked = Signal()
    pause_clicked = Signal()
    continue_clicked = Signal()
    stop_clicked = Signal()
    cancel_shutdown_clicked = Signal()
    show_log_clicked = Signal()
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        load_all()
        self._keys = {"continue": "f8", "pause": "f9", "stop": "f10"}
        self._narrow = False
        self._running = False
        self._paused = False
        self._waiting = False
        self._mode_title = ""
        self._bb_after = False               # loot modes also loot the Builder Base (Builder Base page)
        self._density = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        root.addWidget(self._build_controls())
        self.shutdown_banner = Banner("<b>The PC shuts down in 60 seconds.</b>  The run has ended and "
                                      "“Shut down the PC” was selected.", "warning")
        self.cancel_shutdown_btn = self.shutdown_banner.add_button(
            Button("Cancel shutdown", "x-circle", "danger", "sm"))
        self.cancel_shutdown_btn.clicked.connect(self.cancel_shutdown_clicked)
        self.shutdown_banner.hide()
        root.addWidget(self.shutdown_banner)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # ---------------- left: mode + options ----------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setSpacing(16)
        setup = Card("Run setup", "Choose what the bot does and what happens next.", icon="bolt", spacing=8)
        self._build_modes(setup)
        setup.layout().addSpacing(4)
        setup.add(divider())
        setup.layout().addSpacing(2)
        self._build_options(setup)
        setup.layout().addStretch(1)
        ll.addWidget(setup, 1)
        self.left_scroll = scroll(left, margins=(0, 0, 10, 0))
        self.left_scroll.setFixedWidth(404)
        self.left_scroll.viewport().installEventFilter(self)
        body.addWidget(self.left_scroll)

        # ---------------- right: stats + log ----------------
        right = QVBoxLayout()
        right.setSpacing(16)
        body.addLayout(right, 1)
        res_row = QHBoxLayout()
        res_row.setSpacing(16)
        self.res_cards = {r: ResourceCard(r) for r in T.RESOURCES}
        for c in self.res_cards.values():
            res_row.addWidget(c)
        right.addLayout(res_row)
        info = QHBoxLayout()
        info.setSpacing(16)
        info.addWidget(self._build_account(), 5)
        info.addWidget(self._build_session(), 4)
        info.addWidget(self._build_scout(), 4)
        right.addLayout(info)
        right.addWidget(self._build_log(), 1)

        self._started = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self.set_running(False)

    # ------------------------------------------------------------------ building
    def _build_controls(self):
        card = self.hero_card = _frame()
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 14, 20, 14)
        lay.setSpacing(10)
        self.start_btn = Button("Start", "play", "primary", "lg")
        self.start_btn.setMinimumWidth(150)
        self.start_btn.enable_glow(T.GOLD)
        self.pause_btn = Button("Pause", "pause", "secondary", "lg", hint="F9")
        self.continue_btn = Button("Continue", "next", "success", "lg", hint="F8")
        self.stop_btn = Button("Stop", "stop", "danger", "lg", hint="F10")
        for b in (self.start_btn, self.pause_btn, self.continue_btn, self.stop_btn):
            lay.addWidget(b)
        self.start_btn.clicked.connect(self.start_clicked)
        self.pause_btn.clicked.connect(self.pause_clicked)
        self.continue_btn.clicked.connect(self.continue_clicked)
        self.stop_btn.clicked.connect(self.stop_clicked)
        self.start_btn.setToolTip("Save the settings and start the selected mode")

        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {T.BORDER};")
        lay.addSpacing(8)
        lay.addWidget(sep)
        lay.addSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.hero_caption = Pill("READY", T.TEXT_MUTED)
        self.hero_title = ElidedLabel("", lines=1, pt=11, color=T.TEXT, weight=QFont.DemiBold)
        self.hero_text = ElidedLabel("", lines=2)
        col.addStretch(1)
        col.addLayout(hbox(self.hero_caption, self.hero_title, spacing=10))
        col.addWidget(self.hero_text)
        col.addStretch(1)
        lay.addLayout(col, 1)
        return card

    def _build_modes(self, card):
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons = {}
        self.mode_box = QGridLayout()
        self.mode_box.setContentsMargins(0, 0, 0, 0)
        self.mode_box.setHorizontalSpacing(8)
        h = MODE_DENSITY[0][0]
        for key, mode in sorted(MODES.items(), key=lambda kv: (not kv[1].ready, kv[1].order)):
            icon, color = MODE_LOOK.get(key, ("bolt", T.GOLD))
            b = ChoiceCard(mode.title, _clean(mode.description), icon, color,
                           badge="" if mode.ready else "Coming soon", height=h)
            b.short_title = MODE_SHORT.get(key, mode.title)
            b.setProperty("mode_key", key)
            b.setEnabled(mode.ready)
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
        self._place_modes(0)
        card.add(self.mode_box)
        self.mode_group.buttonToggled.connect(self._mode_changed)

    def _modes_height(self, density):
        h, gap, cols = MODE_DENSITY[density]
        rows = math.ceil(len(self.mode_buttons) / cols)
        return rows * h + max(0, rows - 1) * gap

    def _place_modes(self, density):
        """Lay the mode cards out in one column (full or compact cards) or two columns of small tiles."""
        self._density = density
        h, gap, cols = MODE_DENSITY[density]
        dense = cols > 1
        for b in self.mode_buttons.values():
            self.mode_box.removeWidget(b)
        for i, (key, b) in enumerate(self.mode_buttons.items()):
            mode = MODES[key]
            b.setFixedHeight(h)
            b.set_dense(dense)
            tip = _clean(mode.description)
            b.setToolTip(f"<b>{mode.title}</b>{'' if mode.ready else ' (coming soon)'}<br>{tip}" if dense else tip)
            self.mode_box.addWidget(b, i // cols, i % cols)
        self.mode_box.setVerticalSpacing(gap)
        for c in range(2):
            self.mode_box.setColumnStretch(c, 1 if c < cols else 0)

    def _fit_modes(self):
        """Pick the roomiest mode list that lets the whole setup column fit without scrolling."""
        if not self.mode_buttons:
            return
        other = self.left_scroll.widget().sizeHint().height() - self._modes_height(self._density)
        # size for the mode with the most option rows (4: Loot all / Loot current), so picking a
        # mode never changes the layout
        spacing = max(0, self.rows["full"].parentWidget().layout().spacing()) if self.rows["full"].parentWidget() else 8
        shown = sum(1 for r in self.rows.values() if not r.isHidden())
        other += max(0, MAX_OPTION_ROWS - shown) * (self.rows["full"].sizeHint().height() + spacing)
        avail = self.left_scroll.viewport().height()
        best = next((d for d in range(len(MODE_DENSITY)) if other + self._modes_height(d) <= avail),
                    len(MODE_DENSITY) - 1)
        if best != self._density:
            self._place_modes(best)

    def _build_options(self, card):
        self.when_full = Combo(WHEN_FULL)
        self.when_done = Combo(WHEN_DONE)
        self.rounds = Spin(0, 999, special="Forever")
        self.current_account = Combo(editable=True)
        self.current_th = Spin(0, 25, special="Unknown")
        self.resume = Toggle(checked=True)
        self.rows = {
            "full": SettingRow("When an account is full", control=self.when_full, control_width=180),
            "done": SettingRow("When the run ends", control=self.when_done, control_width=180),
            "rounds": SettingRow("Rounds over all accounts", control=self.rounds, control_width=120),
            "current": SettingRow("Account open now", control=self.current_account, control_width=180),
            "th": SettingRow("Its Town Hall", control=self.current_th, control_width=120),
            "resume": SettingRow("Continue where the last run stopped", control=self.resume),
        }
        for r in self.rows.values():
            card.add(r)
        self.current_account.lineEdit().setPlaceholderText("Name in the switch list")
        for w in (self.when_full, self.when_done, self.current_account):
            w.currentIndexChanged.connect(self.changed)
        self.current_account.editTextChanged.connect(self.changed)
        self.rounds.valueChanged.connect(self.changed)
        self.current_th.valueChanged.connect(self.changed)

    def _build_account(self):
        card = _frame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        self.acc_progress = label("", "caption")
        lay.addLayout(hbox(label("ACCOUNT", "caption"), None, self.acc_progress))
        self.avatar = Avatar(40)
        self.acc_name = ElidedLabel("—", lines=1, pt=12, color=T.TEXT, weight=QFont.DemiBold)
        self.acc_device = ElidedLabel("No run yet", lines=1, pt=8.5)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.acc_name)
        col.addWidget(self.acc_device)
        lay.addLayout(hbox(self.avatar, col, spacing=12))
        self.acc_bar = AnimatedBar((T.GOLD_HI, T.GOLD_LO), 5)
        lay.addWidget(self.acc_bar)
        self.acc_action = label("Idle", "rowDesc")
        self.acc_action.setMinimumWidth(10)
        lay.addWidget(self.acc_action)
        return card

    def _build_session(self):
        card = _frame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(7)
        self.run_time = label("—", "caption")
        self.run_time.setFont(T.font(8.5, QFont.DemiBold, mono=True))
        self.run_time.setToolTip("Run time")
        clock = QLabel()
        clock.setPixmap(icons.pixmap("clock", T.TEXT_MUTED, 13))
        clock.setToolTip("Run time")
        lay.addLayout(hbox(label("THIS RUN", "caption"), None, clock, self.run_time, spacing=5))
        self.stat_values = {}
        self.stat_rows = {}
        self.stat_titles = {}
        for key, title, _short in STATS:
            v = CountLabel(role="metric")
            name = label(title, "muted")
            name.setToolTip(title)
            row = QWidget()
            row.setLayout(hbox(name, None, v))
            self.stat_values[key] = v
            self.stat_rows[key] = row
            self.stat_titles[key] = name
            lay.addWidget(row)
        self.attacks = self.stat_values["attacks"]
        self.searches = self.stat_values["searches"]
        lay.addStretch(1)
        self._update_stat_rows()
        return card

    def _update_stat_rows(self):
        """List the counters the selected mode produces, plus any other that is above 0."""
        mode = self.mode_key() if hasattr(self, "mode_group") else ""
        relevant = MODE_STATS.get(mode, ("attacks", "searches"))
        if self._bb_after and mode in LOOT_MODES:
            relevant = (*relevant, "bb_attacks")
        for key, row in self.stat_rows.items():
            v = self.stat_values[key].value()
            row.setVisible(key in relevant or bool(v))

    def _build_scout(self):
        card = _frame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(7)
        lay.addWidget(label("LAST SCOUTED BASE", "caption"))
        self.scout = {}
        for r in T.RESOURCES:
            v = CountLabel(role="metric")
            self.scout[r] = v
            lay.addLayout(hbox(ResourceIcon(r, 16), label(T.RESOURCE_NAME[r], "muted"), None, v, spacing=8))
        lay.addStretch(1)
        return card

    def _build_log(self):
        card = Card("Activity", icon="terminal", padding=16, spacing=8)
        clear = IconButton("trash", "Clear this view")
        full = Button("Full log", "arrow-right", "ghost", "sm")
        card.add_action(clear)
        card.add_action(full)
        self.log_view = LogView(3000)
        card.add(self.log_view, 1)
        clear.clicked.connect(self.log_view.clear)
        full.clicked.connect(self.show_log_clicked)
        return card

    # ------------------------------------------------------------------ settings
    def load(self, settings, accounts):
        key = settings.get("mode", "loot_all")
        btn = self.mode_buttons.get(key)
        if btn is None or not btn.isEnabled():
            btn = self.mode_buttons.get("loot_all") or next(iter(self.mode_buttons.values()))
        btn.setChecked(True)
        self.when_full.select(settings.get("when_full", "switch"))
        self.when_done.select(settings.get("when_done", "nothing"))
        self.rounds.setValue(settings.get("repeat_rounds", 1))
        self.set_accounts(accounts)
        self.current_account.setCurrentText(settings.get("current_account", ""))
        self.current_th.setValue(settings.get("current_th", 0) or 0)
        self._bb_after = bool((settings.get("builder") or {}).get("after_main", False))
        self._mode_changed()

    def apply(self, settings, accounts):
        settings["mode"] = self.mode_key()
        settings["when_full"] = self.when_full.currentData()
        settings["when_done"] = self.when_done.currentData()
        settings["repeat_rounds"] = self.rounds.value()
        settings["current_account"] = self.current_account.currentText().strip()
        settings["current_th"] = self.current_th.value()

    def set_accounts(self, accounts):
        text = self.current_account.currentText()
        self.current_account.blockSignals(True)
        self.current_account.clear()
        self.current_account.addItems([a["name"] for a in accounts])
        self.current_account.setCurrentText(text)
        self.current_account.blockSignals(False)

    def set_builder_after(self, on):
        """Loot modes also loot the Builder Base (Builder Base page): list its attacks under "This run"."""
        if bool(on) != self._bb_after:
            self._bb_after = bool(on)
            self._update_stat_rows()

    def set_hotkeys(self, keys):
        self._keys = dict(keys)
        for btn, k in ((self.pause_btn, "pause"), (self.continue_btn, "continue"), (self.stop_btn, "stop")):
            btn.set_hint("" if self._narrow else (keys.get(k) or "").upper())
            btn.setToolTip(f"Hotkey: {(keys.get(k) or '-').upper()}")

    def mode_key(self):
        b = self.mode_group.checkedButton()
        return b.property("mode_key") if b else "loot_all"

    def _mode_changed(self, *_):
        key = self.mode_key()
        current = key == "loot_current"
        self.rows["current"].setVisible(current)
        self.rows["th"].setVisible(current)
        self.rows["rounds"].setVisible(not current)
        self.rows["resume"].setVisible(key == "loot_all")
        if not self._running:
            self._hero_idle()
        self._update_stat_rows()
        QTimer.singleShot(0, self._fit_modes)            # option rows shown/hidden change the needed height
        self.changed.emit()

    # ------------------------------------------------------------------ hero line
    def _hero(self, caption, color, title, text):
        waiting = caption.startswith("WAITING")
        if waiting != bool(self.hero_card.styleSheet()):
            self.hero_card.setStyleSheet(f"QFrame#Card {{ border: 1px solid {T.rgba(T.AMBER, 0.6)}; "
                                         f"background: {T.mix(T.SURFACE, T.AMBER, 0.05).name()}; }}"
                                         if waiting else "")
        self.hero_caption.set(caption, color, strong=waiting)
        self.hero_title.setText(title)
        self.hero_text.setText(text)

    def _hero_idle(self):
        mode = MODES.get(self.mode_key())
        self._hero("READY", T.TEXT_MUTED, mode.title if mode else "",
                   _clean(mode.description) if mode else "")

    # ------------------------------------------------------------------ status
    def set_running(self, running):
        self._running = running
        self._paused = False
        self._waiting = False
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.pause_btn.setEnabled(running)
        self.continue_btn.setEnabled(False)
        self.continue_btn.set_attention(False)
        self.pause_btn.set_text("Pause")
        self.pause_btn.set_icon("pause")
        for key, b in self.mode_buttons.items():
            b.setEnabled(not running and MODES[key].ready)
        if running:
            self._started = time.time()
            self._mode_title = MODES[self.mode_key()].title if self.mode_key() in MODES else ""
            for c in self.res_cards.values():
                c.reset()
            for v in self.scout.values():
                v.set_value(None)
            for v in self.stat_values.values():
                v.set_value(0)
            self._update_stat_rows()
            self.acc_action.setText("Starting…")
            self.acc_bar.set_value(0)
            self.run_time.setText("0:00:00")
            self._hero("RUNNING", T.GREEN, self._mode_title, "Starting…")
        else:
            self._started = None
            self.acc_action.setText("Idle")
            self._hero_idle()

    def set_paused(self, paused):
        self._paused = paused
        self.pause_btn.set_text("Resume" if paused else "Pause")
        self.pause_btn.set_icon("play" if paused else "pause")
        if paused:
            self._hero("PAUSED", T.AMBER, self._mode_title,
                       f"You can use the game now. Press Resume ({self._keys.get('pause', '').upper()}) to go on.")
        else:
            self._hero("RUNNING", T.GREEN, self._mode_title, self.acc_action.text())

    def hide_shutdown(self):
        self.shutdown_banner.hide()

    def update_status(self, st):
        if "device" in st:
            self.acc_device.setText(f"on {st['device']}")
        if "mode" in st and st["mode"]:
            self._mode_title = st["mode"]
            if self._running and not self._waiting and not self._paused:
                self._hero("RUNNING", T.GREEN, self._mode_title, self.acc_action.text())
        if "account" in st:
            name = str(st["account"] or "—")
            self.acc_name.setText(name)
            self.avatar.set_name(name)
        if st.get("progress"):
            prog = str(st["progress"])
            self.acc_progress.setText(prog.replace("/", " / "))
            m = re.match(r"\s*(\d+)\s*/\s*(\d+)", prog)
            if m and int(m.group(2)):
                self.acc_bar.set_value(int(m.group(1)) / int(m.group(2)))
        if "action" in st:
            self.acc_action.setText(str(st["action"]))
            if self._running and not self._waiting and not self._paused:
                self._hero("RUNNING", T.GREEN, self._mode_title, str(st["action"]))
        full = st.get("fullness") or {}
        for r, val in full.items():
            if r in self.res_cards:
                v, cap, is_full = val
                self.res_cards[r].set_fullness(v, cap, is_full)
        for r, v in (st.get("resources") or {}).items():
            if r in self.res_cards and r not in full:
                self.res_cards[r].set_plain(v, watched=False)
        if st.get("loot"):
            for r, v in st["loot"].items():
                if r in self.scout:
                    self.scout[r].set_value(v)
        if "stats" in st:
            s = st["stats"] or {}
            for key, v in self.stat_values.items():
                if key in s:
                    v.set_value(s.get(key) or 0)
            self._update_stat_rows()
        if st.get("waiting"):
            self._waiting = True
            self.continue_btn.setEnabled(True)
            self.continue_btn.set_attention(True, T.GREEN)
            key = self._keys.get("continue", "").upper()
            self._hero("WAITING FOR YOU", T.AMBER, st.get("action") or "Waiting for you",
                       f"Spend the resources in the game, then press Continue ({key}).")
        elif st.get("waiting") is False:
            self._waiting = False
            self.continue_btn.setEnabled(False)
            self.continue_btn.set_attention(False)
            if self._running:
                self._hero("RUNNING", T.GREEN, self._mode_title, self.acc_action.text())
        if st.get("shutdown_pending"):
            self.shutdown_banner.show()

    def eventFilter(self, obj, e):
        if obj is self.left_scroll.viewport() and e.type() == QEvent.Resize:
            self._fit_modes()
        return super().eventFilter(obj, e)

    def resizeEvent(self, e):
        narrow = self.width() < 940          # small window: tighter setup column, compact numbers, no key hints
        if narrow != self._narrow:
            self._narrow = narrow
            self.left_scroll.setFixedWidth(372 if narrow else 404)
            for key in ("full", "done", "current"):
                self.rows[key].control.setFixedWidth(160 if narrow else 180)
            for v in [c.value for c in self.res_cards.values()] + list(self.scout.values()):
                v.set_fmt(fmt_short if narrow else fmt_int)
            for key, title, short in STATS:
                self.stat_titles[key].setText(short if narrow else title)
            self.set_hotkeys(self._keys)
        super().resizeEvent(e)

    def _tick(self):
        if self._started:
            s = int(time.time() - self._started)
            self.run_time.setText(f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}")

    def append_log(self, msg, level):
        self.log_view.append(msg, level)

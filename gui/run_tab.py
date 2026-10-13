"""Run controls (Start / Pause / Continue / Stop and the status pill, in the top bar) and the live panel at the
bottom of the window (one status line + the Activity log)."""

import re
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from bot.flow import BY_KEY
from gui import icons
from gui import theme as T
from gui.components import (AnimatedBar, Avatar, Button, CountLabel, ElidedLabel, IconButton, Pill, PulseDot,
                            ResourceIcon, fmt_short, label)
from gui.logs_tab import LogView

# "This run" counters: key, label. Attacks / searches / Builder Base attacks are always listed, the others
# once they are above 0.
STATS = [("attacks", "Attacks"), ("searches", "Searches"), ("bb_attacks", "BB attacks"), ("donated", "Donated"),
         ("upgrades", "Upgrades"), ("research", "Research")]
ALWAYS_STATS = ("attacks", "searches", "bb_attacks")


def step_of(text):
    """The flow step a status text names (the flow reports a step's title as its action), or None."""
    t = (text or "").strip().lower()
    for key, step in BY_KEY.items():
        if t == step.title.lower() or t.startswith(step.title.lower() + ":"):
            return key
    return BY_KEY.get(text) and text


class StatusPill(QFrame):
    """Run state in the top bar: Idle / Running (pulsing) / Paused / Waiting for you, a detail and the run time."""

    STATES = {
        "idle": ("Idle", T.TEXT_DIM, False),
        "running": ("Running", T.GREEN, True),
        "paused": ("Paused", T.AMBER, False),
        "waiting": ("Waiting for you", T.AMBER, True),
        "busy": ("Working", T.BLUE, True),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self.detail = "Ready"
        self._color = QColor(T.TEXT_DIM)
        self._started = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 14, 0)
        lay.setSpacing(6)
        self.dot = PulseDot(size=20)
        lay.addWidget(self.dot, 0, Qt.AlignVCenter)
        self.title = label("Idle")
        self.title.setFont(T.font(9.75, QFont.DemiBold))
        lay.addWidget(self.title)
        self.sub = ElidedLabel("", lines=1, pt=8.75)
        self.sub.setMinimumWidth(30)
        lay.addWidget(self.sub, 1, Qt.AlignVCenter)
        self.time = label("", "small")
        self.time.setFont(T.font(8.25, QFont.DemiBold, mono=True))
        lay.addWidget(self.time)
        self.setFixedHeight(36)
        self.setMinimumWidth(170)
        self.setMaximumWidth(380)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_state("idle", "Ready")

    def set_state(self, state, detail=None):
        text, color, pulse = self.STATES[state]
        self.state = state
        if detail is not None:
            self.detail = detail
        self._color = QColor(color)
        self.title.setText(text)
        self.title.setStyleSheet(f"color: {T.mix(color, T.TEXT, 0.35).name() if state != 'idle' else T.TEXT};")
        self.sub.setText(f"·  {self.detail}" if self.detail else "")
        self.setToolTip(f"{text}: {self.detail}" if self.detail else text)
        self.dot.set_state(color, pulse, 900 if state == "waiting" else 1600)
        self.update()

    def start_clock(self):
        self._started = time.time()
        self._timer.start(1000)
        self._tick()

    def stop_clock(self):
        self._timer.stop()
        self._started = None
        self.time.setText("")

    def _tick(self):
        if self._started:
            s = int(time.time() - self._started)
            self.time.setText(f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        idle = self.state == "idle"
        p.setPen(QPen(T.qc(self._color, 0.18 if idle else 0.40), 1))
        p.setBrush(QColor(T.SURFACE) if idle else T.mix(T.SURFACE, self._color, 0.09))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)


class RunControls(QWidget):
    """Start / Pause / Continue / Stop with their hotkey hints."""

    start_clicked = Signal()
    pause_clicked = Signal()
    continue_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys = {"continue": "f8", "pause": "f9", "stop": "f10"}
        self._compact = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.start_btn = Button("Start", "play", "primary", "md")
        self.start_btn.setMinimumWidth(104)
        self.start_btn.enable_glow(T.GOLD)
        self.pause_btn = Button("Pause", "pause", "secondary", "md", hint="F9")
        self.continue_btn = Button("Continue", "next", "success", "md", hint="F8")
        self.stop_btn = Button("Stop", "stop", "danger", "md", hint="F10")
        for b in (self.start_btn, self.pause_btn, self.continue_btn, self.stop_btn):
            lay.addWidget(b, 0, Qt.AlignVCenter)
        self.start_btn.clicked.connect(self.start_clicked)
        self.pause_btn.clicked.connect(self.pause_clicked)
        self.continue_btn.clicked.connect(self.continue_clicked)
        self.stop_btn.clicked.connect(self.stop_clicked)
        self.start_btn.setToolTip("Save the settings and run the flow")
        self.set_running(False)

    def set_hotkeys(self, keys):
        self._keys = dict(keys)
        for btn, k in ((self.pause_btn, "pause"), (self.continue_btn, "continue"), (self.stop_btn, "stop")):
            btn.set_hint("" if self._compact else (keys.get(k) or "").upper())
            btn.setToolTip(f"Hotkey: {(keys.get(k) or '-').upper()}")

    def set_compact(self, compact):
        """Narrow window: no key caps on the buttons (the tooltips still name the hotkeys)."""
        if compact != self._compact:
            self._compact = compact
            self.set_hotkeys(self._keys)

    def set_running(self, running):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.pause_btn.setEnabled(running)
        self.continue_btn.setEnabled(False)
        self.continue_btn.set_attention(False)
        self.pause_btn.set_text("Pause")
        self.pause_btn.set_icon("pause")

    def set_paused(self, paused):
        self.pause_btn.set_text("Resume" if paused else "Pause")
        self.pause_btn.set_icon("play" if paused else "pause")

    def update_status(self, st):
        if st.get("waiting"):
            self.continue_btn.setEnabled(True)
            self.continue_btn.set_attention(True, T.GREEN)
        elif st.get("waiting") is False:
            self.continue_btn.setEnabled(False)
            self.continue_btn.set_attention(False)


class _Sep(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(13, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(QRectF(6, 2, 1, self.height() - 4), QColor(T.BORDER_STRONG))


class LivePanel(QFrame):
    """Bottom of the window: account, step / action, progress, last scouted base, this run's counters, the log."""

    show_log_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._running = False
        self._paused = False
        self._waiting = False
        self._keys = {"continue": "f8", "pause": "f9", "stop": "f10"}
        self._step_title = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)

        line = QHBoxLayout()
        line.setSpacing(8)
        self.avatar = Avatar(28)
        line.addWidget(self.avatar)
        acc = QVBoxLayout()
        acc.setSpacing(0)
        self.acc_name = ElidedLabel("No run yet", lines=1, pt=9.75, color=T.TEXT, weight=QFont.DemiBold)
        self.acc_name.setFixedWidth(130)
        self.acc_progress = label("", "small")
        self.acc_progress.setFont(T.font(8, QFont.DemiBold, mono=True))
        self.acc_bar = AnimatedBar((T.GOLD_HI, T.GOLD_LO), 4)
        self.acc_bar.setFixedWidth(130)
        acc.addWidget(self.acc_name)
        prog = QHBoxLayout()
        prog.setSpacing(6)
        prog.addWidget(self.acc_bar, 0, Qt.AlignVCenter)
        prog.addWidget(self.acc_progress)
        prog.addStretch(1)
        acc.addLayout(prog)
        line.addLayout(acc)
        line.addWidget(_Sep())
        self.step_pill = Pill("", T.GOLD)
        self.step_pill.hide()
        line.addWidget(self.step_pill, 0, Qt.AlignVCenter)
        self.action = ElidedLabel("Idle", lines=1, pt=9.25, color=T.TEXT_MUTED)
        self.action.setMinimumWidth(80)
        line.addWidget(self.action, 1, Qt.AlignVCenter)

        line.addWidget(_Sep())
        self.scout_label = label("LAST BASE", "caption")
        self.scout_label.setToolTip("Loot of the last scouted base")
        line.addWidget(self.scout_label)
        self.scout = {}
        for r in T.RESOURCES:
            v = CountLabel(fmt_short, role="metric")
            v.setFont(T.font(9.5, QFont.DemiBold))
            v.setMinimumWidth(36)
            v.setToolTip(f"{T.RESOURCE_NAME[r]} of the last scouted base")
            self.scout[r] = v
            line.addWidget(ResourceIcon(r, 15))
            line.addWidget(v)
        line.addWidget(_Sep())
        self.stat_values, self.stat_boxes = {}, {}
        for key, title in STATS:
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(4)
            name = label(title, "small")
            v = CountLabel(role="metric")
            v.setFont(T.font(9.5, QFont.DemiBold))
            v.set_value(0)
            bl.addWidget(name)
            bl.addWidget(v)
            self.stat_values[key] = v
            self.stat_boxes[key] = box
            box.setVisible(key in ALWAYS_STATS)
            line.addWidget(box)
        line.addWidget(_Sep())
        clock = QLabel()
        clock.setPixmap(icons.pixmap("clock", T.TEXT_MUTED, 13))
        clock.setToolTip("Run time")
        self.run_time = label("—", "small")
        self.run_time.setFont(T.font(8.25, QFont.DemiBold, mono=True))
        self.run_time.setToolTip("Run time")
        line.addWidget(clock)
        line.addWidget(self.run_time)
        line.addSpacing(4)
        self.clear_btn = IconButton("trash", "Clear this view")
        self.full_btn = Button("Full log", "arrow-right", "ghost", "sm")
        line.addWidget(self.clear_btn)
        line.addWidget(self.full_btn)
        lay.addLayout(line)

        self.log_view = LogView(3000)
        self.log_view.setMinimumHeight(48)
        lay.addWidget(self.log_view, 1)
        self.clear_btn.clicked.connect(self.log_view.clear)
        self.full_btn.clicked.connect(self.show_log_clicked)
        self._started = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._compact = None
        self.set_running(False)

    # --- run state
    def set_running(self, running):
        self._running = running
        self._paused = False
        self._waiting = False
        if running:
            self._started = time.time()
            self.run_time.setText("0:00:00")
            for v in self.scout.values():
                v.set_value(None)
            for k, v in self.stat_values.items():
                v.set_value(0)
                self.stat_boxes[k].setVisible(k in ALWAYS_STATS)
            self.acc_bar.set_value(0)
            self.acc_progress.setText("")
            self._set_action("Starting…")
        else:
            self._started = None
            self._set_step(None)
            self._set_action("Idle")

    def set_paused(self, paused):
        self._paused = paused
        if paused:
            self._set_action(f"Paused: you can use the game. Press Resume ({self._keys.get('pause', '').upper()}) "
                             "to go on.", T.AMBER)
        else:
            self._set_action(self._last_action)

    def set_hotkeys(self, keys):
        self._keys = dict(keys)

    _last_action = "Idle"

    def _set_action(self, text, color=None):
        if color is None:
            self._last_action = text
        self.action.setText(text)
        self.action.set_color(color or (T.TEXT if self._running else T.TEXT_MUTED))

    def _set_step(self, key_or_title):
        if not key_or_title:
            self._step_title = ""
            self.step_pill.hide()
            return
        step = BY_KEY.get(key_or_title)
        title = step.title if step else str(key_or_title)
        self._step_title = title
        self.step_pill.set(title, T.GOLD)
        self.step_pill.show()

    def update_status(self, st):
        if "account" in st:
            name = str(st["account"] or "—")
            self.acc_name.setText(name)
            self.avatar.set_name(name if st["account"] else "")
        if "progress" in st:
            prog = str(st.get("progress") or "")
            self.acc_progress.setText(prog.replace("/", " / "))
            m = re.match(r"\s*(\d+)\s*/\s*(\d+)", prog)
            self.acc_bar.set_value(int(m.group(1)) / int(m.group(2)) if m and int(m.group(2)) else 0)
        if st.get("step"):
            self._set_step(st["step"])
        if "action" in st:
            text = str(st["action"] or "")
            key = step_of(text)
            if key:
                self._set_step(key)
            if not self._paused and not self._waiting:
                self._set_action(text)
            else:
                self._last_action = text
        if st.get("loot"):
            for r, v in st["loot"].items():
                if r in self.scout:
                    self.scout[r].set_value(v)
        if "stats" in st:
            s = st["stats"] or {}
            for key, v in self.stat_values.items():
                if key in s:
                    v.set_value(s.get(key) or 0)
                self.stat_boxes[key].setVisible(key in ALWAYS_STATS or bool(v.value()))
        if st.get("waiting"):
            self._waiting = True
            key = self._keys.get("continue", "").upper()
            self._set_action(f"Waiting for you: {st.get('action') or 'the account is full'}. Spend the resources, "
                             f"then press Continue ({key}).", T.AMBER)
        elif st.get("waiting") is False:
            self._waiting = False
            self._set_action(self._last_action)

    def current_step(self):
        """The function key that runs now (from the status), or None."""
        return next((k for k, s in BY_KEY.items() if s.title == self._step_title), None)

    def resizeEvent(self, e):
        compact = self.width() < 1180
        if compact != self._compact:
            self._compact = compact
            self.scout_label.setVisible(not compact)
            self.acc_name.setFixedWidth(104 if compact else 130)
            self.acc_bar.setFixedWidth(104 if compact else 130)
            self.full_btn.set_text("" if compact else "Full log")
            self.full_btn.setToolTip("Full log" if compact else "")
        super().resizeEvent(e)

    def _tick(self):
        if self._started:
            s = int(time.time() - self._started)
            self.run_time.setText(f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}")

    def append_log(self, msg, level):
        self.log_view.append(msg, level)


class _BadgeOverlay(QWidget):
    """Paints the badge on top of the button (a later child paints over the earlier ones)."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _):
        owner = self.owner
        if not owner.badge_text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = T.font(7.25, QFont.Bold)
        w = max(18, QFontMetrics(f).horizontalAdvance(owner.badge_text) + 10)
        r = QRectF(self.width() - w - 1, 1, w, 17)
        p.setPen(QPen(QColor(T.SIDEBAR), 2))
        p.setBrush(owner.badge_color)
        p.drawRoundedRect(r, 8.5, 8.5)
        p.setFont(f)
        p.setPen(QColor("#1e1400" if owner.badge_color.lightness() > 150 else "#ffffff"))
        p.drawText(r, Qt.AlignCenter, owner.badge_text)


class Badged(QWidget):
    """A button with a small count badge on its top-right corner (missing templates, unseen warnings)."""

    def __init__(self, button, parent=None):
        super().__init__(parent)
        self.button = button
        self.badge_text = ""
        self.badge_color = QColor(T.RED)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 7, 9, 0)
        lay.addWidget(button)
        self._overlay = _BadgeOverlay(self)

    def set_badge(self, text, color=T.RED):
        self.badge_text = str(text or "")
        self.badge_color = QColor(color)
        self._overlay.update()

    def resizeEvent(self, e):
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()
        super().resizeEvent(e)

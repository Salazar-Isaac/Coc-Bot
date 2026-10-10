"""Run tab: choose a mode and options, start/pause/stop, watch status and the log."""

import logging
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout, QWidget)

from bot.modes import MODES, load_all

WHEN_FULL = [("switch", "Switch to the next account"), ("wait", "Wait for me (I spend, then Continue)"),
             ("stop", "Stop the run")]
WHEN_DONE = [("nothing", "Do nothing"), ("close_game", "Close the game"), ("shutdown", "Shut down the PC"),
             ("sleep", "Put the PC to sleep")]

LEVEL_COLORS = {logging.WARNING: QColor(200, 120, 0), logging.ERROR: QColor(210, 40, 40),
                logging.CRITICAL: QColor(210, 40, 40)}


def _fmt(v):
    return f"{v:,}" if isinstance(v, int) else "-"


class RunTab(QWidget):
    start_clicked = Signal()
    pause_clicked = Signal()
    continue_clicked = Signal()
    stop_clicked = Signal()
    cancel_shutdown_clicked = Signal()
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        load_all()
        root = QHBoxLayout(self)

        # ---------------- left: controls ----------------
        left = QVBoxLayout()
        root.addLayout(left, 0)

        mode_box = QGroupBox("What should the bot do?")
        ml = QVBoxLayout(mode_box)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for key, mode in sorted(MODES.items(), key=lambda kv: (not kv[1].ready, kv[1].order)):
            rb = QRadioButton(mode.title + ("" if mode.ready else "  (coming next)"))
            rb.setEnabled(mode.ready)
            rb.setProperty("mode_key", key)
            self.mode_group.addButton(rb)
            self.mode_buttons[key] = rb
            ml.addWidget(rb)
        self.mode_desc = QLabel()
        self.mode_desc.setWordWrap(True)
        self.mode_desc.setStyleSheet("padding:4px 2px; font-style:italic;")
        ml.addWidget(self.mode_desc)
        self.mode_group.buttonToggled.connect(self._mode_changed)
        left.addWidget(mode_box)

        opt_box = QGroupBox("Options")
        form = QFormLayout(opt_box)
        self.when_full = QComboBox()
        for k, t in WHEN_FULL:
            self.when_full.addItem(t, k)
        form.addRow("When an account is full:", self.when_full)
        self.when_done = QComboBox()
        for k, t in WHEN_DONE:
            self.when_done.addItem(t, k)
        form.addRow("When the run ends:", self.when_done)
        self.rounds = QSpinBox()
        self.rounds.setRange(0, 999)
        self.rounds.setSpecialValueText("Forever")
        form.addRow("Rounds over all accounts:", self.rounds)
        self.current_account = QComboBox()
        self.current_account.setEditable(True)
        self.current_th = QSpinBox()
        self.current_th.setRange(0, 25)
        self.current_th.setSpecialValueText("unknown")
        self.current_label = QLabel("Account open now:")
        self.current_th_label = QLabel("Its Town Hall:")
        form.addRow(self.current_label, self.current_account)
        form.addRow(self.current_th_label, self.current_th)
        self.resume = QCheckBox("Continue from the account where the last run stopped")
        self.resume.setChecked(True)
        form.addRow(self.resume)
        left.addWidget(opt_box)
        for w in (self.when_full, self.when_done, self.current_account):
            w.currentIndexChanged.connect(self.changed)
        self.current_account.editTextChanged.connect(self.changed)
        self.rounds.valueChanged.connect(self.changed)
        self.current_th.valueChanged.connect(self.changed)

        btns = QGridLayout()
        self.start_btn = QPushButton("▶  Start")
        self.pause_btn = QPushButton("Pause  (F9)")
        self.continue_btn = QPushButton("Continue  (F8)")
        self.stop_btn = QPushButton("■  Stop  (F10)")
        self.cancel_shutdown_btn = QPushButton("Cancel shutdown")
        self.start_btn.setObjectName("start")
        self.stop_btn.setObjectName("stop")
        for b in (self.start_btn, self.pause_btn, self.continue_btn, self.stop_btn, self.cancel_shutdown_btn):
            b.setMinimumHeight(38)
        btns.addWidget(self.start_btn, 0, 0)
        btns.addWidget(self.stop_btn, 0, 1)
        btns.addWidget(self.pause_btn, 1, 0)
        btns.addWidget(self.continue_btn, 1, 1)
        btns.addWidget(self.cancel_shutdown_btn, 2, 0, 1, 2)
        left.addLayout(btns)
        left.addStretch(1)
        self.start_btn.clicked.connect(self.start_clicked)
        self.pause_btn.clicked.connect(self.pause_clicked)
        self.continue_btn.clicked.connect(self.continue_clicked)
        self.stop_btn.clicked.connect(self.stop_clicked)
        self.cancel_shutdown_btn.clicked.connect(self.cancel_shutdown_clicked)
        self.cancel_shutdown_btn.hide()

        # ---------------- right: status + log ----------------
        right = QVBoxLayout()
        root.addLayout(right, 1)
        st_box = QGroupBox("Status")
        grid = QGridLayout(st_box)
        self.status_labels = {}
        rows = [("state", "State"), ("device", "Device"), ("account", "Account"), ("action", "Doing"),
                ("gold", "Gold"), ("elixir", "Elixir"), ("dark", "Dark elixir"), ("loot", "Last scouted"),
                ("attacks", "Attacks / searches"), ("time", "Run time")]
        for i, (k, title) in enumerate(rows):
            t = QLabel(title + ":")
            v = QLabel("-")
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            f = v.font()
            f.setBold(True)
            v.setFont(f)
            grid.addWidget(t, i // 2, (i % 2) * 2)
            grid.addWidget(v, i // 2, (i % 2) * 2 + 1)
            self.status_labels[k] = v
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        right.addWidget(st_box)

        log_box = QGroupBox("Log")
        ll = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setFont(QFont("Consolas", 9))
        ll.addWidget(self.log_view)
        right.addWidget(log_box, 1)

        self._started = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self.set_running(False)

    # ------------------------------------------------------------------ settings
    def load(self, settings, accounts):
        key = settings.get("mode", "loot_all")
        btn = self.mode_buttons.get(key) or self.mode_buttons.get("loot_all")
        btn.setChecked(True)
        self._select(self.when_full, settings.get("when_full", "switch"))
        self._select(self.when_done, settings.get("when_done", "nothing"))
        self.rounds.setValue(settings.get("repeat_rounds", 1))
        self.set_accounts(accounts)
        self.current_account.setCurrentText(settings.get("current_account", ""))
        self.current_th.setValue(settings.get("current_th", 0))
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

    @staticmethod
    def _select(combo, data):
        i = combo.findData(data)
        combo.setCurrentIndex(max(0, i))

    def mode_key(self):
        b = self.mode_group.checkedButton()
        return b.property("mode_key") if b else "loot_all"

    def _mode_changed(self, *_):
        key = self.mode_key()
        mode = MODES.get(key)
        self.mode_desc.setText(mode.description if mode else "")
        current = key == "loot_current"
        for w in (self.current_account, self.current_th, self.current_label, self.current_th_label):
            w.setVisible(current)
        self.rounds.setEnabled(not current)
        self.resume.setEnabled(key == "loot_all")
        self.changed.emit()

    # ------------------------------------------------------------------ status
    def set_running(self, running):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.pause_btn.setEnabled(running)
        self.continue_btn.setEnabled(False)
        for b in self.mode_buttons.values():
            b.setEnabled(not running and MODES[b.property("mode_key")].ready)
        if running:
            self._started = time.time()
            self.status_labels["state"].setText("Running")
        else:
            self._started = None
            self.status_labels["state"].setText("Idle")
            self.pause_btn.setText("Pause  (F9)")

    def set_paused(self, paused):
        self.pause_btn.setText("Resume  (F9)" if paused else "Pause  (F9)")
        self.status_labels["state"].setText("Paused" if paused else "Running")

    def update_status(self, st):
        L = self.status_labels
        if "device" in st:
            L["device"].setText(st["device"])
        if "account" in st:
            L["account"].setText(str(st["account"]) + (f"  ({st['progress']})" if st.get("progress") else ""))
        if "action" in st:
            L["action"].setText(st["action"])
        if "fullness" in st:
            for r, (v, cap, full) in st["fullness"].items():
                L[r].setText(f"{_fmt(v)} / {_fmt(cap) if cap else 'no limit'}" + ("  FULL" if full else ""))
        if "resources" in st:
            for r, v in st["resources"].items():
                if "fullness" not in st or r not in st["fullness"]:
                    L[r].setText(_fmt(v))
        if "loot" in st and st["loot"]:
            lo = st["loot"]
            L["loot"].setText(f"{_fmt(lo.get('gold'))} / {_fmt(lo.get('elixir'))} / {_fmt(lo.get('dark'))}")
        if "stats" in st:
            s = st["stats"]
            L["attacks"].setText(f"{s.get('attacks', 0)} / {s.get('searches', 0)}")
        if st.get("waiting"):
            self.continue_btn.setEnabled(True)
            L["state"].setText("Waiting for you - press Continue (F8)")
        elif st.get("waiting") is False:
            self.continue_btn.setEnabled(False)
            L["state"].setText("Running")
        if st.get("shutdown_pending"):
            self.cancel_shutdown_btn.show()

    def _tick(self):
        if self._started:
            s = int(time.time() - self._started)
            self.status_labels["time"].setText(f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}")

    def append_log(self, msg, level):
        fmt = QTextCharFormat()
        if level in LEVEL_COLORS:
            fmt.setForeground(LEVEL_COLORS[level])
        cursor = self.log_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(msg + "\n", fmt)
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

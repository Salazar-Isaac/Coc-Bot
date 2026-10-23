"""Left column of the window: the ready-made options (Loot all accounts, Loot + Donate, Home loot +
upgrade, ...). One click picks what the bot does; the steps it runs are listed under it, and each
step's settings are in the sections on the right.

Picking an option also sets each step's accounts from the roles on the Accounts list (Loot +
Donate: only the Main and the Looters loot, the others request). Upgrades and research never run
on the Main or the Looters (accounts 1-2).
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from bot.flow import BY_KEY, OPTION, OPTIONS, DEFAULT_OPTION, option_flow
from gui import icons
from gui import theme as T
from gui.components import Card, ChoiceCard, FlowLayout, Pill, SettingRow, Toggle, label, scroll
from gui.widgets import Combo

SHORT = {"attack_all": "Loot", "loot_current": "Loot current", "donate": "Donate", "bb_attack": "Builder loot",
         "bb_attack_current": "Current account",
         "home_upgrade": "Home upgrade", "walls": "Walls", "bb_upgrade": "Builder upgrade", "home_research": "Lab research",
         "bb_research": "Star Lab research", "raid": "Capital raid"}

GROUP_LOOK = {
    "Loot": (T.GOLD, "Loot"),
    "Donate": (T.ELIXIR_HI, "Donate"),
    "Upgrade": (T.GREEN, "Upgrade · accounts 1-2 (Main, Looter) are never upgraded"),
    "Raid": ("#ff9f43", "Raid · Clan Capital, Friday to Monday"),
}


class StepRow(QPushButton):
    """One step of the chosen option: number, icon, title, and what it works on (13 accounts)."""

    def __init__(self, n, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setFixedHeight(30)
        step = BY_KEY[key]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 10, 0)
        lay.setSpacing(6)
        self.num = QLabel(str(n))
        self.num.setFixedSize(20, 20)
        self.num.setAlignment(Qt.AlignCenter)
        icon = QLabel()
        icon.setPixmap(icons.pixmap(step.icon, T.TEXT_MUTED, 15))
        self.title = label(SHORT.get(key, step.title), "rowTitle")
        self.detail = label("", "small")
        self.detail.setStyleSheet(f"color: {T.TEXT_DIM};")
        for w in (self.num, icon, self.title):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(w)
        self.set_running(False)
        self.set_detail("")

    def sizeHint(self):
        return self.layout().sizeHint().expandedTo(QSize(60, 30))     # as wide as its number, icon and title

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_detail(self, text):
        self.detail.setText(text)
        self.setToolTip(f"{BY_KEY[self.key].title}{' · ' + text if text else ''}<br>Click: show its settings")

    def set_running(self, on):
        color = T.GOLD if on else T.BORDER
        self.num.setStyleSheet(f"background: {T.GOLD if on else T.SURFACE}; color: {T.BG if on else T.TEXT_MUTED};"
                               f" border: 1px solid {color}; border-radius: 10px; font-size: 8pt; font-weight: 700;")
        self.setStyleSheet("QPushButton { background: transparent; border: 1px solid %s; border-radius: 8px; }"
                           "QPushButton:hover { background: rgba(232, 235, 247, 12); }" % color)


class OptionsPanel(QWidget):
    """Same interface the window used for the flow box: changed, step_clicked, cleared,
    preset_chosen, keys(), load/apply, set_running, set_running_key, set_details."""

    changed = Signal()
    step_clicked = Signal(str)          # a step of the chosen option was clicked: show its settings
    cleared = Signal()
    preset_chosen = Signal(dict)        # {step: roles}: the window sets the steps' accounts

    def __init__(self, parent=None):
        super().__init__(parent)
        self.locked = False
        self._option = DEFAULT_OPTION
        self._details = {}
        self._running_key = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.card = Card("What should the bot do?", "Pick one - its settings are on the right.", icon="bolt",
                         padding=14, spacing=6)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.cards = {}
        for name in ("Loot", "Donate", "Upgrade", "Raid"):
            color, head = GROUP_LOOK[name]
            cap = label(head.upper(), "caption")
            cap.setContentsMargins(2, 8 if self.cards else 0, 0, 2)
            il.addWidget(cap)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(6)
            for i, o in enumerate(o for o in OPTIONS if o.group == name):
                c = ChoiceCard(o.title, o.description, o.icon, color, height=48)
                c.set_dense(True)                     # icon + title; the description shows on hover
                c.setToolTip(f"<b>{o.title}</b><br>{o.description}")
                c.setProperty("option", o.key)
                self.group.addButton(c)
                self.cards[o.key] = c
                grid.addWidget(c, i // 2, i % 2)
            il.addLayout(grid)
        self.research_home = Toggle()
        self.research_bb = Toggle()
        self.research_rows = [
            SettingRow("Also research in the Laboratory", "After the home upgrades (list in its section)",
                       self.research_home),
            SettingRow("Also research in the Star Laboratory", "After the Builder Base upgrades",
                       self.research_bb),
        ]
        for r in self.research_rows:
            il.addWidget(r)
        il.addStretch(1)
        self.card.add(scroll(inner, margins=(0, 0, 8, 0)), 1)
        lay.addWidget(self.card, 1)

        self.steps_card = Card("It runs", icon="flow", padding=14, spacing=6)
        self.count_pill = Pill("", T.TEXT_MUTED)
        self.steps_card.add_action(self.count_pill)
        steps = QWidget()
        self.steps_box = FlowLayout(steps, 6, 6)
        self.steps_card.add(steps)
        self.start_combo = Combo()
        self.start_combo.setMinimumWidth(230)
        self.start_combo.setToolTip("The account the run starts with. It follows the run (it shows the account the "
                                    "bot is on), so after a stop the next run goes on from there; after a whole round "
                                    "it is back at #1. Upgrades never run on accounts 1-2, also when you start at #1.")
        self.start_row = SettingRow("Start from account", "Moves along as the bot changes account", self.start_combo,
                                    240)
        self.steps_card.add(self.start_row)
        self._accounts = []
        self._start = 1
        self.steps_card.title_label.setToolTip("Account by account: each account does these in this order, then "
                                               "the next account. Click one for its settings.")
        lay.addWidget(self.steps_card)

        self.step_rows = []
        self.group.buttonClicked.connect(self._chosen)
        self.start_combo.currentIndexChanged.connect(self._start_changed)
        self.research_home.toggled.connect(self._research_changed)
        self.research_bb.toggled.connect(self._research_changed)
        self._sync()

    # --- api used by the window
    def keys(self):
        return option_flow(self._option, {"home": self.research_home.isChecked(),
                                          "builder": self.research_bb.isChecked()})

    def option(self):
        return OPTION.get(self._option) or OPTION[DEFAULT_OPTION]

    def set_current(self, key):
        pass

    def append(self, key):
        pass

    def flash_flow(self):
        pass

    def set_details(self, details):
        self._details = dict(details or {})
        for r in self.step_rows:
            r.set_detail(self._details.get(r.key, ""))

    def set_running_key(self, key):
        self._running_key = key
        for r in self.step_rows:
            r.set_running(r.key == key)

    def set_running(self, running):
        self.locked = running
        for c in self.cards.values():
            c.setEnabled(not running or c.isChecked())
        for t in (self.research_home, self.research_bb):
            t.setEnabled(not running)
        self.start_combo.setEnabled(not running)          # it follows the run meanwhile
        if not running:
            self.set_running_key(None)
        self._sync()

    def load(self, settings, accounts):
        key = settings.get("option")
        rt = settings.get("research_too") or {}
        flow = [k for k in settings.get("flow", []) if k in BY_KEY]
        if key not in OPTION or option_flow(key, rt) != flow:
            # settings from before the options (or edited by hand): the option whose steps match the flow
            key = next((o.key for o in OPTIONS if list(o.steps) == [k for k in flow if not k.endswith("research")]),
                       key if key in OPTION else DEFAULT_OPTION)
        self._option = key
        for t, v in ((self.research_home, rt.get("home")), (self.research_bb, rt.get("builder"))):
            t.blockSignals(True)
            t.setChecked(bool(v))
            t.blockSignals(False)
        self.cards[key].setChecked(True)
        self._start = max(1, int(settings.get("start_from", 1) or 1))
        self.set_accounts(accounts)
        self._sync()

    def apply(self, settings, accounts):
        settings["start_from"] = self._start
        settings["option"] = self._option
        settings["research_too"] = {"home": self.research_home.isChecked(), "builder": self.research_bb.isChecked()}
        settings["flow"] = self.keys()
        settings["mode"] = "flow"

    def set_accounts(self, accounts):
        """The accounts for "Start from account" (#position, name, Town Hall), from the Accounts table."""
        self._accounts = [dict(a) for a in (accounts or [])]
        self._fill_start()

    def set_start(self, pos):
        """The run moved to account #pos (or finished a round: #1)."""
        self._start = max(1, int(pos or 1))
        self._fill_start()
        self.changed.emit()                               # saved, so a later run goes on from here

    def _fill_start(self):
        c = self.start_combo
        c.blockSignals(True)
        c.clear()
        for i, a in enumerate(self._accounts):
            if not a.get("enabled", True) or a.get("role") == "skip":
                continue
            th = a.get("th")
            c.addItem(f"#{i + 1}  {a.get('name', '?')}{f' · TH {th}' if th else ''}", i + 1)
        if self._start > len(self._accounts) and self._accounts:
            c.addItem("All accounts done: donating", self._start)     # "Upgrade, loot, donate" after its pass
        if c.count():
            idx = c.findData(self._start)
            if idx < 0:                                   # that account is off now: the next one after it
                later = [j for j in range(c.count()) if c.itemData(j) > self._start]
                idx = later[0] if later else 0
            c.setCurrentIndex(idx)
        c.blockSignals(False)

    def _start_changed(self, *_):
        data = self.start_combo.currentData()
        if data and not self.locked:
            self._start = int(data)
            self.changed.emit()

    # --- internals
    def _chosen(self, card):
        key = card.property("option")
        if self.locked or key == self._option:
            return
        self._option = key
        self.preset_chosen.emit(dict(OPTION[key].roles))   # the window sets the steps' accounts first
        self._sync()
        self.changed.emit()

    def _research_changed(self, *_):
        self._sync()
        self.changed.emit()

    def _sync(self):
        steps = self.option().steps
        self.start_row.setVisible(any(BY_KEY[k].per_account for k in steps))
        self.research_rows[0].setVisible("home_upgrade" in steps)
        self.research_rows[1].setVisible("bb_upgrade" in steps)
        keys = self.keys()
        while self.steps_box.count():
            item = self.steps_box.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        self.step_rows = []
        for i, k in enumerate(keys):
            row = StepRow(i + 1, k)
            row.set_detail(self._details.get(k, ""))
            row.set_running(k == self._running_key)
            row.clicked.connect(lambda _=False, k=k: self.step_clicked.emit(k))
            self.steps_box.addWidget(row)
            self.step_rows.append(row)
        n = len(keys)
        self.count_pill.set(f"{n} step{'s' if n != 1 else ''}", T.GOLD)

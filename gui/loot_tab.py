"""Loot settings page: when an account is full, which bases to attack, how to attack, full-at table."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from bot import config
from bot.actions import attack
from gui import theme as T
from gui.components import (Button, Card, ChipToggle, ResourceIcon, Segmented, SettingRow, Toggle, divider, hbox,
                            label, scroll)
from gui.widgets import BigSpin, Combo, Spin

NAMES = T.RESOURCE_NAME
TH_LEVELS = [str(t) for t in range(19, 10, -1)]
LOOT_DEFAULTS = config.DEFAULT_SETTINGS["loot"]
DEFAULT_MARGIN = dict(getattr(config, "DEFAULT_MARGIN", LOOT_DEFAULTS.get("full_margin", {})))

# words in attack plan names (config/attack_plans.json) shown nicer in the dropdown: edrag_clone -> E-Dragons + Clone
PLAN_WORDS = {"edrag": "E-Dragons", "edrags": "E-Dragons", "lalo": "LaLo", "pekka": "P.E.K.K.A", "clone": "+ Clone",
              "rage": "+ Rage", "freeze": "+ Freeze", "th": "TH", "bk": "King", "aq": "Queen", "gw": "Warden",
              "rc": "Champion"}


def plan_title(name, plan=None):
    """Display name of an attack plan: its "title" if it has one, else the key made readable."""
    title = (plan or {}).get("title")
    if title:
        return str(title)
    words = [PLAN_WORDS.get(w.lower(), w.capitalize()) for w in str(name).replace("-", "_").split("_") if w]
    return " ".join(words) or str(name)


def crore(v):
    """3 crore storage -> '2.95' style numbers for the margin example (1 crore = 10,000,000)."""
    return f"{v / 10_000_000:.4f}".rstrip("0").rstrip(".")


class LootTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        content = QWidget()
        cols = QHBoxLayout(content)
        cols.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        right = QVBoxLayout()
        right.setSpacing(16)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)

        # --- what counts as full ---
        full = Card("When is an account full?", "Pick the storages to watch. Only Elixir = fill elixir, "
                    "then switch account.", icon="coins")
        self.watch = {}
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for r in config.RESOURCES:
            chip = ChipToggle(NAMES[r], T.RESOURCE_COLOR[r], resource=r)
            chip.toggled.connect(self.changed)
            self.watch[r] = chip
            chips.addWidget(chip)
        chips.addStretch(1)
        full.add(chips)
        self.full_rule = Segmented([("any", "Any is full"), ("all", "All are full")])
        self.full_rule.currentIndexChanged.connect(self.changed)
        full.add(SettingRow("Full when", "Of the watched storages", self.full_rule))
        full.add(divider())

        # how a storage counts as full: measured capacity minus a margin, or the Town Hall table
        self.full_mode = Segmented([("capacity", "Capacity − margin"), ("table", "Town Hall table")])
        self.full_mode.currentIndexChanged.connect(self._full_mode_changed)
        self.full_mode.currentIndexChanged.connect(self.changed)
        self.full_mode_row = SettingRow("When is a storage full", " ")          # text set by the mode
        mode_box = QWidget()
        mb = QVBoxLayout(mode_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.setSpacing(8)
        mb.addWidget(self.full_mode_row)
        mb.addWidget(self.full_mode)
        full.add(mode_box)

        self.margin_box = QWidget()
        mg = QVBoxLayout(self.margin_box)
        mg.setContentsMargins(0, 6, 0, 0)
        mg.setSpacing(4)
        self.margin_head = SettingRow("Stop this close to full", " ")          # example set live
        mg.addWidget(self.margin_head)
        self.margin = {}
        for r in config.RESOURCES:
            sp = BigSpin(maximum=10_000_000, step=100_000 if r != "dark" else 1_000)
            sp.setSpecialValueText("No margin")
            sp.setFixedWidth(170)
            sp.valueChanged.connect(self.changed)
            self.margin[r] = sp
            row = SettingRow(NAMES[r], control=sp)
            row.layout().insertWidget(0, ResourceIcon(r, 22), 0, Qt.AlignVCenter)
            mg.addWidget(row)
        self.margin["gold"].valueChanged.connect(self._margin_example)
        full.add(self.margin_box)
        left.addWidget(full)

        # --- Town Hall table (fallback in capacity mode) ---
        self.th_card = Card("Storage “full at” by Town Hall", " ", icon="layers")
        self.th_toggle = Button("Show", "chevron-down", "ghost", "sm")
        self.th_toggle.clicked.connect(self._toggle_table)
        self.th_card.add_action(self.th_toggle)
        self.th_open = False
        self.th_body = QWidget()
        grid = QGridLayout(self.th_body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(label("TOWN HALL", "caption"), 0, 0)
        for i, r in enumerate(config.RESOURCES):
            grid.addLayout(hbox(ResourceIcon(r, 16), label(NAMES[r].upper(), "caption"), None, spacing=6), 0, i + 1)
        self.full_at = {}
        for row_i, lvl in enumerate(TH_LEVELS, start=1):
            tl = label(f"TH {lvl}")
            tl.setFont(T.font(9.5, QFont.DemiBold))
            grid.addWidget(tl, row_i, 0)
            for i, r in enumerate(config.RESOURCES):
                sp = BigSpin(maximum=100_000_000, step=500_000 if r != "dark" else 10_000)
                sp.setMinimumWidth(110)
                sp.valueChanged.connect(self.changed)
                self.full_at[(lvl, r)] = sp
                grid.addWidget(sp, row_i, i + 1)
        for c in (1, 2, 3):
            grid.setColumnStretch(c, 1)
        self.th_card.add(self.th_body)
        left.addWidget(self.th_card)

        # --- who loot_all loots ---
        roles = Card("Who does “Loot all accounts” loot?", icon="users")
        self.roles = {}
        for i, (key, title, desc) in enumerate((("main", "Main", "Loots and donates to the others"),
                                                ("loot", "Loot only", "Just loot, never request troops"),
                                                ("both", "Loot + request", "Loot here and also request troops in "
                                                 "the donation modes"),
                                                ("feeder", "Feeders", "Only request troops"))):
            t = Toggle()
            t.toggled.connect(self.changed)
            self.roles[key] = t
            if i:
                roles.add(divider())
            roles.add(SettingRow(title, desc, t))
        left.addWidget(roles)
        left.addStretch(1)

        # --- army + attack ---
        atk = Card("Attack", "Which army to bring and how the bot fights once it found a base.", icon="swords")
        self.plan = Combo()
        self.plan.currentIndexChanged.connect(self._plan_changed)
        self.plan.currentIndexChanged.connect(self.changed)
        open_plans = Button("Edit plans", "edit", "ghost", "sm")
        open_plans.setToolTip("Opens config/attack_plans.json")
        open_plans.clicked.connect(lambda: os.startfile(attack.PLANS_PATH))
        self.plan_desc = label("", "rowDesc", wrap=True)
        plan_box = QWidget()
        pb = QVBoxLayout(plan_box)
        pb.setContentsMargins(0, 2, 0, 4)
        pb.setSpacing(6)
        pb.addLayout(hbox(label("Attack plan", "rowTitle"), None, open_plans))
        pb.addWidget(self.plan)
        pb.addWidget(self.plan_desc)
        atk.add(plan_box)

        self.recipe = QLineEdit()
        self.recipe.setPlaceholderText("e.g. loot (name of a Saved Recipe in the game)")
        self.recipe.setMaxLength(40)
        self.recipe.setClearButtonEnabled(True)
        self.recipe.textChanged.connect(self.changed)
        recipe_box = QWidget()
        rb = QVBoxLayout(recipe_box)
        rb.setContentsMargins(0, 2, 0, 4)
        rb.setSpacing(6)
        rb.addWidget(label("Army recipe to use before looting", "rowTitle"))
        rb.addWidget(self.recipe)
        rb.addWidget(label("Every account switches to this saved army (e.g. E-Dragons + Clone) before attacking. "
                           "Accounts without that recipe keep their army. Empty = keep each army.", "rowDesc",
                           wrap=True))
        atk.add(recipe_box)
        atk.add(divider())

        self.battle_seconds = Spin(20, 180, suffix=" s")
        atk.add(SettingRow("Max battle time", "End the battle after this many seconds", self.battle_seconds, 110))
        atk.add(divider())
        self.smart_deploy = Toggle()
        self.count_troops = Toggle()
        self.zoom = Toggle()
        atk.add(SettingRow("Detect the deploy zone (red area)",
                           "Finds the red no-deploy border and drops troops just outside it", self.smart_deploy))
        atk.add(SettingRow("Deploy exactly the troops I have (no extra taps)",
                           "Reads each troop count and taps exactly that many times", self.count_troops))
        atk.add(SettingRow("Zoom out before searching", "Shows the whole base before deploying", self.zoom))
        atk.add(divider())
        self.max_searches = Spin(5, 2000)
        self.max_attacks = Spin(0, 999, special="No limit")
        self.stuck = Spin(1, 10, suffix=" attacks")
        self.stuck.setToolTip("If storages do not grow after this many attacks, the account counts as full")
        atk.add(SettingRow("Max searches per attack", "Give up after this many “Next” and retry", self.max_searches,
                           110))
        atk.add(SettingRow("Max attacks per account", "Then go on to the next account", self.max_attacks, 110))
        atk.add(SettingRow("Full if storages stop growing", "No growth after this many attacks", self.stuck, 110))
        for w in (self.battle_seconds, self.max_searches, self.max_attacks, self.stuck):
            w.valueChanged.connect(self.changed)
        for t in (self.smart_deploy, self.count_troops, self.zoom):
            t.toggled.connect(self.changed)
        right.addWidget(atk)

        # --- which bases to attack ---
        base = Card("Which bases to attack", "Minimum loot for the watched storages. “Any” = no minimum.",
                    icon="target")
        self.min_loot = {}
        for r in config.RESOURCES:
            sp = BigSpin(maximum=10_000_000, step=100_000 if r != "dark" else 1_000)
            sp.setSpecialValueText("Any")
            sp.setFixedWidth(170)
            sp.valueChanged.connect(self.changed)
            self.min_loot[r] = sp
            row = SettingRow(f"Minimum {NAMES[r].lower()}", control=sp)
            row.layout().insertWidget(0, ResourceIcon(r, 22), 0, Qt.AlignVCenter)
            base.add(row)
        base.add(divider())
        self.min_rule = Segmented([("any", "Any is met"), ("all", "All are met")])
        self.min_rule.currentIndexChanged.connect(self.changed)
        base.add(SettingRow("Attack when", "Of the watched minimums", self.min_rule))
        right.addWidget(base)
        right.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll(content))
        self._plans = {}
        self._full_mode_changed()
        self._margin_example()

    # ------------------------------------------------------------------ helpers
    def _plan_changed(self, *_):
        plan = self._plans.get(self.plan.currentData()) or {}
        self.plan_desc.setText(plan.get("description", ""))
        self.plan_desc.setVisible(bool(plan.get("description")))

    def _margin_example(self, *_):
        m = self.margin["gold"].value()
        text = (f"e.g. 3 crore storage → loots until {crore(30_000_000 - m)} crore" if m < 30_000_000
                else "Room left in each storage when the account counts as full")
        self.margin_head.desc.setText(text)

    def _full_mode_changed(self, *_):
        """Capacity mode: margins shown, Town Hall table folded away (only a fallback). Table mode: the table."""
        capacity = self.full_mode.currentData() == "capacity"
        self.full_mode_row.desc.setText(
            "The bot measures each account's real storage size from the resource bar, so accounts with low "
            "storages are handled too." if capacity else
            "Fixed amounts per Town Hall level, from the table below.")
        self.margin_box.setVisible(capacity)
        self.th_card.title_label.setText("Town Hall table" + (" (fallback)" if capacity else ""))
        self.th_card.subtitle_label.setText(
            "Used only until the bot has measured an account's storages. An account's own “full at” "
            "(Accounts page) always wins." if capacity else
            "Set slightly below your real capacity. An account's own “full at” (Accounts page) wins over "
            "this table.")
        self.th_card.tile.set_icon("layers", T.TEXT_DIM if capacity else T.GOLD)
        self.th_card.title_label.setStyleSheet(f"color: {T.TEXT_MUTED};" if capacity else "")
        self.th_toggle.setVisible(capacity)
        self._sync_table()

    def _toggle_table(self):
        self.th_open = not self.th_open
        self._sync_table()

    def _sync_table(self):
        shown = self.th_open or self.full_mode.currentData() == "table"
        self.th_body.setVisible(shown)
        self.th_toggle.set_text("Hide" if self.th_open else "Show")
        self.th_toggle.set_icon("chevron-up" if self.th_open else "chevron-down")

    # ------------------------------------------------------------------ settings io
    def load(self, settings, accounts):
        lo = settings["loot"]
        d = LOOT_DEFAULTS
        for r in config.RESOURCES:
            self.watch[r].setChecked(bool(lo.get("watch", {}).get(r)))
            self.min_loot[r].setValue(lo.get("min_loot", {}).get(r, 0))
            margin = lo.get("full_margin") or {}
            self.margin[r].setValue(int(margin.get(r, DEFAULT_MARGIN.get(r, 0)) or 0))
        self.full_rule.setCurrentIndex(max(0, self.full_rule.findData(lo.get("full_rule", "any"))))
        self.min_rule.setCurrentIndex(max(0, self.min_rule.findData(lo.get("min_loot_rule", "any"))))
        self.full_mode.setCurrentIndex(max(0, self.full_mode.findData(lo.get("full_mode",
                                                                             d.get("full_mode", "capacity")))))
        self.recipe.setText(str(lo.get("army_recipe", d.get("army_recipe", "")) or ""))
        self.plan.blockSignals(True)
        self.plan.clear()
        try:
            self._plans = attack.load_plans()
        except (OSError, ValueError):
            self._plans = {}
        for name, plan in self._plans.items():
            self.plan.addItem(plan_title(name, plan), name)
            desc = plan.get("description", "")
            self.plan.setItemData(self.plan.count() - 1, f"{name}: {desc}" if desc else name, Qt.ToolTipRole)
        self.plan.select(lo.get("attack_plan", "edrag_spread"))
        self.plan.blockSignals(False)
        self._plan_changed()
        self.battle_seconds.setValue(lo.get("battle_seconds", 60))
        self.smart_deploy.setChecked(lo.get("smart_deploy", True))
        self.count_troops.setChecked(lo.get("count_troops", True))
        self.max_searches.setValue(lo.get("max_searches", 150))
        self.max_attacks.setValue(lo.get("max_attacks_per_account", 0))
        self.stuck.setValue(lo.get("stuck_attacks", 2))
        self.zoom.setChecked(lo.get("zoom_out", True))
        for k, t in self.roles.items():
            t.setChecked(lo.get("roles", {}).get(k, k != "feeder"))
        table = settings.get("full_at", config.DEFAULT_FULL_AT)
        for (lvl, r), sp in self.full_at.items():
            sp.setValue(table.get(lvl, config.DEFAULT_FULL_AT.get(lvl, {})).get(r, 0))
        self._full_mode_changed()
        self._margin_example()

    def apply(self, settings, accounts):
        lo = settings.setdefault("loot", {})
        lo["watch"] = {r: self.watch[r].isChecked() for r in config.RESOURCES}
        lo["min_loot"] = {r: self.min_loot[r].value() for r in config.RESOURCES}
        lo["full_rule"] = self.full_rule.currentData()
        lo["min_loot_rule"] = self.min_rule.currentData()
        lo["full_mode"] = self.full_mode.currentData()
        lo["full_margin"] = {r: self.margin[r].value() for r in config.RESOURCES}
        lo["army_recipe"] = self.recipe.text().strip()
        lo["attack_plan"] = self.plan.currentData() or lo.get("attack_plan") or "edrag_spread"
        lo["battle_seconds"] = self.battle_seconds.value()
        lo["smart_deploy"] = self.smart_deploy.isChecked()
        lo["count_troops"] = self.count_troops.isChecked()
        lo["max_searches"] = self.max_searches.value()
        lo["max_attacks_per_account"] = self.max_attacks.value()
        lo["stuck_attacks"] = self.stuck.value()
        lo["zoom_out"] = self.zoom.isChecked()
        lo["roles"] = {k: t.isChecked() for k, t in self.roles.items()}
        table = {}
        for (lvl, r), sp in self.full_at.items():
            table.setdefault(lvl, {})[r] = sp.value()
        settings["full_at"] = table

    def set_running(self, running):
        self.setEnabled(not running)

"""Loot settings page: when an account is full, which bases to attack, how to attack, full-at table."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from bot import config
from bot.actions import attack
from gui import theme as T
from gui.components import (Button, Card, ChipToggle, ResourceIcon, Segmented, SettingRow, Toggle, divider, hbox,
                            label, scroll)
from gui.widgets import BigSpin, Combo, Spin

NAMES = T.RESOURCE_NAME
TH_LEVELS = [str(t) for t in range(19, 10, -1)]


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
        left.addWidget(full)

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
        left.addWidget(base)
        left.addStretch(1)

        # --- attack ---
        atk = Card("Attack", "How the bot fights once it found a base.", icon="swords")
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

        # --- Town Hall table ---
        th = Card("Storage “full at” by Town Hall", "Set slightly below your real capacity. An account's own "
                  "value (Accounts page) wins over this table.", icon="layers")
        grid = QGridLayout()
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
        th.add(grid)
        right.addWidget(th)
        right.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll(content))
        self._plans = {}

    def _plan_changed(self, *_):
        plan = self._plans.get(self.plan.currentData()) or {}
        self.plan_desc.setText(plan.get("description", ""))
        self.plan_desc.setVisible(bool(plan.get("description")))

    def load(self, settings, accounts):
        lo = settings["loot"]
        for r in config.RESOURCES:
            self.watch[r].setChecked(bool(lo.get("watch", {}).get(r)))
            self.min_loot[r].setValue(lo.get("min_loot", {}).get(r, 0))
        self.full_rule.setCurrentIndex(max(0, self.full_rule.findData(lo.get("full_rule", "any"))))
        self.min_rule.setCurrentIndex(max(0, self.min_rule.findData(lo.get("min_loot_rule", "any"))))
        self.plan.blockSignals(True)
        self.plan.clear()
        try:
            self._plans = attack.load_plans()
        except (OSError, ValueError):
            self._plans = {}
        for name, plan in self._plans.items():
            self.plan.addItem(name, name)
            self.plan.setItemData(self.plan.count() - 1, plan.get("description", ""), Qt.ToolTipRole)
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

    def apply(self, settings, accounts):
        lo = settings.setdefault("loot", {})
        lo["watch"] = {r: self.watch[r].isChecked() for r in config.RESOURCES}
        lo["min_loot"] = {r: self.min_loot[r].value() for r in config.RESOURCES}
        lo["full_rule"] = self.full_rule.currentData()
        lo["min_loot_rule"] = self.min_rule.currentData()
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

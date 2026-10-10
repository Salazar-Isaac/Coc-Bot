"""Loot Settings tab."""

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from bot import config
from bot.actions import attack
from gui.widgets import BigSpin

NAMES = {"gold": "Gold", "elixir": "Elixir", "dark": "Dark elixir"}
TH_LEVELS = [str(t) for t in range(19, 10, -1)]


class LootTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        right = QVBoxLayout()
        root.addLayout(left, 1)
        root.addLayout(right, 1)

        # --- what counts as full ---
        full_box = QGroupBox("When is an account full?")
        fl = QVBoxLayout(full_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Watch:"))
        self.watch = {}
        for r in config.RESOURCES:
            cb = QCheckBox(NAMES[r])
            cb.toggled.connect(self.changed)
            self.watch[r] = cb
            row.addWidget(cb)
        row.addStretch(1)
        fl.addLayout(row)
        self.full_rule = QComboBox()
        self.full_rule.addItem("when ANY watched resource is full", "any")
        self.full_rule.addItem("when ALL watched resources are full", "all")
        self.full_rule.currentIndexChanged.connect(self.changed)
        fl.addWidget(self.full_rule)
        roles_row = QHBoxLayout()
        roles_row.addWidget(QLabel("\"Loot all accounts\" includes:"))
        self.roles = {}
        for key, label in (("main", "Main"), ("loot", "Loot only"), ("feeder", "Feeders")):
            cb = QCheckBox(label)
            cb.toggled.connect(self.changed)
            self.roles[key] = cb
            roles_row.addWidget(cb)
        roles_row.addStretch(1)
        fl.addLayout(roles_row)
        hint = QLabel("Tick only Elixir to \"fill elixir, then switch account\".")
        hint.setStyleSheet("font-style:italic;")
        fl.addWidget(hint)
        left.addWidget(full_box)

        # --- which bases to attack ---
        base_box = QGroupBox("Which bases to attack")
        bf = QFormLayout(base_box)
        self.min_loot = {}
        for r in config.RESOURCES:
            sp = BigSpin(maximum=10_000_000, step=100_000 if r != "dark" else 1_000)
            sp.setSpecialValueText("any")
            sp.valueChanged.connect(self.changed)
            self.min_loot[r] = sp
            bf.addRow(f"Minimum {NAMES[r].lower()}:", sp)
        self.min_rule = QComboBox()
        self.min_rule.addItem("attack when ANY watched minimum is met", "any")
        self.min_rule.addItem("attack only when ALL watched minimums are met", "all")
        self.min_rule.currentIndexChanged.connect(self.changed)
        bf.addRow(self.min_rule)
        left.addWidget(base_box)

        # --- attack ---
        atk_box = QGroupBox("Attack")
        af = QFormLayout(atk_box)
        self.plan = QComboBox()
        self.plan.currentIndexChanged.connect(self.changed)
        plan_row = QHBoxLayout()
        plan_row.addWidget(self.plan, 1)
        open_plans = QPushButton("Edit plans…")
        open_plans.setToolTip("Opens config/attack_plans.json")
        open_plans.clicked.connect(lambda: os.startfile(attack.PLANS_PATH))
        plan_row.addWidget(open_plans)
        af.addRow("Attack plan:", plan_row)
        self.battle_seconds = QSpinBox()
        self.battle_seconds.setRange(10, 180)
        self.battle_seconds.setSuffix(" s")
        af.addRow("End the battle after:", self.battle_seconds)
        self.max_searches = QSpinBox()
        self.max_searches.setRange(5, 2000)
        af.addRow("Max searches per attack:", self.max_searches)
        self.max_attacks = QSpinBox()
        self.max_attacks.setRange(0, 999)
        self.max_attacks.setSpecialValueText("no limit")
        af.addRow("Max attacks per account:", self.max_attacks)
        self.stuck = QSpinBox()
        self.stuck.setRange(1, 10)
        self.stuck.setToolTip("If storages do not grow after this many attacks, the account counts as full")
        af.addRow("Full if no growth after:", self.stuck)
        self.zoom = QCheckBox("Zoom out before searching")
        af.addRow(self.zoom)
        for w in (self.battle_seconds, self.max_searches, self.max_attacks, self.stuck):
            w.valueChanged.connect(self.changed)
        self.zoom.toggled.connect(self.changed)
        left.addWidget(atk_box)
        left.addStretch(1)

        # --- Town Hall table ---
        th_box = QGroupBox("Storage \"full at\" amounts by Town Hall")
        grid = QGridLayout(th_box)
        grid.addWidget(QLabel("Town Hall"), 0, 0)
        for i, r in enumerate(config.RESOURCES):
            grid.addWidget(QLabel(NAMES[r]), 0, i + 1)
        self.full_at = {}
        for row_i, th in enumerate(TH_LEVELS, start=1):
            grid.addWidget(QLabel(f"TH {th}"), row_i, 0)
            for i, r in enumerate(config.RESOURCES):
                sp = BigSpin(maximum=100_000_000, step=500_000 if r != "dark" else 10_000)
                sp.valueChanged.connect(self.changed)
                self.full_at[(th, r)] = sp
                grid.addWidget(sp, row_i, i + 1)
        note = QLabel("Set these slightly below your real storage capacity. "
                      "An account's own value in the Accounts tab wins over this table.")
        note.setWordWrap(True)
        note.setStyleSheet("font-style:italic;")
        grid.addWidget(note, len(TH_LEVELS) + 1, 0, 1, 4)
        right.addWidget(th_box)
        right.addStretch(1)

    def load(self, settings, accounts):
        lo = settings["loot"]
        for r in config.RESOURCES:
            self.watch[r].setChecked(bool(lo["watch"].get(r)))
            self.min_loot[r].setValue(lo["min_loot"].get(r, 0))
        self.full_rule.setCurrentIndex(max(0, self.full_rule.findData(lo["full_rule"])))
        self.min_rule.setCurrentIndex(max(0, self.min_rule.findData(lo["min_loot_rule"])))
        self.plan.blockSignals(True)
        self.plan.clear()
        for name, plan in attack.load_plans().items():
            self.plan.addItem(f"{name} - {plan.get('description', '')}", name)
        self.plan.setCurrentIndex(max(0, self.plan.findData(lo["attack_plan"])))
        self.plan.blockSignals(False)
        self.battle_seconds.setValue(lo["battle_seconds"])
        self.max_searches.setValue(lo["max_searches"])
        self.max_attacks.setValue(lo["max_attacks_per_account"])
        self.stuck.setValue(lo.get("stuck_attacks", 2))
        self.zoom.setChecked(lo.get("zoom_out", True))
        for k, cb in self.roles.items():
            cb.setChecked(lo.get("roles", {}).get(k, k != "feeder"))
        table = settings.get("full_at", config.DEFAULT_FULL_AT)
        for (th, r), sp in self.full_at.items():
            sp.setValue(table.get(th, config.DEFAULT_FULL_AT.get(th, {})).get(r, 0))

    def apply(self, settings, accounts):
        lo = settings["loot"]
        lo["watch"] = {r: self.watch[r].isChecked() for r in config.RESOURCES}
        lo["min_loot"] = {r: self.min_loot[r].value() for r in config.RESOURCES}
        lo["full_rule"] = self.full_rule.currentData()
        lo["min_loot_rule"] = self.min_rule.currentData()
        lo["attack_plan"] = self.plan.currentData() or "edrag_spread"
        lo["battle_seconds"] = self.battle_seconds.value()
        lo["max_searches"] = self.max_searches.value()
        lo["max_attacks_per_account"] = self.max_attacks.value()
        lo["stuck_attacks"] = self.stuck.value()
        lo["zoom_out"] = self.zoom.isChecked()
        lo["roles"] = {k: cb.isChecked() for k, cb in self.roles.items()}
        table = {}
        for (th, r), sp in self.full_at.items():
            table.setdefault(th, {})[r] = sp.value()
        settings["full_at"] = table

    def set_running(self, running):
        self.setEnabled(not running)

"""Builder Base page: the night village. Star Bonus attacks, collecting, upgrades and Star Laboratory research."""

import copy

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from bot import config
from bot.actions import builder_base
from gui import icons
from gui import theme as T
from gui.components import (Banner, Card, ChipToggle, FlowLayout, Pill, SettingRow, TagEditor, Toggle, divider, label,
                            scroll)
from gui.village_tab import ROLES
from gui.widgets import BigSpin, Combo, Spin

BB_ARMIES = [("auto", "Auto: P.E.K.K.A, else Sneaky Archer", "Best unlocked: P.E.K.K.A when the Builder Base has it, otherwise Sneaky Archers"),
             ("keep", "Keep each account's army", "Never change the Builder Base army"),
             ("pekka", "P.E.K.K.A"), ("night_witch", "Night Witch"), ("archer", "Sneaky Archer"),
             ("barbarian", "Raged Barbarian"), ("boxer_giant", "Boxer Giant"), ("bomber", "Bomber"),
             ("cannon_cart", "Cannon Cart"), ("drop_ship", "Drop Ship"), ("hog_glider", "Hog Glider"),
             ("beta_minion", "Beta Minion"), ("baby_dragon", "Baby Dragon"),
             ("electrofire_wizard", "Electrofire Wizard")]
NIGHT = "#8c9bff"          # accent of the Builder Base (same as its mode card on the Dashboard)

# the source of truth for keys and defaults is bot/config.py
DEFAULTS = copy.deepcopy(config.DEFAULT_SETTINGS.get("builder", {}))

# the Builder-Hall-first upgrade order the bot follows (bot/actions/builder_base.py)
GEAR_UP_ORDER = list(getattr(builder_base, "GEAR_UP_ORDER", []))

# suggestions for the "Never upgrade" box (part of a name is enough, these just save typing)
BB_BUILDINGS = sorted({n for n in GEAR_UP_ORDER if not n.startswith("__")} | {
    "Builder Hall", "Wall", "Battle Machine", "Battle Copter", "Gold Mine", "Elixir Collector", "Gem Mine",
    "Gold Storage", "Elixir Storage", "Builder Barracks", "Star Laboratory", "Clock Tower", "Builder's Hut",
    "O.T.T.O's Outpost", "Healing Hut", "Reinforcement Camp", "Army Camp", "Double Cannon", "Archer Tower",
    "Hidden Tesla", "Firecrackers", "Crusher", "Guard Post", "Air Bombs", "Multi Mortar", "Roaster",
    "Giant Cannon", "Mega Tesla", "Lava Launcher", "X-Bow", "Push Trap", "Spring Trap", "Mine", "Mega Mine"},
    key=str.lower)
BB_TROOPS = ["Raged Barbarian", "Sneaky Archer", "Boxer Giant", "Beta Minion", "Bomber", "Baby Dragon",
             "Cannon Cart", "Night Witch", "Drop Ship", "Power P.E.K.K.A", "Hog Glider", "Electrofire Wizard"]


def _list_block(title, description, editor):
    """A title + description with a tag editor under it (fills the card's width)."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.addWidget(SettingRow(title, description))
    lay.addWidget(editor)
    return w


def _gear_up_path():
    """The first steps of the gear-up order as little tags: Builder Hall › New buildings › Cannon › …"""
    w = QWidget()
    flow = FlowLayout(w, 6, 6)
    steps = [("New buildings" if n == "__new__" else n) for n in GEAR_UP_ORDER[:5]] or \
        ["Builder Hall", "New buildings", "Cannon", "Archer Tower", "Mortar"]
    colors = [T.GOLD, T.GREEN] + [NIGHT] * (len(steps) - 2)
    pills = [Pill(step, color) for step, color in zip(steps, colors)]
    h = pills[0].sizeHint().height()

    def text(t, css):
        lb = label(t)
        lb.setStyleSheet(f"color: {T.TEXT_DIM}; {css}")
        lb.setFixedHeight(h)
        lb.setAlignment(Qt.AlignVCenter)
        return lb

    for i, pill in enumerate(pills):
        if i:
            flow.addWidget(text("›", "font-size: 11pt; font-weight: 600;"))
        flow.addWidget(pill)
    flow.addWidget(text("then the rest", "font-size: 8.5pt;"))
    w.setGraphicsEffect(QGraphicsOpacityEffect(w))
    return w


class BuilderTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        content = QWidget()
        page = QVBoxLayout(content)
        page.setSpacing(16)

        note = Banner("<b>Accounts without a Builder Base are skipped automatically</b> (boat not repaired "
                      "yet): the bot notices it and goes on. It never spends gems: upgrades and research are paid "
                      "with Builder gold and Builder elixir only.", "info")
        note.icon.setPixmap(icons.pixmap("boat", T.BLUE, 18))
        page.addWidget(note)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        right = QVBoxLayout()
        right.setSpacing(16)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        page.addLayout(cols)
        page.addStretch(1)
        self._header_toggles = {}

        # --- attacks ---
        atk = Card("Attacks", "Two-stage battles, up to 6 stars each. The daily Star Bonus pays extra loot.",
                   icon="swords", color=NIGHT)
        self.after_main = Toggle()
        atk.add(SettingRow("Loot the Builder Base after the home village is full",
                           "Loot modes: each account loots its home village until full, then sails to its "
                           "Builder Base.", self.after_main))
        self.after_bonus = Toggle()
        atk.add(SettingRow("Keep attacking after the daily Star Bonus is complete",
                           "Off: stop once the Star Bonus is done (e.g. 8/8 stars).", self.after_bonus))
        self.army = Combo(BB_ARMIES)
        self.army.currentIndexChanged.connect(self.changed)
        atk.add(SettingRow("Army", "Battle Machine + this unit in every slot (the bot only rebuilds it when "
                           "it differs). Units the account has not unlocked fall back to the next best.",
                           self.army, 260))
        atk.add(divider())
        self.max_attacks = Spin(0, 100, special="No limit")
        atk.add(SettingRow("Max attacks per visit", "Then sail back and go on", self.max_attacks, 120))
        self.stuck = Spin(1, 10, suffix=" attacks")
        self.stuck.setToolTip("If the storages do not grow after this many attacks, they count as full")
        atk.add(SettingRow("Full if storages stop growing after", "Handles accounts whose storages are smaller "
                           "than their Builder Hall suggests.", self.stuck, 120))
        self.full_margin = BigSpin(maximum=5_000_000, step=10_000)
        self.full_margin.setSpecialValueText("Only when full")
        atk.add(SettingRow("Storages count as full within", "Gold and elixir: the measured storage size minus "
                           "this.", self.full_margin, 150))
        left.addWidget(atk)

        # --- roles ---
        who = Card("Builder Base for", "Accounts with these roles (Accounts page) visit their Builder Base: in the "
                   "“Builder Base only” mode, and after looting when that is switched on.", icon="users",
                   color=T.GREEN)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.roles = {}
        for i, (key, title, desc, icon, color) in enumerate(ROLES):
            chip = ChipToggle(title, color, icon=icon)
            chip.setToolTip(desc)
            self.roles[key] = chip
            grid.addWidget(chip, i // 2, i % 2)
        who.add(grid)
        left.addWidget(who)
        left.addStretch(1)

        # --- collect (on arrival) ---
        col, self.collect = self._switch_card("Collect resources", "On arrival: the Gold Mine and the Elixir "
                                              "Collector.", "pickaxe", T.GOLD)
        right.addWidget(col)

        # --- builders (before sailing back) ---
        b, self.upgrade = self._switch_card("Upgrade buildings", "Before sailing back: put free Builder Base "
                                            "builders to work on upgrades you can afford.", "hammer", T.GOLD_HI)
        self.gear_up = Toggle()
        self.gear_up_row = SettingRow("Builder Hall first, then new buildings, then Cannon / Archer Tower / Mortar",
                                      "The gear-up path. Off: the game's suggested upgrades first.", self.gear_up)
        b.add(self.gear_up_row)
        self.gear_up_path = _gear_up_path()
        b.add(self.gear_up_path)
        self.max_upgrades = Spin(1, 4)
        self.max_upgrades.setToolTip("At most this many upgrades are started on each visit")
        self.max_upgrades_row = SettingRow("Upgrades per visit", "One per free builder, up to this many",
                                           self.max_upgrades, 110)
        b.add(self.max_upgrades_row)
        b.add(divider())
        self.upgrade_skip = TagEditor("Add a building, e.g. Wall", BB_BUILDINGS,
                                      "Nothing skipped: any affordable upgrade can start.", icon="ban")
        self.upgrade_skip_block = _list_block("Never upgrade", "Part of the name is enough.", self.upgrade_skip)
        b.add(self.upgrade_skip_block)
        right.addWidget(b)

        # --- Star Laboratory (before sailing back) ---
        lab, self.research = self._switch_card("Star Laboratory research", "Before sailing back: start research "
                                               "for Builder Base troops.", "flask", T.ELIXIR_HI)
        self.research_skip = TagEditor("Add a troop, e.g. Night Witch", BB_TROOPS,
                                       "Nothing skipped: any affordable research can start.", icon="ban")
        self.research_skip_block = _list_block("Never research", "Part of the name is enough.", self.research_skip)
        lab.add(self.research_skip_block)
        right.addWidget(lab)
        right.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll(content))

        for t in (self.after_main, self.after_bonus, self.collect, self.upgrade, self.gear_up, self.research,
                  *self.roles.values()):
            t.toggled.connect(self.changed)
        for sp in (self.max_attacks, self.stuck, self.full_margin, self.max_upgrades):
            sp.valueChanged.connect(self.changed)
        self.upgrade_skip.changed.connect(self.changed)
        self.research_skip.changed.connect(self.changed)
        for t in (self.upgrade, self.gear_up, self.research):
            t.toggled.connect(self._sync)
        self._sync()

    def _switch_card(self, title, subtitle, icon, color):
        """A card whose on/off switch sits in its header; clicking the title flips it too."""
        card = Card(title, subtitle, icon=icon, color=color)
        t = Toggle()
        card.add_action(t)
        for lb in (card.title_label, card.subtitle_label):
            lb.setCursor(Qt.PointingHandCursor)
            lb.installEventFilter(self)
            self._header_toggles[lb] = t
        return card, t

    def eventFilter(self, obj, e):
        t = self._header_toggles.get(obj)
        if (t is not None and e.type() == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton
                and t.isEnabled()):
            t.toggle()
            return True
        return super().eventFilter(obj, e)

    def _sync(self, *_):
        """Options of a chore are dimmed while the chore itself is off."""
        on = self.upgrade.isChecked()
        for w in (self.gear_up_row, self.max_upgrades_row, self.upgrade_skip_block):
            w.setEnabled(on)
        self.gear_up_path.setEnabled(on)
        self.gear_up_path.graphicsEffect().setOpacity(1.0 if on and self.isEnabled() else 0.45)   # own colours
        self.gear_up_path.setVisible(self.gear_up.isChecked())
        self.research_skip_block.setEnabled(self.research.isChecked())

    # ------------------------------------------------------------------ settings io
    def load(self, settings, accounts):
        b = copy.deepcopy(DEFAULTS)
        b.update(settings.get("builder") or {})
        d = DEFAULTS
        self.after_main.setChecked(bool(b.get("after_main", d.get("after_main", False))))
        self.after_bonus.setChecked(bool(b.get("after_bonus", d.get("after_bonus", False))))
        self.army.blockSignals(True)
        self.army.select(b.get("army", d.get("army", "auto")))
        self.army.blockSignals(False)
        self.max_attacks.setValue(int(b.get("max_attacks", d.get("max_attacks", 20)) or 0))
        self.stuck.setValue(int(b.get("stuck_attacks", d.get("stuck_attacks", 3)) or 3))
        self.full_margin.setValue(int(b.get("full_margin", d.get("full_margin", 50000)) or 0))
        self.collect.setChecked(bool(b.get("collect", d.get("collect", True))))
        self.upgrade.setChecked(bool(b.get("upgrade", d.get("upgrade", False))))
        self.gear_up.setChecked(bool(b.get("gear_up", d.get("gear_up", True))))
        self.max_upgrades.setValue(int(b.get("max_upgrades", d.get("max_upgrades", 1)) or 1))
        self.research.setChecked(bool(b.get("research", d.get("research", False))))
        self.upgrade_skip.set_values(b.get("upgrade_skip") or [])
        self.research_skip.set_values(b.get("research_skip") or [])
        roles = b.get("on_roles")
        roles = d.get("on_roles", [r[0] for r in ROLES]) if roles is None else roles
        for k, t in self.roles.items():
            t.setChecked(k in roles)
        self._sync()

    def apply(self, settings, accounts):
        b = settings.setdefault("builder", {})        # keys this page does not show (e.g. zoom_out) are kept
        b["after_main"] = self.after_main.isChecked()
        b["after_bonus"] = self.after_bonus.isChecked()
        b["army"] = self.army.currentData() or "auto"
        b["max_attacks"] = self.max_attacks.value()
        b["stuck_attacks"] = self.stuck.value()
        b["full_margin"] = self.full_margin.value()
        b["collect"] = self.collect.isChecked()
        b["upgrade"] = self.upgrade.isChecked()
        b["gear_up"] = self.gear_up.isChecked()
        b["max_upgrades"] = self.max_upgrades.value()
        b["research"] = self.research.isChecked()
        b["upgrade_skip"] = self.upgrade_skip.values()
        b["research_skip"] = self.research_skip.values()
        b["on_roles"] = [k for k, t in self.roles.items() if t.isChecked()]

    def set_running(self, running):
        self.setEnabled(not running)
        self._sync()

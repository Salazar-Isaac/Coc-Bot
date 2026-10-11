"""Village page: chores done on each account visit: collect resources, builder upgrades, laboratory research."""

import copy

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from bot.actions import troops
from gui import icons
from gui import theme as T
from gui.components import (Banner, Card, ChipToggle, ResourceIcon, SettingRow, TagEditor, Toggle, divider,
                            scroll)
from gui.widgets import BigSpin, Spin

NAMES = T.RESOURCE_NAME

DEFAULTS = {
    "collect": True,
    "upgrade_buildings": False,
    "max_upgrades": 2,
    "include_other": True,
    "upgrade_skip": ["Wall", "Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion", "Minion Prince",
                     "Dragon Duke"],
    "research": False,
    "research_skip": [],
    "reserve": {"gold": 0, "elixir": 0, "dark": 0},
    "on_roles": ["main", "loot", "both", "feeder"],
}

# key, title, description, icon, colour (same look as the roles on the Accounts page)
ROLES = [("main", "Main", "Loots and donates to the others", "crown", T.GOLD),
         ("loot", "Loot only", "Just loots, never requests troops", "swords", T.ELIXIR_HI),
         ("both", "Loot + request", "Loots and also requests troops", "sparkles", "#4fd1c5"),
         ("feeder", "Feeder", "Only requests troops", "send", "#5cc8ff")]

# suggestions for the "Never upgrade" box (part of a name is enough, these just save typing)
BUILDINGS = ["Wall", "Barbarian King", "Archer Queen", "Minion Prince", "Grand Warden", "Royal Champion",
             "Dragon Duke", "Town Hall", "Clan Castle", "Laboratory", "Army Camp", "Barracks", "Dark Barracks",
             "Spell Factory", "Dark Spell Factory", "Workshop", "Pet House", "Blacksmith", "Hero Hall",
             "Builder's Hut", "Cannon", "Archer Tower", "Mortar", "Air Defense", "Wizard Tower", "Air Sweeper",
             "Hidden Tesla", "Bomb Tower", "X-Bow", "Inferno Tower", "Eagle Artillery", "Scattershot",
             "Spell Tower", "Monolith", "Multi-Archer Tower", "Ricochet Cannon", "Multi-Gear Tower", "Firespitter",
             "Gold Mine", "Elixir Collector", "Dark Elixir Drill", "Gold Storage", "Elixir Storage",
             "Dark Elixir Storage", "Bomb", "Spring Trap", "Giant Bomb", "Air Bomb", "Seeking Air Mine",
             "Skeleton Trap", "Tornado Trap"]


def _research_names():
    names = {n for n in troops.SPACE if n != "heal"} | set(troops.SIEGES)
    return sorted((n.title() + (" Spell" if n in troops.SPELLS else "") for n in names), key=str.lower)


def _list_block(title, description, editor):
    """A title + description with a tag editor under it (fills the card's width)."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.addWidget(SettingRow(title, description))
    lay.addWidget(editor)
    return w


class VillageTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        content = QWidget()
        page = QVBoxLayout(content)
        page.setSpacing(16)

        safety = Banner("<b>Safe with gems and magic items.</b> The bot never taps anything that costs gems or "
                        "magic items (Boost, Finish Now, Hammer or Book confirms) and closes any “buy with gems” "
                        "offer. Upgrades and research are paid with gold, elixir or dark elixir only.", "success")
        safety.icon.setPixmap(icons.pixmap("shield", T.GREEN, 18))
        page.addWidget(safety)

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

        # --- collect (on arrival) ---
        col, self.collect = self._switch_card("Collect resources", "When the bot arrives on an account: gold "
                                              "mines, elixir collectors, dark elixir drills and the loot cart.",
                                              "pickaxe", T.GOLD)
        left.addWidget(col)

        # --- reserve ---
        res = Card("Always keep at least", "Upgrades and research never spend below these, e.g. to keep elixir "
                   "for donating.", icon="shield", color="#5cc8ff")
        self.reserve = {}
        for r in T.RESOURCES:
            sp = BigSpin(maximum=100_000_000, step=100_000 if r != "dark" else 1_000)
            sp.setSpecialValueText("No reserve")
            sp.setFixedWidth(170)
            self.reserve[r] = sp
            row = SettingRow(NAMES[r], control=sp)
            row.layout().insertWidget(0, ResourceIcon(r, 22), 0, Qt.AlignVCenter)
            res.add(row)
        left.addWidget(res)

        # --- roles ---
        who = Card("Do chores on", "Accounts with these roles (Accounts page) get the chores.", icon="users",
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

        # --- builders (before leaving) ---
        b, self.upgrade = self._switch_card("Upgrade buildings", "Before the bot leaves an account: put free "
                                            "builders to work on upgrades you can afford.", "hammer", T.GOLD_HI)
        self.max_upgrades = Spin(1, 6)
        self.max_upgrades.setToolTip("At most this many upgrades are started on each visit")
        self.max_upgrades_row = SettingRow("Upgrades per visit", "One per free builder, up to this many",
                                           self.max_upgrades, 110)
        b.add(self.max_upgrades_row)
        self.include_other = Toggle()
        self.include_other_row = SettingRow("Also use “Other upgrades”", "Not only the game's suggested upgrades",
                                            self.include_other)
        b.add(self.include_other_row)
        b.add(divider())
        self.upgrade_skip = TagEditor("Add a building, e.g. Wall", BUILDINGS,
                                      "Nothing skipped: any affordable upgrade can start.",
                                      defaults=DEFAULTS["upgrade_skip"], icon="ban")
        self.upgrade_skip_block = _list_block(
            "Never upgrade", "Part of the name is enough. Heroes are skipped by default so they stay usable for "
            "attacks.", self.upgrade_skip)
        b.add(self.upgrade_skip_block)
        right.addWidget(b)

        # --- laboratory (before leaving) ---
        lab, self.research = self._switch_card("Start research", "Before the bot leaves an account: laboratory "
                                               "research for troops, spells and siege machines.", "flask",
                                               T.ELIXIR_HI)
        self.research_skip = TagEditor("Add a troop, spell or siege", _research_names(),
                                       "Nothing skipped: any affordable research can start.", icon="ban")
        self.research_skip_block = _list_block("Never research", "Part of the name is enough.", self.research_skip)
        lab.add(self.research_skip_block)
        right.addWidget(lab)
        right.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll(content))

        for t in (self.collect, self.upgrade, self.include_other, self.research, *self.roles.values()):
            t.toggled.connect(self.changed)
        for sp in (self.max_upgrades, *self.reserve.values()):
            sp.valueChanged.connect(self.changed)
        self.upgrade_skip.changed.connect(self.changed)
        self.research_skip.changed.connect(self.changed)
        self.upgrade.toggled.connect(self._sync)
        self.research.toggled.connect(self._sync)
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
        for w in (self.max_upgrades_row, self.include_other_row, self.upgrade_skip_block):
            w.setEnabled(on)
        self.research_skip_block.setEnabled(self.research.isChecked())

    # ------------------------------------------------------------------ settings io
    def load(self, settings, accounts):
        v = copy.deepcopy(DEFAULTS)
        v.update(settings.get("village") or {})
        self.collect.setChecked(bool(v.get("collect", True)))
        self.upgrade.setChecked(bool(v.get("upgrade_buildings", False)))
        self.max_upgrades.setValue(int(v.get("max_upgrades", 2) or 2))
        self.include_other.setChecked(bool(v.get("include_other", True)))
        self.upgrade_skip.set_values(v.get("upgrade_skip") or [])
        self.research.setChecked(bool(v.get("research", False)))
        self.research_skip.set_values(v.get("research_skip") or [])
        reserve = v.get("reserve") or {}
        for r, sp in self.reserve.items():
            sp.setValue(int(reserve.get(r, 0) or 0))
        roles = v.get("on_roles")
        roles = DEFAULTS["on_roles"] if roles is None else roles
        for k, t in self.roles.items():
            t.setChecked(k in roles)
        self._sync()

    def apply(self, settings, accounts):
        v = settings.setdefault("village", {})
        v["collect"] = self.collect.isChecked()
        v["upgrade_buildings"] = self.upgrade.isChecked()
        v["max_upgrades"] = self.max_upgrades.value()
        v["include_other"] = self.include_other.isChecked()
        v["upgrade_skip"] = self.upgrade_skip.values()
        v["research"] = self.research.isChecked()
        v["research_skip"] = self.research_skip.values()
        v["reserve"] = {r: sp.value() for r, sp in self.reserve.items()}
        v["on_roles"] = [k for k, t in self.roles.items() if t.isChecked()]

    def set_running(self, running):
        self.setEnabled(not running)

"""Upgrades page: the "Loot + Upgrade" and "Builder Base upgrades" plans for your other accounts
(ticked "Upgrade" on the Accounts page)."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from bot.actions.upgrades import BB_DEFAULT, PLAN
from gui import icons
from gui import theme as T
from gui.components import Banner, Card, SettingRow, TagEditor, Toggle, hbox, label, scroll
from gui.widgets import Spin

# key, title, description, icon, colour (same look as the roles on the Accounts page)
ROLES = [("main", "Main", "Loots and donates to the others", "crown", T.GOLD),
         ("loot", "Looter", "Loots in every mode and requests troops", "swords", T.ELIXIR_HI),
         ("both", "Loot + request", "Loots and also requests troops", "sparkles", "#4fd1c5"),
         ("feeder", "Feeder", "Only requests troops", "send", "#5cc8ff")]

# suggestions for "Also upgrade" (part of a name is enough, these just save typing)
BUILDINGS = ["Air Defense", "Air Sweeper", "Bomb Tower", "Builder's Hut", "Clan Castle", "Eagle Artillery",
             "Elixir Collector", "Dark Elixir Drill", "Firespitter", "Gold Mine", "Hidden Tesla", "Inferno Tower",
             "Monolith", "Mortar", "Multi-Archer Tower", "Multi-Gear Tower", "Ricochet Cannon", "Scattershot",
             "Spell Tower", "Wizard Tower", "Workshop", "X-Bow", "Wall", "Barbarian King", "Archer Queen",
             "Grand Warden", "Royal Champion", "Minion Prince", "Dragon Duke"]
BB_BUILDINGS = ["Cannon", "Double Cannon", "Archer Tower", "Mortar", "Multi Mortar", "Hidden Tesla", "Firecrackers",
                "Crusher", "Guard Post", "Air Bombs", "Roaster", "Giant Cannon", "Mega Tesla", "Lava Launcher",
                "X-Bow", "Builder Barracks", "Army Camp", "Gold Mine", "Elixir Collector", "Gold Storage",
                "Elixir Storage", "Clock Tower", "Star Laboratory", "Healing Hut", "Reinforcement Camp",
                "O.T.T.O's Outpost", "Wall"]


def _block(title, description, editor):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.addWidget(SettingRow(title, description))
    lay.addWidget(editor)
    return w


class UpgradesTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accounts = []
        content = QWidget()
        page = QVBoxLayout(content)
        page.setSpacing(16)

        safety = Banner("<b>Never with gems.</b> Only upgrades priced in gold, elixir or dark elixir that the "
                        "account can afford, confirmed with the Confirm button that shows a resource price. Prices "
                        "are read from the game every time, so price changes and sales are handled.", "success")
        safety.icon.setPixmap(icons.pixmap("shield", T.GREEN, 18))
        page.addWidget(safety)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(16)
        right.setSpacing(16)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        page.addLayout(cols)

        # --- which accounts ---
        card = Card("Loot + Upgrade", "The mode “Loot + Upgrade” loots these accounts one after another. Those ticked "
                    "“Upgrade” on the Accounts page (all but the Main and Omi ji) start upgrades before looting, if "
                    "they have the resources, and again after looting.", icon="hammer", color=T.GOLD_HI)
        self.enabled = Toggle()
        card.add_action(self.enabled)
        self.first = Spin(1, 200)
        self.last = Spin(1, 200)
        for sp in (self.first, self.last):
            sp.setFixedWidth(90)
        self.range_names = label("", "small", wrap=True)
        self.range_names.setStyleSheet(f"color: {T.TEXT_MUTED};")
        rng = QWidget()
        rng.setLayout(hbox(label("from #"), self.first, label("to #"), self.last, spacing=8))
        card.add(SettingRow("Accounts", "Positions on the Accounts page (default 1 to 15)", rng))
        card.add(self.range_names)
        self.max_per_visit = Spin(1, 6)
        self.max_per_visit.setFixedWidth(90)
        card.add(SettingRow("Upgrades per visit", "One per free builder, up to this many", self.max_per_visit))
        left.addWidget(card)

        # --- main village order ---
        order = Card("Main village order", "The first step with an affordable upgrade is used, so a builder never "
                     "waits for an expensive item. Anything not listed is never upgraded.", icon="list",
                     color="#5cc8ff")
        for i, (_, names) in enumerate(PLAN, 1):
            lb = label(f"<b>{i}.</b>&nbsp;&nbsp;{', '.join(names)}")
            lb.setTextFormat(Qt.RichText)
            lb.setWordWrap(True)
            order.add(lb)
        self.extra = TagEditor("Add a building, e.g. Wizard Tower", BUILDINGS,
                               "Nothing added: only the steps above.", icon="plus")
        order.add(_block(f"{len(PLAN) + 1}.  Also upgrade (your list, in this order)",
                         "Part of a name is enough (“Wizard” = Wizard Tower).", self.extra))
        th = label(f"<b>{len(PLAN) + 2}.</b>&nbsp;&nbsp;Town Hall, when nothing above can be upgraded any more at "
                   "this Town Hall level. From Town Hall 16 on, its weapon gets all 5 stars first.")
        th.setTextFormat(Qt.RichText)
        th.setWordWrap(True)
        order.add(th)
        left.addWidget(order)
        left.addStretch(1)

        # --- Builder Base ---
        bb = Card("Builder Base (gear up)", "The mode “Builder Base upgrades” sails to each of these accounts' "
                  "Builder Base and puts its builders to work in this order:", icon="boat", color="#8c9bff")
        for i, text in enumerate(["New buildings the Builder Hall unlocked are built first.",
                                  "Then the buildings on your list, in its order:"], 1):
            lb = label(f"<b>{i}.</b>&nbsp;&nbsp;{text}")
            lb.setTextFormat(Qt.RichText)
            lb.setWordWrap(True)
            bb.add(lb)
        self.bb_plan = TagEditor("Add a Builder Base building", BB_BUILDINGS, "Nothing listed: only new buildings "
                                 "and the Builder Hall.", defaults=BB_DEFAULT, icon="hammer")
        bb.add(self.bb_plan)
        lb = label("<b>3.</b>&nbsp;&nbsp;The Builder Hall, when none of those can be upgraded any more - that unlocks "
                   "new buildings and levels, and it all starts again.")
        lb.setTextFormat(Qt.RichText)
        lb.setWordWrap(True)
        bb.add(lb)
        right.addWidget(bb)
        right.addStretch(1)
        page.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll(content))
        self.enabled.toggled.connect(self.changed)
        for sp in (self.first, self.last, self.max_per_visit):
            sp.valueChanged.connect(self.changed)
        self.first.valueChanged.connect(self._names)
        self.last.valueChanged.connect(self._names)
        self.extra.changed.connect(self.changed)
        self.bb_plan.changed.connect(self.changed)
        for lb in (card.title_label, card.subtitle_label):
            lb.setCursor(Qt.PointingHandCursor)
            lb.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton and self.enabled.isEnabled():
            self.enabled.toggle()
            return True
        return super().eventFilter(obj, e)

    def _names(self, *_):
        a, b = self.first.value(), self.last.value()
        accs = self._accounts[a - 1:b] if a <= b else []
        if not accs:
            self.range_names.setText("No accounts in this range.")
            return
        up = [x["name"] for x in accs if x.get("upgrade")]
        self.range_names.setText(f"{accs[0]['name']} … {accs[-1]['name']} ({len(accs)} accounts, "
                                 f"{len(up)} upgrade: {', '.join(up) if up else 'none'})")

    # ------------------------------------------------------------------ settings io
    def load(self, settings, accounts):
        self._accounts = accounts
        u = settings.get("upgrades") or {}
        self.enabled.setChecked(bool(u.get("enabled", True)))
        self.max_per_visit.setValue(int(u.get("max_per_visit", 5) or 5))
        self.first.setValue(int(u.get("from", 1)))
        self.last.setValue(int(u.get("to", 15)))
        self.extra.set_values(u.get("extra") or [])
        self.bb_plan.set_values(u.get("bb_plan", BB_DEFAULT))
        self._names()

    def apply(self, settings, accounts):
        u = settings.setdefault("upgrades", {})
        u["enabled"] = self.enabled.isChecked()
        u["max_per_visit"] = self.max_per_visit.value()
        u["from"], u["to"] = self.first.value(), max(self.first.value(), self.last.value())
        u["extra"] = self.extra.values()
        u["bb_plan"] = self.bb_plan.values()

    def set_running(self, running):
        self.setEnabled(not running)

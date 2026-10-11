"""Upgrades page: the upgrade plan for your other accounts (ticked "Upgrade" on the Accounts page)."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from bot.actions.upgrades import PLAN
from gui import icons
from gui import theme as T
from gui.components import Banner, Card, SettingRow, Toggle, label, scroll
from gui.widgets import Spin

# key, title, description, icon, colour (same look as the roles on the Accounts page)
ROLES = [("main", "Main", "Loots and donates to the others", "crown", T.GOLD),
         ("loot", "Looter", "Loots in every mode and requests troops", "swords", T.ELIXIR_HI),
         ("both", "Loot + request", "Loots and also requests troops", "sparkles", "#4fd1c5"),
         ("feeder", "Feeder", "Only requests troops", "send", "#5cc8ff")]


class UpgradesTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        content = QWidget()
        page = QVBoxLayout(content)
        page.setSpacing(16)

        safety = Banner("<b>Never with gems.</b> Only upgrades priced in gold, elixir or dark elixir that the "
                        "account can afford, confirmed with the Confirm button that shows a resource price. "
                        "Boost, Finish Now and magic items are never touched.", "success")
        safety.icon.setPixmap(icons.pixmap("shield", T.GREEN, 18))
        page.addWidget(safety)

        card = Card("Upgrade plan", "On the accounts ticked “Upgrade” on the Accounts page (your other accounts, "
                    "not the Main or the Omi account): when the bot loots them it first puts free builders to "
                    "work if there are resources, loots, and after looting starts upgrades again.",
                    icon="hammer", color=T.GOLD_HI)
        self.enabled = Toggle()
        card.add_action(self.enabled)
        self.max_per_visit = Spin(1, 6)
        self.max_per_visit.setFixedWidth(110)
        card.add(SettingRow("Upgrades per visit", "One per free builder, up to this many", self.max_per_visit))
        page.addWidget(card)

        order = Card("Order", "The first step with an affordable upgrade is used, so a builder never waits for "
                     "an expensive item. Walls, heroes, traps and other buildings are never upgraded.",
                     icon="list", color="#5cc8ff")
        steps = [", ".join(names) for _, names in PLAN]
        steps.append("Town Hall, when nothing above can be upgraded any more at this Town Hall level. "
                     "From Town Hall 16 on, its weapon gets all 5 stars first.")
        for i, text in enumerate(steps, 1):
            lb = label(f"<b>{i}.</b>&nbsp;&nbsp;{text}")
            lb.setWordWrap(True)
            lb.setTextFormat(Qt.RichText)
            order.add(lb)
        page.addWidget(order)
        page.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll(content))
        self.enabled.toggled.connect(self.changed)
        self.enabled.toggled.connect(self.max_per_visit.setEnabled)
        self.max_per_visit.valueChanged.connect(self.changed)
        for lb in (card.title_label, card.subtitle_label):
            lb.setCursor(Qt.PointingHandCursor)
            lb.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton and self.enabled.isEnabled():
            self.enabled.toggle()
            return True
        return super().eventFilter(obj, e)

    # ------------------------------------------------------------------ settings io
    def load(self, settings, accounts):
        u = settings.get("upgrades") or {}
        self.enabled.setChecked(bool(u.get("enabled", True)))
        self.max_per_visit.setValue(int(u.get("max_per_visit", 5) or 5))
        self.max_per_visit.setEnabled(self.enabled.isChecked())

    def apply(self, settings, accounts):
        u = settings.setdefault("upgrades", {})
        u["enabled"] = self.enabled.isChecked()
        u["max_per_visit"] = self.max_per_visit.value()

    def set_running(self, running):
        self.setEnabled(not running)

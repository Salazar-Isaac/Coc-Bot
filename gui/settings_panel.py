"""Right column: every setting in one scroll area, in sections.

One section per function in the flow (once, in flow order), "Base choice per Town Hall" right after the first
attack section, then General, Accounts and Device & hotkeys. A function that is not in the flow is shown only
while it is picked in the palette (with "Add to flow"). show_step() scrolls to a section and flashes it."""

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from bot.flow import BY_KEY, STEPS
from gui import theme as T
from gui.accounts_tab import AccountsTab
from gui.components import Button, IconTile, Pill, label, scroll
from gui.device_tab import DeviceTab
from gui.donate_tab import DonateTab
from gui.step_settings import BODIES, STEP_COLORS

ATTACKS = ("attack_all", "loot_current")
# key: title, subtitle, icon, colour (sections that are not functions)
EXTRA = {
    "base_choice": ("Base choice per Town Hall", "Which bases the attacks take: the minimum loot a base must have.",
                    "target", T.GOLD),
    "general": ("General", "What happens when an account is full, when the run ends and how often the flow runs.",
                "sliders", T.BLUE),
    "accounts": ("Accounts", "Your Supercell ID accounts in switching order. # is the position the accounts "
                 "fields use.", "users", T.GREEN),
    "device": ("Device & hotkeys", "Where the game runs, screen profile, hotkeys and behaviour.", "monitor",
               "#5cc8ff"),
}
ALWAYS = ("general", "accounts", "device")


class Section(QFrame):
    """Header (icon, title, subtitle, step numbers / Add to flow / fold) + a body. Flashes gold when shown."""

    add_clicked = Signal(str)

    def __init__(self, key, title, subtitle, icon, color, body, foldable=False, parent=None):
        super().__init__(parent)
        self.key = key
        self.body = body
        self.peek = False
        self.folded = False
        self.foldable = foldable
        self._flash = QVariantAnimation(self)
        self._flash.setDuration(1900)
        self._flash.setStartValue(0.0)
        self._flash.setKeyValueAt(0.08, 1.0)
        self._flash.setKeyValueAt(0.55, 1.0)
        self._flash.setEndValue(0.0)
        self._flash.setEasingCurve(QEasingCurve.InOutQuad)
        self._flash.valueChanged.connect(lambda _v: self.update())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 14)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.tile = IconTile(icon, color, 36)
        head.addWidget(self.tile, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = label(title)
        self.title.setFont(T.font(12.5, QFont.DemiBold, display=True))
        self.subtitle = label(subtitle, "rowDesc", wrap=True)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        head.addLayout(col, 1)
        self.pills = QHBoxLayout()
        self.pills.setSpacing(6)
        head.addLayout(self.pills)
        self.summary = label("", "small")
        self.summary.hide()
        head.addWidget(self.summary, 0, Qt.AlignVCenter)
        self.not_in_flow = Pill("Not in the flow", T.TEXT_MUTED)
        self.not_in_flow.hide()
        head.addWidget(self.not_in_flow, 0, Qt.AlignVCenter)
        self.add_btn = Button("Add to flow", "plus", "primary", "sm")
        self.add_btn.hide()
        self.add_btn.clicked.connect(lambda: self.add_clicked.emit(self.key))
        head.addWidget(self.add_btn, 0, Qt.AlignVCenter)
        self.fold_btn = None
        if foldable:
            self.fold_btn = Button("Hide", "chevron-up", "ghost", "sm")
            self.fold_btn.clicked.connect(lambda: self.set_folded(not self.folded))
            head.addWidget(self.fold_btn, 0, Qt.AlignVCenter)
            for w in (self.title, self.subtitle, self.tile):
                w.setCursor(Qt.PointingHandCursor)
                w.installEventFilter(self)
        lay.addLayout(head)
        lay.addWidget(body)
        self._pill_widgets = []

    def set_steps(self, numbers):
        for w in self._pill_widgets:
            self.pills.removeWidget(w)
            w.deleteLater()
        self._pill_widgets = []
        if numbers:
            text = ("Step " if len(numbers) == 1 else "Steps ") + " · ".join(str(n) for n in numbers)
            p = Pill(text, T.GOLD)
            p.setToolTip("Its place in the flow")
            self.pills.addWidget(p, 0, Qt.AlignVCenter)
            self._pill_widgets.append(p)

    def set_peek(self, on):
        self.peek = on
        self.add_btn.setVisible(on)
        self.not_in_flow.setVisible(on)
        self.update()

    def set_add_enabled(self, on):
        self.add_btn.setEnabled(on)

    def set_folded(self, folded):
        if not self.foldable:
            return
        self.folded = bool(folded)
        self.body.setVisible(not self.folded)
        self.summary.setVisible(self.folded and bool(self.summary.text()))
        self.fold_btn.set_text("Show" if self.folded else "Hide")
        self.fold_btn.set_icon("chevron-down" if self.folded else "chevron-up")

    def set_summary(self, text):
        self.summary.setText(text)
        self.summary.setVisible(self.folded and bool(text))

    def flash(self):
        self._flash.stop()
        self._flash.start()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton and self.foldable:
            self.set_folded(not self.folded)
            return True
        return super().eventFilter(obj, e)

    def paintEvent(self, _):
        a = float(self._flash.currentValue() or 0.0) if self._flash.state() == QVariantAnimation.Running else 0.0
        if a <= 0.01 and not self.peek:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.peek:
            p.setPen(QPen(T.qc(T.TEXT_DIM, 0.7), 1.2, Qt.DashLine))
            p.setBrush(T.qc(T.SURFACE, 0.35))
            p.drawRoundedRect(r, 18, 18)
        if a > 0.01:
            p.setPen(QPen(T.qc(T.GOLD, 0.85 * a), 1.6))
            p.setBrush(T.qc(T.GOLD, 0.055 * a))
            p.drawRoundedRect(r, 18, 18)


class SettingsPanel(QWidget):
    """All settings in one scroll area. pages = the parts with load / apply / changed / set_running."""

    changed = Signal()

    accounts_rows_changed = Signal(list)          # the Accounts table changed (not saved yet)
    add_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flow = []
        self._peek = None
        self._order = []
        self._accounts = []
        self.bodies = {k: cls() for k, cls in BODIES.items()}
        self.donate = DonateTab()
        self.accounts = AccountsTab()
        self.device = DeviceTab()
        self.bodies.update({"donate": self.donate, "accounts": self.accounts, "device": self.device})
        self.attack = self.bodies["attack_all"]
        self.base_choice = self.bodies["base_choice"]
        self.general = self.bodies["general"]

        self.sections = {}
        for step in STEPS:
            self.sections[step.key] = Section(step.key, step.title, step.description, step.icon,
                                              STEP_COLORS.get(step.key, T.GOLD), self.bodies[step.key])
        for key, (title, sub, icon, color) in EXTRA.items():
            self.sections[key] = Section(key, title, sub, icon, color, self.bodies[key],
                                         foldable=key in ("accounts", "device"))
        self.sections["accounts"].set_folded(True)
        self.sections["device"].set_folded(True)

        content = QWidget()
        self.lay = QVBoxLayout(content)
        self.lay.setSpacing(6)
        for s in self.sections.values():
            s.hide()
            self.lay.addWidget(s)
            s.add_clicked.connect(self.add_requested)
        self.lay.addStretch(1)
        self.area = scroll(content, margins=(0, 0, 8, 24))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.area)
        self._scroll_anim = QPropertyAnimation(self.area.verticalScrollBar(), b"value", self)
        self._scroll_anim.setDuration(420)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)

        self.pages = list(self.bodies.values())
        for b in self.pages:
            b.changed.connect(self.changed)
        self.attack.watch_changed.connect(lambda: self.base_choice.set_watched(self.attack.watched()))
        self.accounts.changed.connect(self._accounts_changed)
        self.set_flow([])

    # --- settings io (the window calls these for every part in .pages)
    def load(self, settings, accounts):
        for b in self.pages:
            b.load(settings, accounts)
        self.base_choice.set_watched(self.attack.watched())
        self._accounts_changed()

    def apply(self, settings, accounts):
        for b in self.pages:
            b.apply(settings, accounts)

    def set_running(self, running):
        for b in self.pages:
            b.set_running(running)
        for s in self.sections.values():
            s.set_add_enabled(not running)

    # --- what is shown
    def set_flow(self, keys):
        self._flow = [k for k in keys if k in BY_KEY]
        if self._peek in self._flow:
            self._peek = None
        self._relayout()

    def show_step(self, key):
        """Show the settings of a function (also one that is not in the flow) and scroll to them."""
        if key not in self.sections:
            return
        self._peek = key if key in BY_KEY and key not in self._flow else None
        self._relayout()
        self.scroll_to(key)

    def show_section(self, key):
        """Scroll to a section that is always there (unfolding it)."""
        s = self.sections.get(key)
        if s is None:
            return
        s.set_folded(False)
        self.scroll_to(key)

    def clear_peek(self):
        if self._peek is not None:
            self._peek = None
            self._relayout()

    def peek_key(self):
        return self._peek

    def _wanted(self):
        order, seen = [], set()
        for k in self._flow:
            if k not in seen:
                seen.add(k)
                order.append(k)
        if self._peek and self._peek not in seen:
            order.append(self._peek)
        first_attack = next((i for i, k in enumerate(order) if k in ATTACKS), None)
        if first_attack is not None:
            order.insert(first_attack + 1, "base_choice")
        return order + list(ALWAYS)

    def _relayout(self):
        order = self._wanted()
        positions = {}
        for i, k in enumerate(self._flow):
            positions.setdefault(k, []).append(i + 1)
        for k, s in self.sections.items():
            if k in BY_KEY:
                s.set_steps(positions.get(k, []))
                s.set_peek(k == self._peek)
        if order != self._order:
            self._order = order
            content = self.area.widget()
            content.setUpdatesEnabled(False)
            for s in self.sections.values():
                self.lay.removeWidget(s)
            for i, k in enumerate(order):
                self.lay.insertWidget(i, self.sections[k])
            shown = set(order)
            hidden = [s for k, s in self.sections.items() if k not in shown]
            for s in hidden:
                self.lay.insertWidget(self.lay.count() - 1, s)
                s.hide()
            for k in order:
                self.sections[k].show()
            content.setUpdatesEnabled(True)

    def scroll_to(self, key, flash=True):
        s = self.sections.get(key)
        if s is None:
            return

        def go():
            self.area.widget().layout().activate()
            sb = self.area.verticalScrollBar()
            target = max(sb.minimum(), min(sb.maximum(), s.y() - 4))
            self._scroll_anim.stop()
            if abs(sb.value() - target) < 2:
                sb.setValue(target)
            else:
                self._scroll_anim.setStartValue(sb.value())
                self._scroll_anim.setEndValue(target)
                self._scroll_anim.start()
            if flash:
                s.flash()
        QTimer.singleShot(0, go)

    # --- live data
    def _accounts_changed(self, *_):
        rows = self.accounts.rows()
        self._accounts = rows
        for k, b in self.bodies.items():
            if hasattr(b, "set_accounts") and k not in ("accounts", "device", "donate"):
                b.set_accounts(rows)
        self.sections["accounts"].set_summary(self.accounts.summary())
        self.accounts_rows_changed.emit(rows)

    def details(self):
        """Short text per function for its rows in the flow (accounts it works on, ...)."""
        out = {}
        for step in STEPS:
            b = self.bodies[step.key]
            out[step.key] = b.detail() if hasattr(b, "detail") else ("once" if not step.per_account else "")
        return out

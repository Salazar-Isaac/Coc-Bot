"""Donate page: settings for the Loot + Donate and Donate only modes, and what the Main account donates."""

import re

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLineEdit, QTableWidgetItem, QVBoxLayout, QWidget

from bot.actions import troops
from bot.core import vision
from bot.modes import MODES, load_all
from gui import theme as T
from gui.components import (ROLE, Banner, Button, Card, ChoiceDelegate, IconButton, NumberDelegate, PillDelegate,
                            PlaceholderDelegate, Segmented, SettingRow, Table, Toggle, ToggleDelegate, divider, field,
                            hbox, scroll)
from gui.widgets import BigSpin, Spin

COLS = ["On", "Name", "Type", "Space", "Max per request", "Keywords", "Template", "Icon"]
ON, NAME, TYPE, SPACE, MAX, KEYS, TPL, ICON = range(len(COLS))
TIPS = {TYPE: "Which part of a request it fills: troops, spells or siege machines",
        SPACE: "Housing space of one unit (filled in from the name; change it if needed)",
        MAX: "At most this many units of this item go into one request",
        KEYS: "Extra words that ask for this item in a request message, comma separated (its name always counts)",
        TPL: "Template key of its icon in the donate window, e.g. donate/balloon",
        ICON: "Whether that icon has been captured on the Templates page"}
# key, label, icon, colour, tooltip
CATEGORIES = [("troop", "Troop", "swords", T.GOLD, "Uses the request's troop space"),
              ("spell", "Spell", "flask", T.ELIXIR_HI, "Uses the request's spell space"),
              ("siege", "Siege", "castle", "#5cc8ff", "Uses the request's siege machine slot")]
OLD = Qt.UserRole + 1           # the Name cell remembers the previous name
EDITABLE = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable
FIXED = Qt.ItemIsEnabled | Qt.ItemIsSelectable


def template_key(name):
    slug = re.sub(r"[^a-z0-9_]+", "_", (name or "").strip().lower()).strip("_")
    return f"donate/{slug}" if slug else ""


def _cell(value, flags):
    it = QTableWidgetItem("")
    it.setData(ROLE, value)
    it.setFlags(flags)
    return it


def normalize_key(key):
    key = (key or "").strip().replace("\\", "/")
    if key and "/" not in key:
        key = "donate/" + key
    return key


def builtin_keywords(name):
    """Words the bot already understands for this item (besides its name), e.g. "loon" for Balloon."""
    return troops.ALIASES.get(troops.norm(name).replace(" spell", ""), [])


class DonateTab(QWidget):
    changed = Signal()
    templates_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        load_all()
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(16)
        self.notice = Banner("<b>A donation mode is not ready yet.</b> Everything here is saved now and used as "
                             "soon as it is.", "warning")
        lay.addWidget(self.notice)

        row = QHBoxLayout()
        row.setSpacing(16)
        cycle = Card("Donation cycle", "Loot + Donate and Donate only.", icon="refresh", color=T.ELIXIR_HI)
        self.loot_first = Toggle()
        cycle.add(SettingRow("Loot before donating", "In the Loot + Donate cycle the Main and Loot-only accounts "
                             "loot until full first", self.loot_first))
        cycle.add(divider())
        self.min_keep = BigSpin(maximum=100_000_000, step=500_000)
        self.min_keep.setFixedWidth(170)
        cycle.add(SettingRow("Main keeps at least", "Donates only while its elixir is above this", self.min_keep))
        self.rounds = Spin(0, 999, special="Until elixir low")
        self.rounds.setFixedWidth(170)
        cycle.add(SettingRow("Request / donate rounds", "0 = until the Main's elixir runs low", self.rounds))
        cycle.layout().addStretch(1)
        row.addWidget(cycle, 1)

        req = Card("Clan Castle requests", "Who requests and who gets troops.", icon="send", color="#5cc8ff")
        self.remove_cc = Toggle()
        req.add(SettingRow("Empty the Clan Castle first", "Feeders remove their Clan Castle troops before requesting",
                           self.remove_cc))
        req.add(divider())
        self.request_text = QLineEdit()
        self.request_text.setPlaceholderText("(optional) text sent with the request")
        self.request_text.setMaxLength(120)
        req.add(field("Request message", self.request_text))
        req.add(divider())
        self.donate_to = Segmented([("all", "Everyone"), ("mine", "Only my accounts")])
        self.donate_to.setToolTip("“Only my accounts”: the Main skips requests from players whose name is not on "
                                  "the Accounts page")
        req.add(field("Donate to", self.donate_to, "Only my accounts = requests from the names on your Accounts "
                      "page; other clan mates are skipped."))
        req.layout().addStretch(1)
        row.addWidget(req, 1)
        lay.addLayout(row)

        items = Card("What the Main account donates",
                     "For each request the bot reads its free space (troops / spells / siege) and its message. "
                     "Items whose name or keywords appear in the message are donated first, then the rest in this "
                     "priority order. It never donates more than fits.", icon="gift", color=T.GOLD)
        self.add_btn = Button("Add item", "plus", "secondary", "sm")
        self.remove_btn = Button("Remove", "trash", "secondary", "sm")
        up = IconButton("arrow-up", "Move up (higher priority)", variant="secondary")
        down = IconButton("arrow-down", "Move down", variant="secondary")
        to_templates = Button("Capture icons in Templates", "scan", "outline", "sm")
        items.add(hbox(self.add_btn, self.remove_btn, up, down, None, to_templates, spacing=8))
        t = self.table = Table(COLS, row_height=46)
        t.empty_text = "Nothing to donate yet.\nAdd the troops, spells and siege machines your Main gives."
        t.empty_icon = "gift"
        for c, tip in TIPS.items():
            t.horizontalHeaderItem(c).setToolTip(tip)
        hdr = t.horizontalHeader()
        for c in range(len(COLS)):
            hdr.setSectionResizeMode(c, QHeaderView.Stretch if c in (NAME, KEYS) else QHeaderView.Fixed)
        t.installEventFilter(self)
        t.setEditTriggers(Table.DoubleClicked | Table.SelectedClicked | Table.EditKeyPressed | Table.AnyKeyPressed)
        self._delegates = {
            ON: ToggleDelegate(t),
            TYPE: ChoiceDelegate(t, CATEGORIES),
            SPACE: NumberDelegate(t, lambda v: (str(v), False) if v else ("auto", True),
                                  lambda parent: Spin(1, 50, parent=parent)),
            MAX: NumberDelegate(t, lambda v: (f"{v or 1} ×", False),
                                lambda parent: Spin(1, 99, suffix=" ×", parent=parent)),
            KEYS: PlaceholderDelegate(t, self._keyword_hint),
            ICON: PillDelegate(t),
        }
        for c, d in self._delegates.items():
            t.setItemDelegateForColumn(c, d)
        self.table.setMinimumHeight(300)
        self.table.itemChanged.connect(self._item_changed)
        items.add(self.table, 1)
        items.add(Banner("Each item needs its icon from the donate window: open <b>Templates</b>, take a screenshot "
                         "of the donate window and capture the keys listed under the screen “Donate” "
                         "(group <b>donate/</b>, e.g. <i>donate/balloon</i>).", "info"))
        lay.addWidget(items, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll(content))

        self.loot_first.toggled.connect(self.changed)
        self.min_keep.valueChanged.connect(self.changed)
        self.rounds.valueChanged.connect(self.changed)
        self.remove_cc.toggled.connect(self.changed)
        self.request_text.textChanged.connect(self.changed)
        self.donate_to.currentIndexChanged.connect(self.changed)
        self.add_btn.clicked.connect(self._add_new)
        self.remove_btn.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        to_templates.clicked.connect(self.templates_requested)
        self._update_notice()

    def _update_notice(self):
        """Data-driven: only shown while one of the donation modes is registered as not ready."""
        modes = [MODES[k] for k in ("loot_donate", "donate_only") if k in MODES]
        self.notice.setVisible(any(not m.ready for m in modes))

    # ------------------------------------------------------------------ table layout
    def eventFilter(self, obj, e):
        if obj is self.table and e.type() == QEvent.Resize:
            self._fit_columns(e.size().width())
        return super().eventFilter(obj, e)

    def _fit_columns(self, width):
        """Fixed columns get a bit narrower in a small window; Name and Keywords share the rest."""
        wide = width >= 980
        sizes = ({ON: 66, TYPE: 118, SPACE: 80, MAX: 132, TPL: 190, ICON: 108} if wide else
                 {ON: 62, TYPE: 108, SPACE: 70, MAX: 122, TPL: 150, ICON: 98})
        hdr = self.table.horizontalHeader()
        for c, w in sizes.items():
            if hdr.sectionSize(c) != w:
                hdr.resizeSection(c, w)

    def _keyword_hint(self, index):
        name = self.table.item(index.row(), NAME)
        words = builtin_keywords(name.text() if name else "")
        return ("built in: " + ", ".join(words)) if words else "add words…"

    # ------------------------------------------------------------------ items
    def _add_new(self):
        self._add({"name": "", "template": "", "clicks": 1, "enabled": True})
        r = self.table.rowCount() - 1
        self.table.selectRow(r)
        self.table.editItem(self.table.item(r, NAME))

    def _add(self, item, row=None):
        t = self.table
        r = t.rowCount() if row is None else row
        name_text = item.get("name", "") or ""
        t.blockSignals(True)
        t.insertRow(r)
        t.setItem(r, ON, _cell(bool(item.get("enabled", True)), FIXED))
        name = QTableWidgetItem(name_text)
        name.setData(OLD, name_text)
        t.setItem(r, NAME, name)
        cat = item.get("category") or (troops.category(name_text) if name_text else None)
        t.setItem(r, TYPE, _cell(cat, EDITABLE))
        space = int(item.get("space") or (troops.space_of(name_text) if name_text else 0))
        t.setItem(r, SPACE, _cell(space, EDITABLE))
        t.setItem(r, MAX, _cell(int(item.get("clicks", 1) or 1), EDITABLE))
        kw = QTableWidgetItem(item.get("keywords", "") or "")
        kw.setToolTip(TIPS[KEYS])
        t.setItem(r, KEYS, kw)
        key = QTableWidgetItem(item.get("template", "") or template_key(name_text))
        key.setToolTip("Template key, e.g. donate/balloon")
        t.setItem(r, TPL, key)
        t.setItem(r, ICON, _cell(None, FIXED))
        t.blockSignals(False)
        self._status(r)
        self.changed.emit()

    def _status(self, r):
        it = self.table.item(r, TPL)
        key = normalize_key(it.text() if it else "")
        pill = (("No key", T.TEXT_DIM) if not key else ("Captured", T.GREEN) if vision.templates.has(key)
                else ("Missing", T.AMBER))
        cell = self.table.item(r, ICON)
        if cell is not None and cell.data(ROLE) != pill:
            self.table.blockSignals(True)
            cell.setData(ROLE, pill)
            self.table.blockSignals(False)

    def refresh_status(self):
        for r in range(self.table.rowCount()):
            self._status(r)

    def _set_quiet(self, r, c, value):
        cell = self.table.item(r, c)
        if cell is not None and cell.data(ROLE) != value:
            self.table.blockSignals(True)
            cell.setData(ROLE, value)
            self.table.blockSignals(False)

    def _item_changed(self, item):
        r, c = item.row(), item.column()
        if c == NAME:
            old = item.data(OLD) or ""
            new = item.text().strip()
            key_item = self.table.item(r, TPL)
            if key_item is not None and (not key_item.text().strip() or key_item.text().strip() == template_key(old)):
                self.table.blockSignals(True)
                key_item.setText(template_key(new))
                self.table.blockSignals(False)
            # type and space follow the name until you change them yourself
            cat = self.table.item(r, TYPE).data(ROLE)
            if not cat or (old and cat == troops.category(old)):
                self._set_quiet(r, TYPE, troops.category(new) if new else None)
            space = self.table.item(r, SPACE).data(ROLE)
            if not space or (old and space == troops.space_of(old)):
                self._set_quiet(r, SPACE, troops.space_of(new) if new else 0)
            self.table.blockSignals(True)
            item.setData(OLD, new)
            self.table.blockSignals(False)
            self.table.viewport().update()
        if c in (NAME, TPL):
            self._status(r)
        self.changed.emit()

    def _row_data(self, r):
        t = self.table
        name = t.item(r, NAME).text().strip() if t.item(r, NAME) else ""
        key = t.item(r, TPL)
        kw = t.item(r, KEYS)
        cat = t.item(r, TYPE).data(ROLE) or (troops.category(name) if name else "troop")
        space = int(t.item(r, SPACE).data(ROLE) or (troops.space_of(name) if name else 1))
        return {"name": name,
                "template": normalize_key(key.text() if key else ""),
                "clicks": int(t.item(r, MAX).data(ROLE) or 1),
                "enabled": bool(t.item(r, ON).data(ROLE)),
                "category": cat,
                "space": space,
                "keywords": ", ".join(w.strip() for w in (kw.text() if kw else "").split(",") if w.strip())}

    def _remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self.changed.emit()

    def _move(self, d):
        r = self.table.currentRow()
        if r < 0 or not (0 <= r + d < self.table.rowCount()):
            return
        data = self._row_data(r)
        self.table.blockSignals(True)
        self.table.removeRow(r)
        self.table.blockSignals(False)
        self._add(data, r + d)
        self.table.selectRow(r + d)

    def showEvent(self, e):
        self.refresh_status()
        super().showEvent(e)

    # ------------------------------------------------------------------ settings io
    def load(self, settings, accounts):
        d = settings.get("donate", {})
        self.loot_first.setChecked(d.get("loot_before_donate", True))
        self.min_keep.setValue(d.get("min_elixir_keep", 4_000_000))
        self.rounds.setValue(d.get("rounds", 0))
        self.remove_cc.setChecked(d.get("remove_cc_before_request", True))
        self.request_text.setText(d.get("request_text", ""))
        self.donate_to.setCurrentIndex(max(0, self.donate_to.findData(d.get("donate_to", "all"))))
        self.blockSignals(True)
        self.table.setRowCount(0)
        for it in d.get("items", []) or []:
            if isinstance(it, dict):
                self._add(it)
        self.blockSignals(False)
        self._update_notice()

    def apply(self, settings, accounts):
        d = settings.setdefault("donate", {})
        d["loot_before_donate"] = self.loot_first.isChecked()
        d["min_elixir_keep"] = self.min_keep.value()
        d["rounds"] = self.rounds.value()
        d["remove_cc_before_request"] = self.remove_cc.isChecked()
        d["request_text"] = self.request_text.text()
        d["donate_to"] = self.donate_to.currentData() or "all"
        d["items"] = [it for it in (self._row_data(r) for r in range(self.table.rowCount()))
                      if it["name"] or it["template"]]

    def set_running(self, running):
        self.setEnabled(not running)

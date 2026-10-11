"""Donate page: settings for the Loot + Donate and Donate only modes, and what the Main account donates."""

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QTableWidgetItem, QVBoxLayout, QWidget

from bot.core import vision
from bot.modes import MODES, load_all
from gui import theme as T
from gui.components import (ROLE, Banner, Button, Card, IconButton, NumberDelegate, PillDelegate, SettingRow, Table,
                            Toggle, ToggleDelegate, divider, field, hbox, scroll)
from gui.widgets import BigSpin, Spin

COLS = ["On", "Name", "Template", "Clicks per request", "Icon"]


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


class DonateTab(QWidget):
    changed = Signal()
    templates_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        load_all()
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(16)
        self.notice = Banner("<b>The donation modes are coming soon.</b> The clan chat, donate window and Clan Castle "
                             "request screens are still being mapped. Everything here is saved now and used by them.",
                             "warning")
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
        row.addWidget(cycle, 1)

        req = Card("Clan Castle requests", "What the Feeder accounts do.", icon="send", color="#5cc8ff")
        self.remove_cc = Toggle()
        req.add(SettingRow("Empty the Clan Castle first", "Feeders remove their Clan Castle troops before requesting",
                           self.remove_cc))
        req.add(divider())
        self.request_text = QLineEdit()
        self.request_text.setPlaceholderText("(optional) text sent with the request")
        self.request_text.setMaxLength(120)
        req.add(field("Request message", self.request_text))
        req.layout().addStretch(1)
        row.addWidget(req, 1)
        lay.addLayout(row)

        items = Card("What the Main account donates", "In priority order: the first enabled item that a request "
                     "can take is donated first.", icon="gift", color=T.GOLD)
        self.add_btn = Button("Add item", "plus", "secondary", "sm")
        self.remove_btn = Button("Remove", "trash", "secondary", "sm")
        up = IconButton("arrow-up", "Move up", variant="secondary")
        down = IconButton("arrow-down", "Move down", variant="secondary")
        to_templates = Button("Capture icons in Templates", "scan", "outline", "sm")
        items.add(hbox(self.add_btn, self.remove_btn, up, down, None, to_templates, spacing=8))
        t = self.table = Table(COLS, row_height=46)
        t.empty_text = "Nothing to donate yet.\nAdd the troops, spells and siege machines your Main gives."
        t.empty_icon = "gift"
        t.resize_modes(1, {0: 72, 2: 250, 3: 160, 4: 120})
        t.setEditTriggers(Table.DoubleClicked | Table.SelectedClicked | Table.EditKeyPressed | Table.AnyKeyPressed)
        self._delegates = [ToggleDelegate(t), NumberDelegate(t, lambda v: (f"{v or 1} ×", False),
                                                             lambda parent: Spin(1, 99, suffix=" ×", parent=parent)),
                           PillDelegate(t)]
        t.setItemDelegateForColumn(0, self._delegates[0])
        t.setItemDelegateForColumn(3, self._delegates[1])
        t.setItemDelegateForColumn(4, self._delegates[2])
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
        self.add_btn.clicked.connect(self._add_new)
        self.remove_btn.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        to_templates.clicked.connect(self.templates_requested)
        self._update_notice()

    def _update_notice(self):
        modes = [MODES[k] for k in ("loot_donate", "donate_only") if k in MODES]
        self.notice.setVisible(any(not m.ready for m in modes))

    # ------------------------------------------------------------------ items
    def _add_new(self):
        self._add({"name": "", "template": "", "clicks": 1, "enabled": True})
        r = self.table.rowCount() - 1
        self.table.selectRow(r)
        self.table.editItem(self.table.item(r, 1))

    def _add(self, item, row=None):
        t = self.table
        r = t.rowCount() if row is None else row
        t.blockSignals(True)
        t.insertRow(r)
        fixed = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        t.setItem(r, 0, _cell(bool(item.get("enabled", True)), fixed))
        name = QTableWidgetItem(item.get("name", ""))
        name.setData(Qt.UserRole + 1, item.get("name", ""))
        t.setItem(r, 1, name)
        key = QTableWidgetItem(item.get("template", "") or template_key(item.get("name", "")))
        key.setToolTip("Template key, e.g. donate/balloon")
        t.setItem(r, 2, key)
        t.setItem(r, 3, _cell(int(item.get("clicks", 1) or 1), fixed | Qt.ItemIsEditable))
        t.setItem(r, 4, _cell(None, fixed))
        t.blockSignals(False)
        self._status(r)
        self.changed.emit()

    def _status(self, r):
        it = self.table.item(r, 2)
        key = normalize_key(it.text() if it else "")
        pill = (("No key", T.TEXT_DIM) if not key else ("Captured", T.GREEN) if vision.templates.has(key)
                else ("Missing", T.AMBER))
        cell = self.table.item(r, 4)
        if cell is not None and cell.data(ROLE) != pill:
            self.table.blockSignals(True)
            cell.setData(ROLE, pill)
            self.table.blockSignals(False)

    def refresh_status(self):
        for r in range(self.table.rowCount()):
            self._status(r)

    def _item_changed(self, item):
        r, c = item.row(), item.column()
        if c == 1:
            old = item.data(Qt.UserRole + 1) or ""
            new = item.text().strip()
            key_item = self.table.item(r, 2)
            if key_item is not None and (not key_item.text().strip() or key_item.text().strip() == template_key(old)):
                key_item.setText(template_key(new))
            item.setData(Qt.UserRole + 1, new)
        if c in (1, 2):
            self._status(r)
        self.changed.emit()

    def _row_data(self, r):
        name = self.table.item(r, 1)
        key = self.table.item(r, 2)
        return {"name": name.text().strip() if name else "",
                "template": normalize_key(key.text() if key else ""),
                "clicks": int(self.table.item(r, 3).data(ROLE) or 1),
                "enabled": bool(self.table.item(r, 0).data(ROLE))}

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
        d["items"] = [it for it in (self._row_data(r) for r in range(self.table.rowCount()))
                      if it["name"] or it["template"]]

    def set_running(self, running):
        self.setEnabled(not running)

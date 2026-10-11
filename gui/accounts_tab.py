"""Accounts page: the list of Supercell ID accounts, their role and limits."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QTableWidgetItem, QVBoxLayout, QWidget

from bot import config
from gui import icons
from gui import theme as T
from gui.components import (ROLE, Banner, Button, Card, ChoiceDelegate, IconButton, NumberDelegate, Pill, Table,
                            ToggleDelegate, hbox)
from gui.widgets import BigSpin, Spin

# role, label, icon, colour, hint.  Main loots and donates; Loot only just loots (never requests); Loot + request
# loots in "Loot all" and also requests in the donation modes; Feeder only requests; Skip is ignored.
ROLES = [("main", "Main (donates)", "crown", T.GOLD, "Loots and donates to the others"),
         ("loot", "Loot only", "swords", T.ELIXIR_HI, "Just loots, never requests troops"),
         ("both", "Loot + request", "sparkles", "#4fd1c5",
          "Loots in “Loot all” and also requests in the donation modes"),
         ("feeder", "Feeder (requests)", "send", "#5cc8ff", "Only requests troops"),
         ("skip", "Skip", "x-circle", T.TEXT_DIM, "Ignored by every mode")]
COLS = ["Use", "Name (as in the switch list)", "Role", "Town Hall", "Gold full at", "Elixir full at",
        "Dark full at"]
EDITABLE = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable


def resource_icon(res, size=16):
    ic = QIcon()
    for dpr in (1.0, 1.25, 1.5, 2.0):
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        icons.paint_resource(p, res, QRectF(0, 0, size * dpr, size * dpr))
        p.end()
        pm.setDevicePixelRatio(dpr)
        ic.addPixmap(pm)
    return ic


def _th_text(v):
    return (f"TH {v}", False) if v else ("?", True)


def _full_text(v):
    return (f"{v:,}", False) if v else ("TH table", True)


def _full_editor(parent, res):
    sp = BigSpin(maximum=100_000_000, step=500_000 if res != "dark" else 10_000, parent=parent)
    sp.setSpecialValueText("TH table")
    sp.setMinimumWidth(60)
    return sp


def _th_editor(parent):
    sp = Spin(0, 25, special="?", parent=parent)
    sp.setPrefix("TH ")
    return sp


class AccountsTab(QWidget):
    changed = Signal()
    scan_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(Banner("Names must match the Supercell ID switch list (small typos are fine). Town Hall is "
                             "filled in automatically when the bot switches. <b>Full at</b> left at “TH table” uses "
                             "the Town Hall table in Loot settings. Click a cell to change it.", "info"))

        self.add_btn = Button("Add", "plus", "secondary", "sm")
        self.remove_btn = Button("Remove", "trash", "secondary", "sm")
        self.up_btn = IconButton("arrow-up", "Move up", variant="secondary")
        self.down_btn = IconButton("arrow-down", "Move down", variant="secondary")
        self.scan_btn = Button("Read names from the game…", "download", "outline", "sm")
        self.scan_btn.setToolTip("Opens Settings → Switch ID in the game and reads every account name")
        self.pills = {k: Pill("", c) for k, c in (("total", T.TEXT_MUTED), ("main", T.GOLD), ("loot", T.ELIXIR_HI),
                                                   ("both", "#4fd1c5"), ("feeder", "#5cc8ff"), ("off", T.TEXT_DIM))}
        lay.addLayout(hbox(self.add_btn, self.remove_btn, self.up_btn, self.down_btn, 8, *self.pills.values(), None,
                           self.scan_btn, spacing=8))

        card = Card(padding=1)
        t = self.table = Table(COLS, row_height=48)
        t.empty_text = "No accounts yet.\nAdd them one by one or let the bot read the names from the game."
        t.empty_icon = "users"
        t.resize_modes(1, {0: 72, 2: 190, 3: 100, 4: 138, 5: 138, 6: 130})
        t.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
                          | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)
        self._delegates = [ToggleDelegate(t), ChoiceDelegate(t, ROLES), NumberDelegate(t, _th_text, _th_editor)]
        t.setItemDelegateForColumn(0, self._delegates[0])
        t.setItemDelegateForColumn(2, self._delegates[1])
        t.setItemDelegateForColumn(3, self._delegates[2])
        for i, res in enumerate(config.RESOURCES):
            d = NumberDelegate(t, _full_text, lambda parent, r=res: _full_editor(parent, r))
            self._delegates.append(d)
            t.setItemDelegateForColumn(4 + i, d)
            t.horizontalHeaderItem(4 + i).setIcon(resource_icon(res))
        t.itemChanged.connect(lambda *_: self.changed.emit())
        card.add(t, 1)
        lay.addWidget(card, 1)

        self.add_btn.clicked.connect(self._add_new)
        self.remove_btn.clicked.connect(self._remove)
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.scan_btn.clicked.connect(self.scan_requested)
        self.changed.connect(self._summary)
        self._summary()

    # --------------------------------------------------------------------- rows
    @staticmethod
    def _cell(value, flags=EDITABLE):
        it = QTableWidgetItem("")
        it.setData(ROLE, value)
        it.setFlags(flags)
        return it

    def _add_new(self):
        self._add(config.new_account(""))
        r = self.table.rowCount() - 1
        self.table.selectRow(r)
        self.table.scrollToBottom()
        self.table.editItem(self.table.item(r, 1))

    def _add(self, acc, row=None):
        t = self.table
        r = t.rowCount() if row is None else row
        t.insertRow(r)
        t.setItem(r, 0, self._cell(bool(acc.get("enabled", True)), Qt.ItemIsEnabled | Qt.ItemIsSelectable))
        name = QTableWidgetItem(acc.get("name", ""))
        name.setFlags(EDITABLE)
        t.setItem(r, 1, name)
        t.setItem(r, 2, self._cell(acc.get("role", "loot")))
        t.setItem(r, 3, self._cell(int(acc.get("th") or 0)))
        for i, res in enumerate(config.RESOURCES):
            t.setItem(r, 4 + i, self._cell(int((acc.get("full_at") or {}).get(res, 0) or 0)))
        self.changed.emit()

    def _row_data(self, r):
        t = self.table
        name_item = t.item(r, 1)
        return {
            "name": name_item.text().strip() if name_item else "",
            "enabled": bool(t.item(r, 0).data(ROLE)),
            "role": t.item(r, 2).data(ROLE),
            "th": t.item(r, 3).data(ROLE) or 0,
            "full_at": {res: t.item(r, 4 + i).data(ROLE) or 0 for i, res in enumerate(config.RESOURCES)},
        }

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
        self._add(data, r + d)
        self.table.blockSignals(False)
        self.table.selectRow(r + d)
        self.changed.emit()

    def _summary(self):
        rows = [self._row_data(r) for r in range(self.table.rowCount())]
        on = [a for a in rows if a["enabled"] and a["role"] != "skip"]
        self.pills["total"].set(f"{len(rows)} accounts")
        for k, text in (("main", "Main"), ("loot", "Loot only"), ("both", "Loot + request"), ("feeder", "Feeder")):
            n = sum(1 for a in on if a["role"] == k)
            self.pills[k].set(f"{n} {text}")
            self.pills[k].setVisible(n > 0)
        off = len(rows) - len(on)
        self.pills["off"].set(f"{off} off / skipped")
        self.pills["off"].setVisible(off > 0)
        self.pills["total"].setVisible(bool(rows))

    def count(self):
        return self.table.rowCount()

    # ------------------------------------------------------------- settings io
    def load(self, settings, accounts):
        self.blockSignals(True)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for a in accounts:
            self._add(a)
        self.table.blockSignals(False)
        self.blockSignals(False)
        self.table.viewport().update()
        self._summary()

    def apply(self, settings, accounts):
        accounts[:] = [d for d in (self._row_data(r) for r in range(self.table.rowCount())) if d["name"]]

    def merge_scanned(self, found):
        """Add accounts read from the game that are not in the table yet; fill in Town Halls."""
        existing = {self._row_data(r)["name"].lower(): r for r in range(self.table.rowCount())}
        added = 0
        for name, th in found:
            r = existing.get(name.lower())
            if r is None:
                acc = config.new_account(name, th=th)
                self._add(acc)
                added += 1
            elif th:
                self.table.item(r, 3).setData(ROLE, int(th))
        self.changed.emit()
        return added

    def set_running(self, running):
        self.setEnabled(not running)

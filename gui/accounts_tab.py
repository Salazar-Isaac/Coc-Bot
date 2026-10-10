"""Accounts tab: the list of Supercell ID accounts, their role and limits."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from bot import config
from gui.widgets import BigSpin

ROLES = [("main", "Main (donates)"), ("loot", "Loot only"), ("feeder", "Feeder (requests)"), ("skip", "Skip")]
COLS = ["Use", "Name (as in the switch list)", "Role", "Town Hall", "Gold full at", "Elixir full at",
        "Dark full at"]


class AccountsTab(QWidget):
    changed = Signal()
    scan_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        tip = QLabel("Names must match the Supercell ID switch list (small typos are fine). "
                     "Town Hall is filled in automatically when the bot switches. "
                     "\"Full at\" 0 = use the Town Hall table in Loot Settings.")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3, 4, 5, 6):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.remove_btn = QPushButton("Remove")
        self.up_btn = QPushButton("Move up")
        self.down_btn = QPushButton("Move down")
        self.scan_btn = QPushButton("Read names from the game…")
        self.scan_btn.setToolTip("Opens Settings → Switch ID in the game and reads every account name")
        for b in (self.add_btn, self.remove_btn, self.up_btn, self.down_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.scan_btn)
        lay.addLayout(row)
        self.add_btn.clicked.connect(lambda: self._add(config.new_account("")))
        self.remove_btn.clicked.connect(self._remove)
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.scan_btn.clicked.connect(self.scan_requested)

    # --------------------------------------------------------------------- rows
    def _add(self, acc, row=None):
        t = self.table
        r = t.rowCount() if row is None else row
        t.insertRow(r)
        use = QCheckBox()
        use.setChecked(acc.get("enabled", True))
        use.setStyleSheet("margin-left:12px;")
        use.toggled.connect(self.changed)
        t.setCellWidget(r, 0, use)
        t.setItem(r, 1, QTableWidgetItem(acc.get("name", "")))
        role = QComboBox()
        for k, label in ROLES:
            role.addItem(label, k)
        role.setCurrentIndex(max(0, role.findData(acc.get("role", "loot"))))
        role.currentIndexChanged.connect(self.changed)
        t.setCellWidget(r, 2, role)
        th = QSpinBox()
        th.setRange(0, 25)
        th.setSpecialValueText("?")
        th.setValue(acc.get("th") or 0)
        th.valueChanged.connect(self.changed)
        t.setCellWidget(r, 3, th)
        for i, res in enumerate(config.RESOURCES):
            sp = BigSpin(maximum=100_000_000, step=500_000 if res != "dark" else 10_000)
            sp.setSpecialValueText("TH table")
            sp.setValue((acc.get("full_at") or {}).get(res, 0))
            sp.valueChanged.connect(self.changed)
            t.setCellWidget(r, 4 + i, sp)
        self.changed.emit()

    def _row_data(self, r):
        t = self.table
        name_item = t.item(r, 1)
        return {
            "name": name_item.text().strip() if name_item else "",
            "enabled": t.cellWidget(r, 0).isChecked(),
            "role": t.cellWidget(r, 2).currentData(),
            "th": t.cellWidget(r, 3).value(),
            "full_at": {res: t.cellWidget(r, 4 + i).value() for i, res in enumerate(config.RESOURCES)},
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
        self.table.removeRow(r)
        self._add(data, r + d)
        self.table.selectRow(r + d)

    # ------------------------------------------------------------- settings io
    def load(self, settings, accounts):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for a in accounts:
            self._add(a)
        self.table.blockSignals(False)

    def apply(self, settings, accounts):
        accounts[:] = [self._row_data(r) for r in range(self.table.rowCount()) if self._row_data(r)["name"]]

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
                self.table.cellWidget(r, 3).setValue(th)
        self.changed.emit()
        return added

    def set_running(self, running):
        self.setEnabled(not running)

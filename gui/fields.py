"""Editors used by the flow's settings: account positions, ordered name lists (drag to reorder) and the
attack plan picker."""

import os

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QCompleter, QLabel, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from bot import flow
from bot.actions import attack
from gui import icons
from gui import theme as T
from gui.components import Button, FlowLayout, IconButton, SettingRow, Tween, _popup_style, hbox, label
from gui.widgets import Combo

# words in attack plan names (config/attack_plans.json) shown nicer in the dropdown: edrag_clone -> E-Dragons + Clone
PLAN_WORDS = {"edrag": "E-Dragons", "edrags": "E-Dragons", "lalo": "LaLo", "pekka": "P.E.K.K.A", "clone": "+ Clone",
              "rage": "+ Rage", "freeze": "+ Freeze", "th": "TH", "bk": "King", "aq": "Queen", "gw": "Warden",
              "rc": "Champion"}


def plan_title(name, plan=None):
    """Display name of an attack plan: its "title" if it has one, else the key made readable."""
    title = (plan or {}).get("title")
    if title:
        return str(title)
    words = [PLAN_WORDS.get(w.lower(), w.capitalize()) for w in str(name).replace("-", "_").split("_") if w]
    return " ".join(words) or str(name)


def block(title, description="", *widgets, spacing=8):
    """A title (+ description) with widgets under it at full width."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(spacing)
    lay.addWidget(SettingRow(title, description))
    for x in widgets:
        if isinstance(x, QWidget):
            lay.addWidget(x)
        else:
            lay.addLayout(x)
    return w


# ----------------------------------------------------------------------------- account positions
class AccountsField(QWidget):
    """Account positions ("1-15", "3,5,9-12"; empty = all) with a live preview of the names they pick.
    The text gets a red border while it is not a valid list."""

    changed = Signal()

    def __init__(self, title="Accounts", description="Positions in the Accounts list, e.g. 1-15 or 3,5,9-12. "
                 "Empty = all.", parent=None):
        super().__init__(parent)
        self._accounts = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("all")
        self.edit.setMaxLength(80)
        self.edit.setClearButtonEnabled(True)
        self.edit.setFixedWidth(170)
        self.row = SettingRow(title, description, self.edit)
        lay.addWidget(self.row)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.preview = label("", "small", wrap=True)
        self.preview.setMinimumWidth(10)
        lay.addLayout(hbox(self.icon, self.preview, spacing=7, margins=(0, 0, 0, 2)))
        self.edit.textChanged.connect(self._update)
        self.edit.textChanged.connect(self.changed)
        self._update()

    def text(self):
        return self.edit.text().strip()

    def set_text(self, text):
        self.edit.blockSignals(True)
        self.edit.setText(str(text or ""))
        self.edit.blockSignals(False)
        self._update()

    def is_valid(self):
        return flow.spec_ok(self.text())

    def set_accounts(self, accounts):
        self._accounts = list(accounts or [])
        self._update()

    def picked(self):
        return flow.step_accounts(self.text(), self._accounts) if self.is_valid() else []

    def _update(self, *_):
        ok = self.is_valid()
        if self.edit.property("invalid") != (not ok):
            self.edit.setProperty("invalid", not ok)
            self.edit.style().unpolish(self.edit)
            self.edit.style().polish(self.edit)
        if ok:
            text = flow.describe_accounts(self.text(), self._accounts)
            color = T.TEXT_MUTED if self.picked() else T.AMBER
            self.icon.setPixmap(icons.pixmap("users", color, 14))
        else:
            text = "Not a valid list. Use positions like 1-15 or 3,5,9-12."
            color = T.RED
            self.icon.setPixmap(icons.pixmap("x-circle", color, 14))
        self.preview.setText(text)
        self.preview.setStyleSheet(f"color: {color};")
        self.preview.setToolTip(", ".join(a["name"] for _, a in self.picked()) if ok else "")


# ----------------------------------------------------------------------------- ordered name list
MIME_ORDER = "application/x-cocbot-order"


class OrderChip(QWidget):
    """One entry of an OrderList: position number, name, remove (×). Drag it to move it."""

    H = 30

    def __init__(self, owner, text, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.text = text
        self.index = 0
        self.selected = False
        self.dragging = False
        self._hover = Tween(self, ms=140)
        self._x_hover = Tween(self, ms=120)
        self._on_x = False
        self._press = None
        self.setMouseTracking(True)
        self.setFixedHeight(self.H)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.OpenHandCursor)

    def _font(self):
        return T.font(9.25, QFont.Medium)

    def _num_w(self):
        return max(20, QFontMetrics(T.font(7.75, QFont.Bold)).horizontalAdvance(str(self.index + 1)) + 10)

    def sizeHint(self):
        return QSize(8 + self._num_w() + 8 + QFontMetrics(self._font()).horizontalAdvance(self.text) + 32, self.H)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _x_rect(self):
        return QRectF(self.width() - 25, (self.H - 20) / 2, 20, 20)

    def _set_on_x(self, on):
        on = on and self.isEnabled()
        if on != self._on_x:
            self._on_x = on
            self._x_hover.to(1.0 if on else 0.0)
            self.setCursor(Qt.PointingHandCursor if on else Qt.OpenHandCursor)
            self.setToolTip(f"Remove “{self.text}”" if on else "Drag to move it; click to select it")

    def enterEvent(self, e):
        self._hover.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover.to(0.0)
        self._set_on_x(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self._set_on_x(self._x_rect().adjusted(-4, -4, 4, 4).contains(e.position()))
        if (self._press is not None and e.buttons() & Qt.LeftButton and self.isEnabled()
                and (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            self._press = None
            self.owner._start_drag(self)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        if e.button() == Qt.LeftButton and self.isEnabled():
            if self._x_rect().adjusted(-4, -4, 4, 4).contains(e.position()):
                self.owner.remove_at(self.index)
            else:
                self.owner.select(self.index)
            return
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        if self.dragging:
            p.setOpacity(0.35)
        h, xh = self._hover.value, self._x_hover.value
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = r.height() / 2
        border = T.GOLD if self.selected else T.mix(T.BORDER_STRONG, "#46507f", h)
        p.setPen(QPen(QColor(border), 1.3 if self.selected else 1))
        p.setBrush(T.mix(T.INPUT, "#1a1f38", h) if not self.selected else T.mix(T.INPUT, T.GOLD, 0.10))
        p.drawRoundedRect(r, rad, rad)
        nw = self._num_w()
        nr = QRectF(r.left() + 5, r.center().y() - 10, nw, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(T.qc(T.GOLD, 0.16 if self.selected else 0.10))
        p.drawRoundedRect(nr, 10, 10)
        p.setFont(T.font(7.75, QFont.Bold))
        p.setPen(QColor(T.GOLD_HI if self.selected else T.mix(T.GOLD, T.TEXT_MUTED, 0.45)))
        p.drawText(nr, Qt.AlignCenter, str(self.index + 1))
        p.setFont(self._font())
        p.setPen(QColor(T.TEXT))
        tx = nr.right() + 8
        p.drawText(QRectF(tx, r.top(), r.width() - tx - 28, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        xr = self._x_rect()
        if xh > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(T.qc(T.RED, 0.18 * xh))
            p.drawEllipse(xr)
        icons.paint(p, "x", T.mix(T.mix(T.TEXT_DIM, T.TEXT_MUTED, h), T.RED, xh), xr.adjusted(5, 5, -5, -5))


class _ChipArea(QWidget):
    """Holds the chips (wrapping) and takes chip drops, showing where the chip will land."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.flow = FlowLayout(self, 8, 8)
        self.setAcceptDrops(True)
        self.marker = None              # QRect of the insertion bar while dragging

    def _insert_index(self, pos):
        chips = self.owner._chips
        if not chips:
            return 0
        best, best_d = None, None
        for i, c in enumerate(chips):
            g = c.geometry()
            dy = 0 if g.top() - 4 <= pos.y() <= g.bottom() + 4 else min(abs(pos.y() - g.top()),
                                                                           abs(pos.y() - g.bottom()))
            dx = 0 if g.left() <= pos.x() <= g.right() else min(abs(pos.x() - g.left()), abs(pos.x() - g.right()))
            d = dy * 1000 + dx
            if best_d is None or d < best_d:
                best, best_d = i, d
        g = chips[best].geometry()
        return best if pos.x() < g.center().x() else best + 1

    def _marker_rect(self, index):
        chips = self.owner._chips
        if not chips:
            return None
        if index < len(chips):
            g = chips[index].geometry()
            return QRect(g.left() - 6, g.top() - 1, 3, g.height() + 2)
        g = chips[-1].geometry()
        return QRect(g.right() + 3, g.top() - 1, 3, g.height() + 2)

    def _ours(self, e):
        md = e.mimeData()
        return md.hasFormat(MIME_ORDER) and bytes(md.data(MIME_ORDER)).decode().split(":")[0] == str(id(self.owner))

    def dragEnterEvent(self, e):
        if self._ours(e):
            e.setDropAction(Qt.MoveAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if not self._ours(e):
            e.ignore()
            return
        self.marker = self._marker_rect(self._insert_index(e.position().toPoint()))
        self.update()
        e.setDropAction(Qt.MoveAction)
        e.accept()

    def dragLeaveEvent(self, e):
        self.marker = None
        self.update()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self.marker = None
        self.update()
        if not self._ours(e):
            e.ignore()
            return
        src = int(bytes(e.mimeData().data(MIME_ORDER)).decode().split(":")[1])
        self.owner.move(src, self._insert_index(e.position().toPoint()))
        e.setDropAction(Qt.MoveAction)
        e.accept()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.marker is not None:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.GOLD))
            p.drawRoundedRect(QRectF(self.marker), 1.5, 1.5)


class OrderList(QWidget):
    """An ordered list of names (buildings, research) shown as numbered chips. Drag a chip to move it, or
    select it and use the arrows; × removes it. New names come from a combo (typed names are fine too)."""

    changed = Signal()

    def __init__(self, suggestions=(), placeholder="Add…", empty_text="Nothing in the list yet.", defaults=None,
                 parent=None):
        super().__init__(parent)
        self._values = []
        self._chips = []
        self._selected = -1
        self.defaults = list(defaults) if defaults else None
        self.suggestions = list(suggestions)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)
        self.area = _ChipArea(self)
        lay.addWidget(self.area)
        self.empty = label(empty_text, "small", wrap=True)
        self.empty.setStyleSheet(f"color: {T.TEXT_DIM};")
        lay.addWidget(self.empty)

        self.combo = Combo(editable=True)
        self.combo.addItems(self.suggestions)
        self.combo.setCurrentIndex(-1)
        self.combo.lineEdit().setPlaceholderText(placeholder)
        self.combo.setInsertPolicy(Combo.NoInsert)
        self.combo.setMaxVisibleItems(12)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setMinimumWidth(120)
        comp = QCompleter(self.suggestions, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.setMaxVisibleItems(8)
        comp.popup().setStyleSheet(_popup_style())
        comp.popup().setFont(T.font(9.5))
        self.combo.setCompleter(comp)
        self.add_btn = Button("Add", "plus", "secondary")
        self.up_btn = IconButton("arrow-left", "Move the selected one earlier", size="md", variant="secondary")
        self.down_btn = IconButton("arrow-right", "Move the selected one later", size="md", variant="secondary")
        row = hbox(self.combo, self.add_btn, 6, self.up_btn, self.down_btn, spacing=6)
        self.reset_btn = None
        if self.defaults:
            self.reset_btn = Button("Reset to default", "refresh", "ghost", "sm")
            self.reset_btn.setToolTip("Back to: " + ", ".join(self.defaults))
            self.reset_btn.clicked.connect(self.reset)
        lay.addLayout(row)
        if self.reset_btn is not None:
            lay.addLayout(hbox(label("Drag a chip to change the order.", "small"), None, self.reset_btn))
        else:
            lay.addWidget(label("Drag a chip to change the order.", "small"))
        self.add_btn.clicked.connect(self._add_current)
        self.combo.lineEdit().returnPressed.connect(self._add_current)
        self.combo.activated.connect(lambda _i: QTimer.singleShot(0, self._add_current))
        self.up_btn.clicked.connect(lambda: self._shift(-1))
        self.down_btn.clicked.connect(lambda: self._shift(1))
        self._sync()

    # --- api
    def values(self):
        return list(self._values)

    def set_values(self, values):
        seen, clean = set(), []
        for v in values or []:
            v = str(v).strip()
            if v and v.casefold() not in seen:
                seen.add(v.casefold())
                clean.append(v)
        self._values = clean
        self._selected = -1
        self._rebuild()

    def add(self, text):
        text = str(text or "").strip()
        if not text or text.casefold() in {v.casefold() for v in self._values}:
            return False
        self._values.append(text)
        self._selected = len(self._values) - 1
        self._rebuild()
        self.changed.emit()
        return True

    def remove_at(self, i):
        if 0 <= i < len(self._values):
            del self._values[i]
            self._selected = min(self._selected, len(self._values) - 1) if self._selected != i else -1
            self._rebuild()
            self.changed.emit()

    def move(self, src, dst):
        """Move entry src so that it lands before position dst (dst counted before the move)."""
        if not 0 <= src < len(self._values):
            return
        dst = max(0, min(len(self._values), dst))
        if dst > src:
            dst -= 1
        if dst == src:
            return
        v = self._values.pop(src)
        self._values.insert(dst, v)
        self._selected = dst
        self._rebuild()
        self.changed.emit()

    def select(self, i):
        self._selected = i if self._selected != i else -1
        self._sync_chips()

    def reset(self):
        if self.defaults is not None and self._values != self.defaults:
            self.set_values(self.defaults)
            self.changed.emit()

    # --- internals
    def _add_current(self):
        text = self.combo.currentText().strip()
        if text:
            self.add(text)
        self.combo.setCurrentIndex(-1)
        self.combo.setEditText("")

    def _shift(self, d):
        i = self._selected
        if 0 <= i < len(self._values) and 0 <= i + d < len(self._values):
            self.move(i, i + d + (1 if d > 0 else 0))

    def _start_drag(self, chip):
        drag = QDrag(chip)
        md = QMimeData()
        md.setData(MIME_ORDER, QByteArray(f"{id(self)}:{chip.index}".encode()))
        drag.setMimeData(md)
        pm = chip.grab()
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2 // max(1, int(pm.devicePixelRatio())), chip.height() // 2))
        chip.dragging = True
        chip.update()
        drag.exec(Qt.MoveAction)
        if chip in self._chips:
            chip.dragging = False
            chip.update()
        self.area.marker = None
        self.area.update()

    def _rebuild(self):
        for c in self._chips:
            self.area.flow.removeWidget(c)
            c.hide()
            c.deleteLater()
        self._chips = []
        for i, v in enumerate(self._values):
            c = OrderChip(self, v, self.area)
            c.index = i
            c.setEnabled(self.isEnabled())
            self.area.flow.addWidget(c)
            c.show()
            self._chips.append(c)
        self._sync()

    def _sync_chips(self):
        for i, c in enumerate(self._chips):
            c.selected = i == self._selected
            c.update()
        sel = 0 <= self._selected < len(self._values)
        self.up_btn.setEnabled(sel and self._selected > 0)
        self.down_btn.setEnabled(sel and self._selected < len(self._values) - 1)

    def _sync(self):
        has = bool(self._values)
        self.area.setVisible(has)
        self.empty.setVisible(not has)
        if self.reset_btn is not None:
            self.reset_btn.setEnabled(self._values != self.defaults)
        self._sync_chips()
        self.area.flow.invalidate()
        self.area.updateGeometry()
        self.updateGeometry()


# ----------------------------------------------------------------------------- attack plan
class PlanPicker(QWidget):
    """Attack plan combo (config/attack_plans.json) with "Edit plans" and the plan's description."""

    changed = Signal()

    def __init__(self, title="Attack plan", parent=None):
        super().__init__(parent)
        self._plans = {}
        self._wanted = "edrag_spread"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 4)
        lay.setSpacing(6)
        self.combo = Combo()
        edit = Button("Edit plans", "edit", "ghost", "sm")
        edit.setToolTip("Opens config/attack_plans.json")
        edit.clicked.connect(lambda: os.startfile(attack.PLANS_PATH))
        self.desc = label("", "rowDesc", wrap=True)
        lay.addLayout(hbox(label(title, "rowTitle"), None, edit))
        lay.addWidget(self.combo)
        lay.addWidget(self.desc)
        self.combo.currentIndexChanged.connect(self._changed)

    def reload(self, selected=None):
        selected = selected or self._wanted
        self._wanted = selected
        self.combo.blockSignals(True)
        self.combo.clear()
        try:
            self._plans = attack.load_plans()
        except (OSError, ValueError):
            self._plans = {}
        for name, plan in self._plans.items():
            self.combo.addItem(plan_title(name, plan), name)
            desc = plan.get("description", "")
            self.combo.setItemData(self.combo.count() - 1, f"{name}: {desc}" if desc else name, Qt.ToolTipRole)
        if selected and self.combo.findData(selected) < 0:      # keep a plan that is not in the file (any more)
            self.combo.addItem(f"{plan_title(selected)} (not in attack_plans.json)", selected)
        self.combo.select(selected)
        self.combo.blockSignals(False)
        self._show_desc()

    def plan(self):
        return self.combo.currentData() or self._wanted or "edrag_spread"

    def _show_desc(self):
        plan = self._plans.get(self.combo.currentData()) or {}
        self.desc.setText(plan.get("description", ""))
        self.desc.setVisible(bool(plan.get("description")))

    def _changed(self, *_):
        self._wanted = self.combo.currentData() or self._wanted
        self._show_desc()
        self.changed.emit()

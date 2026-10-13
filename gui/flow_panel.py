"""Left column: the Functions palette and the Flow box.

Drag a function from the palette into the flow (or double-click it / press its +), drag flow rows to
reorder them, × removes a row (dragging a row back onto the palette removes it too). A function may be in
the flow more than once. Presets replace the whole flow in one click. Saved as settings["flow"]."""

import math

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QListView, QListWidget, QListWidgetItem, QSizePolicy,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from bot.flow import BY_KEY, PRESETS, STEPS
from gui import icons
from gui import theme as T
from gui.components import Button, Card, FlowLayout, Pill, Tween, label
from gui.step_settings import STEP_COLORS

KEY = Qt.UserRole
MIME_STEP = "application/x-cocbot-step"         # a function key (from the palette or a flow row)
MIME_ROW = "application/x-cocbot-flow-row"      # the row of a dragged flow row
FULL_H, COMPACT_H, GRID_H, FLOW_H = 50, 34, 38, 42      # row heights
# palette densities, roomiest first: title over description / both on one line / two columns of titles
DENSITIES = ("full", "compact", "grid")


def _mime(key, row=None):
    md = QMimeData()
    md.setData(MIME_STEP, QByteArray(key.encode()))
    if row is not None:
        md.setData(MIME_ROW, QByteArray(str(row).encode()))
    return md


def _key_of(md):
    return bytes(md.data(MIME_STEP)).decode() if md.hasFormat(MIME_STEP) else ""


def _row_of(md):
    try:
        return int(bytes(md.data(MIME_ROW)).decode())
    except ValueError:
        return -1


# ----------------------------------------------------------------------------- palette
class _PaletteDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        view = self.parent()
        if view.density == "grid":
            return QSize(max(60, (view.inner_width() - 1) // 2), GRID_H)
        return QSize(max(60, view.inner_width()), view.row_h())

    def paint(self, p, option, index):
        view = self.parent()
        key = index.data(KEY)
        step = BY_KEY[key]
        color = STEP_COLORS.get(key, T.GOLD)
        row = index.row()
        hover = row == view.hover_row and view.isEnabled()
        current = key == view.current
        compact = view.density != "full"
        grid = view.density == "grid"
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(option.rect).adjusted(0.5, 2.5, -0.5, -2.5)
        if grid:
            r.adjust(0 if index.row() % 2 == 0 else 3, 0, -3 if index.row() % 2 == 0 else 0, 0)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, T.mix(T.SURFACE_2, "#222844", 0.8 if hover else 0.0))
        if current:
            p.fillPath(path, T.qc(T.GOLD, 0.08))
        p.setPen(QPen(QColor(T.GOLD) if current else T.mix(T.BORDER, "#3a4370", 0.8 if hover else 0.0),
                      1.3 if current else 1))
        p.drawPath(path)

        ts = 26.0 if compact else 32.0
        tile = QRectF(r.left() + 8, r.center().y() - ts / 2, ts, ts)
        tint = QColor(color)
        tint.setAlphaF(0.16)
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(tile, ts * 0.28, ts * 0.28)
        m = ts * 0.24
        icons.paint(p, step.icon, color, tile.adjusted(m, m, -m, -m))

        # right side: step numbers in the flow, and a + to add it (on hover)
        right = r.right() - (5 if grid else 8)
        if hover and not view.locked and not grid:
            pr = view.plus_rect(option.rect)
            p.setPen(Qt.NoPen)
            p.setBrush(T.qc(T.GOLD, 0.22 if view.hover_plus else 0.10))
            p.drawEllipse(pr)
            icons.paint(p, "plus", T.GOLD_HI if view.hover_plus else T.GOLD, pr.adjusted(5, 5, -5, -5))
            right = pr.left() - 6
        nums = view.positions.get(key) or []
        if nums and grid:                 # no room for the step numbers: a gold dot on the icon (tooltip has them)
            p.setPen(QPen(QColor(T.SURFACE_2), 2))
            p.setBrush(QColor(T.GOLD))
            p.drawEllipse(QPointF(tile.right() - 1, tile.top() + 1), 4.5, 4.5)
        elif nums:
            text = " · ".join(str(n) for n in nums[:4]) + (" …" if len(nums) > 4 else "")
            bf = T.font(7.75, QFont.Bold)
            bw = QFontMetrics(bf).horizontalAdvance(text) + 14
            br = QRectF(right - bw, r.center().y() - 9, bw, 18)
            p.setPen(QPen(T.qc(T.GOLD, 0.30), 1))
            p.setBrush(T.qc(T.GOLD, 0.12))
            p.drawRoundedRect(br, 9, 9)
            p.setFont(bf)
            p.setPen(QColor(T.GOLD_HI))
            p.drawText(br, Qt.AlignCenter, text)
            right = br.left() - 6

        tx = tile.right() + (8 if grid else 10)
        tw = max(10.0, right - tx)
        tf = T.font(9.25 if grid else 9.75, QFont.DemiBold)
        df = T.font(8.5)
        tfm, dfm = QFontMetrics(tf), QFontMetrics(df)
        title_c = T.mix(T.TEXT, T.GOLD_HI, 0.35 if current else 0.0)
        if grid:                          # two columns: the title only (the description is in the tooltip)
            p.setFont(tf)
            p.setPen(title_c)
            p.drawText(QRectF(tx, r.top(), tw, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       tfm.elidedText(step.title, Qt.ElideRight, int(tw)))
        elif compact:                     # title and description on one line
            title = tfm.elidedText(step.title, Qt.ElideRight, int(tw))
            p.setFont(tf)
            p.setPen(title_c)
            p.drawText(QRectF(tx, r.top(), tw, r.height()), Qt.AlignVCenter | Qt.AlignLeft, title)
            used = tfm.horizontalAdvance(title) + 8
            if tw - used > 30:
                p.setFont(df)
                p.setPen(QColor(T.TEXT_MUTED))
                p.drawText(QRectF(tx + used, r.top(), tw - used, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                           dfm.elidedText(step.description, Qt.ElideRight, int(tw - used)))
        else:
            y = r.center().y() - (tfm.height() + dfm.height() + 1) / 2
            p.setFont(tf)
            p.setPen(title_c)
            p.drawText(QRectF(tx, y, tw, tfm.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       tfm.elidedText(step.title, Qt.ElideRight, int(tw)))
            p.setFont(df)
            p.setPen(QColor(T.TEXT_MUTED))
            p.drawText(QRectF(tx, y + tfm.height() + 1, tw, dfm.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       dfm.elidedText(step.description, Qt.ElideRight, int(tw)))
        p.restore()


class StepPalette(QListWidget):
    """The 8 functions. Click = show its settings, double-click or + = add to the flow, drag = into the flow.
    Dropping a flow row here removes it from the flow."""

    clicked = Signal(str)
    add_requested = Signal(str)
    remove_row = Signal(int)
    cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current = None
        self.positions = {}              # key -> [step numbers in the flow]
        self.density = "full"
        self.locked = False
        self.hover_row = -1
        self.hover_plus = False
        self.removing = False            # a flow row is dragged over the palette
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setItemDelegate(_PaletteDelegate(self))
        self.setStyleSheet("QListWidget { background: transparent; border: none; }"
                           "QListWidget::item, QListWidget::item:selected, QListWidget::item:hover "
                           "{ background: transparent; border: none; }")
        for step in STEPS:
            it = QListWidgetItem()
            it.setData(KEY, step.key)
            it.setToolTip(f"<b>{step.title}</b><br>{step.description}<br><span style='color:{T.TEXT_MUTED}'>"
                          f"{'Runs on each of its accounts' if step.per_account else 'Runs once, where it stands'}"
                          f"</span><br><i>Drag into the flow, double-click or press + to add.</i>")
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            self.addItem(it)
        self.itemDoubleClicked.connect(lambda it: self.locked or self.add_requested.emit(it.data(KEY)))

    def row_h(self):
        return {"full": FULL_H, "compact": COMPACT_H}.get(self.density, GRID_H)

    def inner_width(self):
        w = self.contentsRect().width()
        if self.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn:
            w -= self.verticalScrollBar().sizeHint().width()
        return w

    def content_height(self, density):
        if density == "grid":
            return math.ceil(self.count() / 2) * GRID_H + 2
        return self.count() * (FULL_H if density == "full" else COMPACT_H) + 2

    def set_density(self, density):
        if density != self.density:
            self.density = density
            grid = density == "grid"
            self.setFlow(QListView.LeftToRight if grid else QListView.TopToBottom)
            self.setWrapping(grid)
            self.setResizeMode(QListView.Adjust)
            self.doItemsLayout()
            self.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.doItemsLayout()

    def plus_rect(self, rect):
        r = QRectF(rect)
        return QRectF(r.right() - 34, r.center().y() - 12, 24, 24)

    def _on_plus(self, idx, pos):
        return (idx.isValid() and self.density != "grid" and not self.locked
                and self.plus_rect(self.visualRect(idx)).adjusted(-4, -4, 4, 4).contains(QPointF(pos)))

    def mimeTypes(self):
        return [MIME_STEP]

    def mimeData(self, items):
        return _mime(items[0].data(KEY)) if items else QMimeData()

    def startDrag(self, actions):
        if not self.locked:
            super().startDrag(Qt.CopyAction)

    # --- hover / clicks
    def _hover_at(self, pos):
        idx = self.indexAt(pos)
        row = idx.row() if idx.isValid() else -1
        plus = self._on_plus(idx, pos)
        if row != self.hover_row or plus != self.hover_plus:
            self.hover_row, self.hover_plus = row, plus
            self.viewport().update()
            self.viewport().setCursor(Qt.PointingHandCursor if row >= 0 else Qt.ArrowCursor)

    def viewportEvent(self, e):
        t = e.type()
        if t in (QEvent.MouseMove, QEvent.HoverMove):
            self._hover_at(e.position().toPoint())
        elif t == QEvent.Leave:
            self.hover_row, self.hover_plus = -1, False
            self.viewport().update()
        return super().viewportEvent(e)

    def mousePressEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        if not idx.isValid():
            self.clearSelection()
            self.cleared.emit()
            return
        if e.button() == Qt.LeftButton and self._on_plus(idx, e.position().toPoint()):
            self.add_requested.emit(idx.data(KEY))
            return
        super().mousePressEvent(e)
        if e.button() == Qt.LeftButton:
            self.clicked.emit(idx.data(KEY))

    def mouseDoubleClickEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        if e.button() == Qt.LeftButton and self._on_plus(idx, e.position().toPoint()):
            self.add_requested.emit(idx.data(KEY))     # second quick click on +: one more, like a single click
            return
        super().mouseDoubleClickEvent(e)

    # --- a flow row dropped here = removed from the flow
    def _removing(self, e):
        return not self.locked and e.mimeData().hasFormat(MIME_ROW) and isinstance(e.source(), FlowList)

    def dragEnterEvent(self, e):
        if self._removing(e):
            self.removing = True
            self.viewport().update()
            e.setDropAction(Qt.MoveAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._removing(e):
            e.setDropAction(Qt.MoveAction)
            e.accept()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self.removing = False
        self.viewport().update()
        e.accept()

    def dropEvent(self, e):
        self.removing = False
        self.viewport().update()
        if self._removing(e):
            self.remove_row.emit(_row_of(e.mimeData()))
            e.setDropAction(Qt.CopyAction)       # the flow list removes the row itself
            e.accept()
        else:
            e.ignore()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.removing:
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(self.viewport().rect()).adjusted(1, 1, -1, -1)
            p.setPen(QPen(T.qc(T.RED, 0.8), 1.5, Qt.DashLine))
            p.setBrush(T.qc("#0b0e1a", 0.82))
            p.drawRoundedRect(r, 10, 10)
            ic = QRectF(r.center().x() - 14, r.center().y() - 30, 28, 28)
            icons.paint(p, "trash", T.RED, ic)
            p.setFont(T.font(9.5, QFont.DemiBold))
            p.setPen(QColor(T.TEXT))
            p.drawText(QRectF(r.left(), ic.bottom() + 6, r.width(), 22), Qt.AlignCenter,
                       "Drop here to remove it from the flow")


# ----------------------------------------------------------------------------- flow list
class _FlowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(option.rect.width(), FLOW_H)

    def paint(self, p, option, index):
        view = self.parent()
        key = index.data(KEY)
        step = BY_KEY.get(key)
        if step is None:
            return
        color = STEP_COLORS.get(key, T.GOLD)
        row = index.row()
        hover = row == view.hover_row and not view.dragging
        current = key == view.current
        running = key == view.running_key
        pressed = bool(option.state & QStyle.State_Selected) and view.dragging
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if pressed:
            p.setOpacity(0.4)
        r = QRectF(option.rect).adjusted(0.5, 2.5, -0.5, -2.5)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, T.mix("#1b2037", "#232945", 0.9 if hover else 0.0))
        if current:
            p.fillPath(path, T.qc(T.GOLD, 0.08))
        border = (QColor(T.GOLD) if current else T.qc(T.GREEN, 0.7) if running
                  else T.mix(T.BORDER_STRONG, "#46507f", 0.8 if hover else 0.0))
        p.setPen(QPen(border, 1.3 if current or running else 1))
        p.drawPath(path)

        x = r.left() + 6
        icons.paint(p, "grip", T.mix(T.TEXT_DIM, T.TEXT_MUTED, 0.6 if hover else 0.0) if not view.locked
                    else T.qc(T.TEXT_DIM, 0.3), QRectF(x, r.center().y() - 7, 14, 14))
        x += 18
        nr = QRectF(x, r.center().y() - 11, 22, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(T.qc(T.GREEN, 0.9) if running else T.qc(T.GOLD, 0.16))
        p.drawEllipse(nr)
        p.setFont(T.font(8, QFont.Bold))
        p.setPen(QColor("#03230f" if running else T.GOLD_HI))
        p.drawText(nr, Qt.AlignCenter, str(row + 1))
        x = nr.right() + 9
        icons.paint(p, step.icon, color, QRectF(x, r.center().y() - 8, 16, 16))
        x += 24

        right = r.right() - 8
        if not view.locked:
            xr = view.x_rect(option.rect)
            if hover:
                if view.hover_x:
                    p.setPen(Qt.NoPen)
                    p.setBrush(T.qc(T.RED, 0.2))
                    p.drawEllipse(xr)
                icons.paint(p, "x", T.RED if view.hover_x else T.TEXT_MUTED, xr.adjusted(5, 5, -5, -5))
            else:
                icons.paint(p, "x", T.qc(T.TEXT_DIM, 0.55), xr.adjusted(5, 5, -5, -5))
            right = xr.left() - 4
        detail = view.details.get(key, "")
        df = T.font(8.25)
        dfm = QFontMetrics(df)
        if detail:
            dw = min(dfm.horizontalAdvance(detail.lstrip("!")) + 4, 120)
            p.setFont(df)
            p.setPen(QColor(T.AMBER if detail.startswith("!") else T.TEXT_DIM))
            p.drawText(QRectF(right - dw, r.top(), dw, r.height()), Qt.AlignVCenter | Qt.AlignRight,
                       dfm.elidedText(detail.lstrip("!"), Qt.ElideRight, int(dw)))
            right -= dw + 8
        tf = T.font(9.75, QFont.DemiBold)
        p.setFont(tf)
        p.setPen(T.mix(T.TEXT, T.GOLD_HI, 0.35 if current else 0.0))
        p.drawText(QRectF(x, r.top(), max(10.0, right - x), r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(tf).elidedText(step.title, Qt.ElideRight, int(max(10.0, right - x))))
        p.restore()


class FlowList(QListWidget):
    """The ordered steps. Accepts functions dragged from the palette; rows are dragged to reorder."""

    changed = Signal()
    clicked = Signal(str)
    cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current = None
        self.running_key = None
        self.details = {}
        self.locked = False
        self.hover_row = -1
        self.hover_x = False
        self.drop_row = None
        self.dragging = False
        self.flash = 0.0
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(False)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setAutoScroll(True)
        self.setAutoScrollMargin(28)
        self.setUniformItemSizes(True)
        self.setItemDelegate(_FlowDelegate(self))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(2 * FLOW_H + 8)
        self.setStyleSheet("QListWidget { background: transparent; border: none; }"
                           "QListWidget::item, QListWidget::item:selected, QListWidget::item:hover "
                           "{ background: transparent; border: none; }")

    def sizeHint(self):
        return QSize(300, max(3, self.count() + 1) * FLOW_H + 8)

    # --- content
    def keys(self):
        return [self.item(i).data(KEY) for i in range(self.count())]

    def set_keys(self, keys):
        self.clear()
        for k in keys:
            if k in BY_KEY:
                self.add_key(k)
        self.updateGeometry()

    def add_key(self, key, row=None):
        it = QListWidgetItem()
        it.setData(KEY, key)
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
        it.setToolTip(f"<b>{BY_KEY[key].title}</b><br>{BY_KEY[key].description}<br><i>Drag to move it; × or drag "
                      "it back onto Functions to remove it.</i>")
        if row is None or row >= self.count():
            self.addItem(it)
        else:
            self.insertItem(max(0, row), it)
        self.updateGeometry()
        return it

    def remove_row(self, row):
        if 0 <= row < self.count() and not self.locked:
            self.takeItem(row)
            self.hover_row = -1
            self.updateGeometry()
            self.viewport().update()
            self.changed.emit()

    def x_rect(self, rect):
        r = QRectF(rect)
        return QRectF(r.right() - 30, r.center().y() - 11, 22, 22)

    # --- drag & drop
    def mimeTypes(self):
        return [MIME_STEP, MIME_ROW]

    def mimeData(self, items):
        if not items:
            return QMimeData()
        return _mime(items[0].data(KEY), self.row(items[0]))

    def startDrag(self, actions):
        if self.locked:
            return
        self.dragging = True
        try:
            super().startDrag(Qt.MoveAction | Qt.CopyAction)     # Copy: drops tell Qt not to delete the row
        finally:
            self.dragging = False
            self.drop_row = None
            self.viewport().update()

    def _drop_at(self, pos):
        idx = self.indexAt(pos)
        if not idx.isValid():
            if self.count() and pos.y() < self.visualRect(self.model().index(0, 0)).top():
                return 0
            return self.count()
        rect = self.visualRect(idx)
        return idx.row() + (1 if pos.y() > rect.center().y() else 0)

    def _accepts(self, e):
        return not self.locked and e.mimeData().hasFormat(MIME_STEP)

    def dragEnterEvent(self, e):
        super().dragEnterEvent(e)
        if self._accepts(e):
            self.drop_row = self._drop_at(e.position().toPoint())
            e.setDropAction(Qt.MoveAction if e.source() is self else Qt.CopyAction)
            e.accept()
            self.viewport().update()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        super().dragMoveEvent(e)                 # auto-scrolls near the edges
        if self._accepts(e):
            row = self._drop_at(e.position().toPoint())
            if row != self.drop_row:
                self.drop_row = row
            e.setDropAction(Qt.MoveAction if e.source() is self else Qt.CopyAction)
            e.accept()
            self.viewport().update()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        super().dragLeaveEvent(e)
        self.drop_row = None
        self.viewport().update()

    def dropEvent(self, e):
        self.stopAutoScroll()
        self.setState(QAbstractItemView.NoState)
        row = self._drop_at(e.position().toPoint())
        self.drop_row = None
        self.viewport().update()
        if not self._accepts(e):
            e.ignore()
            return
        self.drop(e.mimeData(), row, internal=e.source() is self)
        e.setDropAction(Qt.CopyAction)      # we moved it ourselves: Qt must not remove the source row
        e.accept()

    def drop(self, md, row, internal):
        """A drop at row: a row of this list moves there, a function from the palette is inserted there."""
        if self.locked:
            return
        if internal and md.hasFormat(MIME_ROW):
            src = _row_of(md)
            if not 0 <= src < self.count():
                return
            dst = row - 1 if row > src else row
            if dst != src:
                it = self.takeItem(src)
                self.insertItem(dst, it)
            self.setCurrentRow(dst)
        else:
            key = _key_of(md)
            if key not in BY_KEY:
                return
            self.add_key(key, row)
            self.setCurrentRow(min(row, self.count() - 1))
        self.changed.emit()

    # --- hover / clicks
    def _hover_at(self, pos):
        idx = self.indexAt(pos)
        row = idx.row() if idx.isValid() else -1
        on_x = row >= 0 and not self.locked and self.x_rect(self.visualRect(idx)).adjusted(-3, -3, 3, 3).contains(
            QPointF(pos))
        if row != self.hover_row or on_x != self.hover_x:
            self.hover_row, self.hover_x = row, on_x
            self.viewport().update()
            self.viewport().setCursor(Qt.PointingHandCursor if on_x else Qt.OpenHandCursor if row >= 0 and
                                      not self.locked else Qt.PointingHandCursor if row >= 0 else Qt.ArrowCursor)

    def viewportEvent(self, e):
        t = e.type()
        if t in (QEvent.MouseMove, QEvent.HoverMove):
            self._hover_at(e.position().toPoint())
        elif t == QEvent.Leave:
            self.hover_row, self.hover_x = -1, False
            self.viewport().update()
        return super().viewportEvent(e)

    def mousePressEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        if not idx.isValid():
            self.clearSelection()
            self.cleared.emit()
            return
        if (e.button() == Qt.LeftButton and not self.locked
                and self.x_rect(self.visualRect(idx)).adjusted(-3, -3, 3, 3).contains(e.position())):
            self.remove_row(idx.row())
            return
        super().mousePressEvent(e)
        if e.button() == Qt.LeftButton:
            self.clicked.emit(idx.data(KEY))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.currentRow() >= 0:
            self.remove_row(self.currentRow())
            return
        super().keyPressEvent(e)

    # --- painting: empty state, drop marker
    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        vr = QRectF(self.viewport().rect()).adjusted(1, 1, -1, -1)
        dragging_in = self.drop_row is not None
        if self.count() == 0:
            pen = QPen(T.qc(T.GOLD, 0.85) if dragging_in else T.qc(T.mix(T.BORDER_STRONG, T.GOLD, self.flash), 1),
                       1.4, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(T.qc(T.GOLD, 0.06 if dragging_in else 0.06 * self.flash))
            p.drawRoundedRect(vr, 12, 12)
            ic = QRectF(vr.center().x() - 13, vr.center().y() - 30, 26, 26)
            icons.paint(p, "flow", T.GOLD if dragging_in else T.TEXT_DIM, ic)
            p.setFont(T.font(9.5, QFont.DemiBold))
            p.setPen(QColor(T.TEXT if dragging_in else T.TEXT_MUTED))
            p.drawText(QRectF(vr.left() + 12, ic.bottom() + 6, vr.width() - 24, 40),
                       Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       "Drop it here" if dragging_in else "Drag functions here (or double-click one)")
            return
        if dragging_in:
            if self.drop_row < self.count():
                y = self.visualRect(self.model().index(self.drop_row, 0)).top() + 0.5
            else:
                y = self.visualRect(self.model().index(self.count() - 1, 0)).bottom() + 1.5
            y = max(2.0, min(vr.bottom() - 1, y))
            p.setPen(QPen(QColor(T.GOLD), 2.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(vr.left() + 10, y), QPointF(vr.right() - 10, y))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.GOLD))
            p.drawEllipse(QPointF(vr.left() + 7, y), 3.5, 3.5)


# ----------------------------------------------------------------------------- panel
class FlowPanel(QWidget):
    """Functions palette + Flow box + presets (left column of the window)."""

    changed = Signal()
    step_clicked = Signal(str)          # a function was clicked (palette or flow)
    cleared = Signal()                  # click on an empty spot: forget the shown function
    preset_chosen = Signal(dict)        # {step: roles}: a preset sets its steps' accounts

    def __init__(self, parent=None):
        super().__init__(parent)
        self.locked = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.palette_card = Card("Functions", icon="blocks", padding=14, spacing=8)
        self.palette_card.title_label.setToolTip("Drag one into the flow, double-click it or press its +")
        self.palette_hint = label("drag into the flow", "small")
        self.palette_hint.setStyleSheet(f"color: {T.TEXT_DIM};")
        self.palette_card.add_action(self.palette_hint)
        self.palette = StepPalette()
        self.palette.setFixedHeight(self.palette.content_height("full"))
        self.palette_card.add(self.palette)
        lay.addWidget(self.palette_card)

        self.flow_card = Card("Flow", icon="flow", padding=14, spacing=8)
        self.flow_card.title_label.setToolTip("Runs from top to bottom. Steps that work per account go account by "
                                              "account (account 1 does all of them, then account 2, ...); Donate "
                                              "and Loot current run once where they stand.")
        self.count_pill = Pill("", T.TEXT_MUTED)
        self.clear_btn = Button("Clear", "trash", "ghost", "sm")
        self.clear_btn.setToolTip("Remove every step from the flow")
        self.flow_card.add_action(self.count_pill)
        self.flow_card.add_action(self.clear_btn)
        self.flow = FlowList()
        self.flow_card.add(self.flow, 1)
        presets = QWidget()
        pl = FlowLayout(presets, 6, 6)
        self.presets_label = label("PRESETS", "caption")
        self.presets_label.setFixedHeight(30)
        pl.addWidget(self.presets_label)
        self.preset_btns = []
        for title, keys, roles in PRESETS:
            b = Button(title, None, "secondary", "sm")
            b.setToolTip("Replace the flow with:<br><b>" + " → ".join(BY_KEY[k].title for k in keys if k in BY_KEY)
                         + "</b><br>and set each step's accounts from the roles on the Accounts list")
            b.clicked.connect(lambda _=False, k=keys, r=roles: self._preset(k, r))
            pl.addWidget(b)
            self.preset_btns.append((b, list(keys)))
        self.flow_card.add(presets)
        lay.addWidget(self.flow_card, 1)

        self.palette.clicked.connect(self._clicked)
        self.palette.add_requested.connect(self.append)
        self.palette.remove_row.connect(self.flow.remove_row)
        self.palette.cleared.connect(self._cleared)
        self.flow.clicked.connect(self._clicked)
        self.flow.cleared.connect(self._cleared)
        self.flow.changed.connect(self._flow_changed)
        self.clear_btn.clicked.connect(self._clear)
        self._flash_t = None
        self._sync()

    # --- api
    def keys(self):
        return self.flow.keys()

    def _preset(self, keys, roles):
        if self.locked:
            return
        self.preset_chosen.emit(roles)                 # the window sets the steps' accounts first
        self.set_flow(keys, emit=True)

    def set_flow(self, keys, emit=False):
        if self.locked:
            return
        self.flow.set_keys(keys)
        self._sync()
        if emit:
            self.changed.emit()

    def append(self, key):
        if self.locked or key not in BY_KEY:
            return
        self.flow.add_key(key)
        self.flow.setCurrentRow(self.flow.count() - 1)
        self.flow.scrollToBottom()
        self._flow_changed()

    def set_current(self, key):
        self.palette.current = key
        self.flow.current = key
        if key is None:
            self.palette.clearSelection()
            self.flow.clearSelection()
        self.palette.viewport().update()
        self.flow.viewport().update()

    def set_details(self, details):
        if details != self.flow.details:
            self.flow.details = dict(details)
            self.flow.viewport().update()

    def set_running_key(self, key):
        if key != self.flow.running_key:
            self.flow.running_key = key
            self.flow.viewport().update()

    def set_running(self, running):
        """Locked while the bot runs: the steps can still be clicked to see their settings."""
        self.locked = running
        self.palette.locked = running
        self.flow.locked = running
        self.flow.setDragDropMode(QAbstractItemView.NoDragDrop if running else QAbstractItemView.DragDrop)
        self.palette.setDragDropMode(QAbstractItemView.NoDragDrop if running else QAbstractItemView.DragOnly)
        self.palette.setAcceptDrops(not running)
        self.palette.viewport().setAcceptDrops(not running)
        self.flow.setAcceptDrops(not running)
        self.flow.viewport().setAcceptDrops(not running)
        if not running:
            self.flow.running_key = None
        for b, _ in self.preset_btns:
            b.setEnabled(not running)
        self._sync()

    def flash_flow(self):
        """Draw attention to the (empty) flow box."""
        if self._flash_t is None:
            self._flash_t = Tween(self, ms=500, on_change=self._flash_step)
            self._flash_t.finished.connect(lambda: self._flash_t.value > 0.5 and self._flash_t.to(0.0))
        self._flash_t.to(1.0)

    def _flash_step(self):
        self.flow.flash = self._flash_t.value
        self.flow.viewport().update()

    # --- settings io
    def load(self, settings, accounts):
        self.flow.blockSignals(True)
        self.flow.set_keys([k for k in settings.get("flow", []) if k in BY_KEY])
        self.flow.blockSignals(False)
        self._sync()

    def apply(self, settings, accounts):
        settings["flow"] = self.keys()
        settings["mode"] = "flow"

    # --- internals
    def _clicked(self, key):
        self.set_current(key)
        self.step_clicked.emit(key)

    def _cleared(self):
        self.set_current(None)
        self.cleared.emit()

    def _clear(self):
        if not self.flow.count() or self.locked:
            return
        if self.flow.count() > 1:
            if not T.ask(self, "Clear the flow", "Remove all steps from the flow?"):
                return
        self.set_flow([], emit=True)

    def _flow_changed(self):
        self._sync()
        self.changed.emit()

    def _sync(self):
        keys = self.keys()
        pos = {}
        for i, k in enumerate(keys):
            pos.setdefault(k, []).append(i + 1)
        self.palette.positions = pos
        self.palette.viewport().update()
        n = len(keys)
        self.count_pill.set(f"{n} step{'s' if n != 1 else ''}" if n else "Empty", T.GOLD if n else T.TEXT_DIM)
        self.clear_btn.setEnabled(bool(n) and not self.locked)
        for b, k in self.preset_btns:
            b.set_variant("outline" if k == keys else "secondary")
        self.flow.updateGeometry()
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        """Pick the roomiest palette that leaves the flow box room for its steps (3 to 6 rows): title over
        description, title and description on one line, or two columns of titles. The flow box scrolls when
        it has more steps than room; the palette scrolls only when even the two columns do not fit."""
        w = self.palette_card.width()
        if w <= 0 or self.height() <= 0:
            return

        def chrome(card, inner_h):
            lay = card.layout()
            total = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else card.sizeHint().height()
            return total - inner_h

        lists = (self.height() - chrome(self.palette_card, self.palette.minimumHeight())
                 - chrome(self.flow_card, self.flow.sizeHint().height()) - self.layout().spacing())
        need = max(3, min(self.flow.count(), 6)) * FLOW_H + 8
        density = next((d for d in DENSITIES if self.palette.content_height(d) <= lists - need), "grid")
        full = self.palette.content_height(density)
        h = max(GRID_H + 2, min(full, lists - self.flow.minimumHeight()))
        policy = Qt.ScrollBarAlwaysOn if h < full else Qt.ScrollBarAlwaysOff
        changed = density != self.palette.density or policy != self.palette.verticalScrollBarPolicy()
        self.palette.setVerticalScrollBarPolicy(policy)
        self.palette.set_density(density)
        if self.palette.minimumHeight() != h or self.palette.maximumHeight() != h:
            self.palette.setFixedHeight(h)
        if changed:
            self.palette.doItemsLayout()

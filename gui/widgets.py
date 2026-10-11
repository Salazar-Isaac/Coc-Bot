"""Reusable widgets: screenshot box-selection dialog, number spin boxes."""

import numpy as np
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
                               QVBoxLayout, QWidget)

from gui import theme as T
from gui.components import Button, label


def to_pixmap(frame_bgr):
    frame = np.ascontiguousarray(frame_bgr)
    h, w = frame.shape[:2]
    img = QImage(frame.data, w, h, frame.strides[0], QImage.Format_BGR888)
    return QPixmap.fromImage(img.copy())


class ImageCanvas(QWidget):
    """Shows a screenshot scaled to fit; drag with the mouse to select a box."""

    changed = Signal()

    def __init__(self, frame_bgr, parent=None):
        super().__init__(parent)
        self.pixmap = to_pixmap(frame_bgr)
        self.img_w, self.img_h = frame_bgr.shape[1], frame_bgr.shape[0]
        self._start = None
        self._rect = None          # in image coordinates
        self.marks = []            # [(QRect in image coords, QColor, label)]
        self.setMinimumSize(960, 540)
        self.setCursor(Qt.CrossCursor)

    def sizeHint(self):
        return QSize(1280, 720)

    # image <-> widget mapping (keeps aspect ratio)
    def _geom(self):
        s = min(self.width() / self.img_w, self.height() / self.img_h)
        ox = (self.width() - self.img_w * s) / 2
        oy = (self.height() - self.img_h * s) / 2
        return s, ox, oy

    def _to_img(self, p):
        s, ox, oy = self._geom()
        x = int(round((p.x() - ox) / s))
        y = int(round((p.y() - oy) / s))
        return QPoint(max(0, min(self.img_w - 1, x)), max(0, min(self.img_h - 1, y)))

    def _to_widget(self, r):
        s, ox, oy = self._geom()
        return QRect(int(ox + r.x() * s), int(oy + r.y() * s), int(r.width() * s), int(r.height() * s))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(T.SIDEBAR))
        s, ox, oy = self._geom()
        target = QRectF(ox, oy, self.img_w * s, self.img_h * s)
        clip = QPainterPath()
        clip.addRoundedRect(target, 8, 8)
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(target.toRect(), self.pixmap)
        if self._rect is not None:
            dim = QPainterPath()
            dim.addRect(target)
            hole = QPainterPath()
            hole.addRect(QRectF(self._to_widget(self._rect)))
            p.fillPath(dim.subtracted(hole), QColor(0, 0, 0, 110))
        p.restore()
        for r, color, text in self.marks:
            p.setPen(QPen(color, 2))
            wr = self._to_widget(r)
            p.drawRect(wr)
            if text:
                p.drawText(wr.topLeft() + QPoint(2, -4), text)
        if self._rect is not None:
            wr = self._to_widget(self._rect)
            p.setPen(QPen(QColor(T.GOLD), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(wr)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.GOLD))
            for c in (wr.topLeft(), wr.topRight(), wr.bottomLeft(), wr.bottomRight()):
                p.drawEllipse(c, 4, 4)

    def mousePressEvent(self, e):
        self._start = self._to_img(e.position().toPoint())
        self._rect = QRect(self._start, self._start)
        self.update()

    def mouseMoveEvent(self, e):
        if self._start is not None:
            self._rect = QRect(self._start, self._to_img(e.position().toPoint())).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        self.mouseMoveEvent(e)
        self._start = None
        self.changed.emit()

    def selection(self):
        if self._rect is None or self._rect.width() < 4 or self._rect.height() < 4:
            return None
        r = self._rect
        return [r.x(), r.y(), r.width(), r.height()]

    def set_selection(self, box):
        self._rect = QRect(*box) if box else None
        self.update()


class CropDialog(QDialog):
    """Ask the user to drag a box on a screenshot. Optionally asks for a text value too."""

    def __init__(self, frame, title, hint, parent=None, ask_value=None, box=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.canvas = ImageCanvas(frame, self)
        if box:
            self.canvas.set_selection(box)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        head = QLabel(title)
        head.setFont(T.font(13, QFont.DemiBold, display=True))
        lay.addWidget(head)
        tip = label(f"Drag a box around: <b style='color:{T.GOLD_HI}'>{hint}</b>", "muted", wrap=True)
        tip.setTextFormat(Qt.RichText)
        lay.addWidget(tip)
        lay.addWidget(self.canvas, 1)
        self.value = None
        if ask_value:
            row = QHBoxLayout()
            row.addWidget(label(ask_value))
            self.value = QLineEdit()
            row.addWidget(self.value, 1)
            lay.addLayout(row)
        bottom = QHBoxLayout()
        self.info = label("", "muted")
        self.info.setFont(T.font(9, mono=True))
        bottom.addWidget(self.info, 1)
        cancel = Button("Cancel", variant="secondary")
        save = Button("Save", "check", variant="primary")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept)
        bottom.addWidget(cancel)
        bottom.addWidget(save)
        lay.addLayout(bottom)
        self.canvas.changed.connect(self._show_box)
        self.resize(1320, 880)
        self._show_box()

    def showEvent(self, e):
        T.style_window(self, T.SURFACE)
        super().showEvent(e)

    def _show_box(self):
        b = self.canvas.selection()
        self.info.setText(f"x={b[0]}  y={b[1]}  w={b[2]}  h={b[3]}" if b else "No box yet")
        self.info.setStyleSheet("")

    def _accept(self):
        if self.canvas.selection() is None:
            self.info.setText("Drag a box first.")
            self.info.setStyleSheet(f"color: {T.AMBER};")
            return
        if self.value is not None and not self.value.text().strip():
            self.info.setText("Type the value too.")
            self.info.setStyleSheet(f"color: {T.AMBER};")
            return
        self.accept()

    def result_box(self):
        return self.canvas.selection()

    def result_value(self):
        return self.value.text().strip() if self.value is not None else None


class Spin(QSpinBox):
    """Spin box that only reacts to the mouse wheel when focused (scrolling a page never changes values).
    While it shows its special text (e.g. "Any", "No limit", "TH table") the text is dimmed."""

    def __init__(self, minimum=0, maximum=999, suffix="", special="", parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(34)
        self.setRange(minimum, maximum)
        if suffix:
            self.setSuffix(suffix)
        if special:
            self.setSpecialValueText(special)
        self.valueChanged.connect(self._dim)
        self._dim()

    def setSpecialValueText(self, text):
        super().setSpecialValueText(text)
        self._dim()

    def _dim(self, *_):
        dim = bool(self.specialValueText()) and self.value() == self.minimum()
        if self.property("dim") != dim:
            self.setProperty("dim", dim)
            self.style().unpolish(self)
            self.style().polish(self)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class DoubleSpin(QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(34)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class Combo(QComboBox):
    """Combo box that ignores the wheel unless focused; items may carry a tooltip."""

    def __init__(self, items=(), editable=False, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setEditable(editable)
        for it in items:
            data, text = it[0], it[1]
            self.addItem(text, data)
            if len(it) > 2:
                self.setItemData(self.count() - 1, it[2], Qt.ToolTipRole)

    def select(self, data):
        self.setCurrentIndex(max(0, self.findData(data)))

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class BigSpin(Spin):
    """Integer spin box for resource amounts, shown with thousands separators."""

    def __init__(self, maximum=200_000_000, step=100_000, parent=None):
        super().__init__(0, maximum, parent=parent)
        self.setSingleStep(step)
        self.setGroupSeparatorShown(True)
        self.setMinimumWidth(140)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

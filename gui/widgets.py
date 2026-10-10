"""Reusable widgets: screenshot box-selection dialog, number spin boxes."""

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
                               QVBoxLayout, QWidget)


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
        p.fillRect(self.rect(), QColor(20, 20, 24))
        s, ox, oy = self._geom()
        p.drawPixmap(QRect(int(ox), int(oy), int(self.img_w * s), int(self.img_h * s)), self.pixmap)
        for r, color, label in self.marks:
            p.setPen(QPen(color, 2))
            wr = self._to_widget(r)
            p.drawRect(wr)
            if label:
                p.drawText(wr.topLeft() + QPoint(2, -4), label)
        if self._rect is not None:
            p.setPen(QPen(QColor(0, 230, 120), 2, Qt.DashLine))
            p.drawRect(self._to_widget(self._rect))

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
        tip = QLabel(f"Drag a box around: <b>{hint}</b>")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addWidget(self.canvas, 1)
        self.value = None
        if ask_value:
            row = QHBoxLayout()
            row.addWidget(QLabel(ask_value))
            self.value = QLineEdit()
            row.addWidget(self.value, 1)
            lay.addLayout(row)
        self.info = QLabel("")
        lay.addWidget(self.info)
        self.canvas.changed.connect(self._show_box)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.resize(1320, 860)

    def _show_box(self):
        b = self.canvas.selection()
        self.info.setText(f"Box: x={b[0]} y={b[1]} w={b[2]} h={b[3]}" if b else "")

    def _accept(self):
        if self.canvas.selection() is None:
            self.info.setText("Drag a box first.")
            return
        if self.value is not None and not self.value.text().strip():
            self.info.setText("Type the value too.")
            return
        self.accept()

    def result_box(self):
        return self.canvas.selection()

    def result_value(self):
        return self.value.text().strip() if self.value is not None else None


class BigSpin(QSpinBox):
    """Integer spin box for resource amounts, shown with thousands separators."""

    def __init__(self, maximum=200_000_000, step=100_000, parent=None):
        super().__init__(parent)
        self.setRange(0, maximum)
        self.setSingleStep(step)
        self.setGroupSeparatorShown(True)
        self.setMinimumWidth(130)

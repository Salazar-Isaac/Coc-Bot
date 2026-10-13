"""The app logo and the animated page stack (the main screen <-> Templates / Full log)."""

from PySide6.QtCore import QEasingCurve, QPointF, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStackedWidget, QWidget

from gui import theme as T


class Logo(QWidget):
    """The app logo (shield + bolt), crisp at any scale."""

    def __init__(self, size=38, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        dpr = self.devicePixelRatioF()
        p.drawPixmap(0, 0, T.logo_pixmap(self.width(), dpr))


class AnimatedStack(QStackedWidget):
    """QStackedWidget whose page changes cross-fade with a short upward slide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._overlay = _Transition(self)
        self._overlay.hide()

    def slide_to(self, index):
        """Switch page: the new page fades in from the background while gliding up a few pixels.
        Only the new page is grabbed once; the frames are cheap pixmap draws."""
        if index == self.currentIndex() or not (0 <= index < self.count()):
            return
        animate = self.isVisible() and self.width() > 0
        self.setCurrentIndex(index)
        if animate:
            self._overlay.run(self.currentWidget().grab())

    def resizeEvent(self, e):
        self._overlay.setGeometry(self.rect())
        super().resizeEvent(e)


class _Transition(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.new = None
        self.t = 1.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(280)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self._done)

    def run(self, new):
        self.new = new
        self.t = 0.0
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.start()

    def _step(self, v):
        self.t = float(v)
        self.update()

    def _done(self):
        self.hide()
        self.new = None

    def paintEvent(self, _):
        if self.new is None:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.BG))
        t = self.t
        p.setOpacity(min(1.0, 0.15 + t * 1.2))
        p.drawPixmap(QPointF(0, 16 * (1 - t)), self.new)

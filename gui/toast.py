"""Toast notifications that slide in at the top-right of the window and dismiss themselves."""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gui import icons
from gui import theme as T
from gui.components import Button, IconButton

KINDS = {
    "info": ("info", T.BLUE),
    "success": ("check-circle", T.GREEN),
    "warning": ("warning", T.AMBER),
    "error": ("x-circle", T.RED),
}

SHADOW = 12      # room around the card for the painted soft shadow
WIDTH = 372


class Toast(QWidget):
    def __init__(self, manager, kind, title, message="", timeout=4500, action=None):
        super().__init__(manager.host)
        self.manager = manager
        self.kind = kind
        self.timeout = timeout
        self.closing = False
        self.target = None
        self._move = None
        self._fade = None
        icon, self.color = KINDS.get(kind, KINDS["info"])
        self.color = QColor(self.color)
        self.setAttribute(Qt.WA_StyledBackground, False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(SHADOW + 16, SHADOW + 12, SHADOW + 8, SHADOW + 14)
        lay.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon, self.color.name(), 20))
        ic.setFixedSize(22, 22)
        lay.addWidget(ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setFont(T.font(10, QFont.DemiBold))
        t.setWordWrap(True)
        col.addWidget(t)
        if message:
            m = QLabel(message)
            m.setWordWrap(True)
            m.setProperty("role", "rowDesc")
            m.setTextInteractionFlags(Qt.TextSelectableByMouse)
            col.addWidget(m)
        if action:
            text, fn = action
            b = Button(text, variant="outline" if kind != "warning" else "primary", size="sm")
            b.clicked.connect(fn)
            b.clicked.connect(self.dismiss)
            row = QHBoxLayout()
            row.setContentsMargins(0, 6, 0, 0)
            row.addWidget(b)
            row.addStretch(1)
            col.addLayout(row)
        lay.addLayout(col, 1)
        close = IconButton("x", "Dismiss", size="sm")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.dismiss)
        lay.addWidget(close, 0, Qt.AlignTop)

        self.setFixedWidth(WIDTH + 2 * SHADOW)
        lay.activate()
        self.setFixedHeight(max(lay.totalHeightForWidth(WIDTH + 2 * SHADOW), 2 * SHADOW + 48))

        self.opacity = QGraphicsOpacityEffect(self)
        self.opacity.setOpacity(0.0)
        self.setGraphicsEffect(self.opacity)

        self._life = QVariantAnimation(self)       # countdown line at the bottom
        self._life.setStartValue(1.0)
        self._life.setEndValue(0.0)
        self._life.valueChanged.connect(lambda _v: self.update())
        self._life.finished.connect(self.dismiss)
        if timeout:
            self._life.setDuration(timeout)

    # --- motion
    def move_to(self, target, ms=260, curve=QEasingCurve.OutCubic):
        self.target = target
        if self._move is not None:
            self._move.stop()
        self._move = QPropertyAnimation(self, b"pos", self)
        self._move.setDuration(ms)
        self._move.setEndValue(target)
        self._move.setEasingCurve(curve)
        self._move.start()

    def fade_to(self, value, ms=220, done=None):
        if self._fade is not None:
            self._fade.stop()
        self._fade = QPropertyAnimation(self.opacity, b"opacity", self)
        self._fade.setDuration(ms)
        self._fade.setEndValue(value)
        if done:
            self._fade.finished.connect(done)
        self._fade.start()

    # --- lifetime
    def start(self):
        if self.timeout:
            self._life.start()

    def enterEvent(self, e):
        if self._life.state() == QVariantAnimation.Running:
            self._life.pause()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._life.state() == QVariantAnimation.Paused:
            self._life.resume()
        super().leaveEvent(e)

    def dismiss(self):
        if self.closing:
            return
        self.closing = True
        self._life.stop()
        self.move_to(self.pos() + QPoint(44, 0), 220, QEasingCurve.InCubic)
        self.fade_to(0.0, 200, self._gone)
        self.manager._closing(self)

    def _gone(self):
        self.hide()
        self.deleteLater()

    # --- painting: soft shadow, card, accent strip, countdown
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(self.rect()).adjusted(SHADOW, SHADOW - 2, -SHADOW, -SHADOW - 2)
        p.setPen(Qt.NoPen)
        for i in range(SHADOW, 0, -2):
            p.setBrush(QColor(0, 0, 0, int(26 * (1 - i / SHADOW) ** 1.6) + 2))
            p.drawRoundedRect(card.adjusted(-i, -i + 4, i, i + 4), 12 + i, 12 + i)
        path = QPainterPath()
        path.addRoundedRect(card, 12, 12)
        p.fillPath(path, QColor("#1f2440"))
        tint = QColor(self.color)
        tint.setAlphaF(0.07)
        p.fillPath(path, tint)
        p.setPen(QColor(T.BORDER_STRONG))
        p.drawPath(path)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(card.left(), card.top(), 4, card.height()), self.color)
        if self.timeout:
            v = float(self._life.currentValue() or 0.0) if self._life.state() != QVariantAnimation.Stopped else 1.0
            lc = QColor(self.color)
            lc.setAlphaF(0.55)
            p.fillRect(QRectF(card.left(), card.bottom() - 2.5, card.width() * v, 2.5), lc)
        p.restore()


class ToastManager(QObject):
    """Stacks toasts at the top-right of `host` and animates them in and out."""

    MARGIN = 14

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.toasts = []
        host.installEventFilter(self)

    def show(self, kind, title, message="", timeout=4500, action=None):
        t = Toast(self, kind, title, message, timeout, action)
        self.toasts.insert(0, t)
        t.move(self._target(0) + QPoint(48, 0))
        t.show()
        t.raise_()
        self._layout()
        t.fade_to(1.0, 240)
        t.start()
        if len(self.toasts) > 4:
            self.toasts[-1].dismiss()
        return t

    def clear(self, kind=None):
        for t in list(self.toasts):
            if kind is None or t.kind == kind:
                t.dismiss()

    def _closing(self, t):
        if t in self.toasts:
            self.toasts.remove(t)
        self._layout()

    def _target(self, i):
        x = self.host.width() - (WIDTH + 2 * SHADOW) - self.MARGIN + SHADOW
        y = self.MARGIN - SHADOW + 4
        for t in self.toasts[:i]:
            y += t.height() - 2 * SHADOW + 10
        return QPoint(x, y)

    def _layout(self):
        for i, t in enumerate(self.toasts):
            target = self._target(i)
            if t.target != target:
                t.move_to(target, 320 if t.target is None else 260)
            t.raise_()

    def eventFilter(self, obj, e):
        if obj is self.host and e.type() == QEvent.Resize:
            for i, t in enumerate(self.toasts):
                if t._move is not None:
                    t._move.stop()
                t.target = self._target(i)
                t.move(t.target)
        return False

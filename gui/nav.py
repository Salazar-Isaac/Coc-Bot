"""Sidebar navigation with a sliding selection indicator, the run-status chip and the animated page stack."""

import time

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from gui import icons
from gui import theme as T
from gui.components import PulseDot, Tween, label, section


class NavBar(QWidget):
    """Vertical list of pages. The highlighted pill slides to the selected item; items fade on hover."""

    currentChanged = Signal(int)
    ITEM_H, GAP = 42, 4

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = list(items)               # [(title, icon)]
        self.badges = {}                        # index -> (text, color)
        self._index = 0
        self._y = Tween(self, ms=280, curve=QEasingCurve.OutCubic)
        self._hover = [Tween(self, ms=160) for _ in self.items]
        self._hover_i = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(len(self.items) * (self.ITEM_H + self.GAP))

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, i, animate=True):
        if 0 <= i < len(self.items) and i != self._index:
            self._index = i
            self._y.to(i, animate and self.isVisible())
            self.update()

    def set_badge(self, i, text, color=T.RED):
        if text:
            self.badges[i] = (str(text), color)
        else:
            self.badges.pop(i, None)
        self.update()

    def _item_at(self, y):
        i = int(y // (self.ITEM_H + self.GAP))
        return i if 0 <= i < len(self.items) else -1

    def mouseMoveEvent(self, e):
        i = self._item_at(e.position().y())
        if i != self._hover_i:
            if 0 <= self._hover_i < len(self._hover):
                self._hover[self._hover_i].to(0.0)
            if i >= 0:
                self._hover[i].to(1.0)
            self._hover_i = i

    def leaveEvent(self, e):
        if 0 <= self._hover_i < len(self._hover):
            self._hover[self._hover_i].to(0.0)
        self._hover_i = -1
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            i = self._item_at(e.position().y())
            if i >= 0 and i != self._index:
                self.setCurrentIndex(i)
                self.currentChanged.emit(i)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w = self.width()
        step = self.ITEM_H + self.GAP
        # sliding selection pill
        sel = QRectF(0, self._y.value * step, w, self.ITEM_H)
        g = QLinearGradient(sel.topLeft(), sel.topRight())
        g.setColorAt(0, T.qc(T.GOLD, 0.17))
        g.setColorAt(1, T.qc(T.GOLD, 0.03))
        p.setPen(QPen(T.qc(T.GOLD, 0.16), 1))
        p.setBrush(g)
        p.drawRoundedRect(sel.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T.GOLD))
        p.drawRoundedRect(QRectF(sel.left() + 1, sel.center().y() - 9, 3.5, 18), 1.75, 1.75)

        f = T.font(10, QFont.Medium)
        fb = T.font(10, QFont.DemiBold)
        for i, (title, icon) in enumerate(self.items):
            r = QRectF(0, i * step, w, self.ITEM_H)
            h = self._hover[i].value
            near = max(0.0, 1.0 - abs(self._y.value - i))
            if h > 0 and i != self._index:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, int(12 * h)))
                p.drawRoundedRect(r, 10, 10)
            ic = T.mix(T.mix(T.TEXT_DIM, T.TEXT_MUTED, h), T.GOLD_HI, near)
            icons.paint(p, icon, ic, QRectF(r.left() + 16, r.center().y() - 9, 18, 18))
            p.setFont(fb if i == self._index else f)
            p.setPen(T.mix(T.mix(T.TEXT_MUTED, T.TEXT, h), T.TEXT, near))
            p.drawText(QRectF(r.left() + 46, r.top(), w - 90, r.height()), Qt.AlignVCenter | Qt.AlignLeft, title)
            if i in self.badges:
                text, color = self.badges[i]
                bf = T.font(7.5, QFont.Bold)
                bw = max(20, QFontMetrics(bf).horizontalAdvance(text) + 12)
                br = QRectF(r.right() - bw - 12, r.center().y() - 9, bw, 18)
                p.setPen(Qt.NoPen)
                p.setBrush(T.qc(color, 0.18))
                p.drawRoundedRect(br, 9, 9)
                p.setFont(bf)
                p.setPen(QColor(color))
                p.drawText(br, Qt.AlignCenter, text)


class StatusChip(QFrame):
    """Run state at the bottom of the sidebar: Idle / Running (pulsing) / Paused / Waiting for you."""

    STATES = {
        "idle": ("Idle", T.TEXT_DIM, False),
        "running": ("Running", T.GREEN, True),
        "paused": ("Paused", T.AMBER, False),
        "waiting": ("Waiting for you", T.AMBER, True),
        "busy": ("Working", T.BLUE, True),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        self.dot = PulseDot()
        lay.addWidget(self.dot, 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = label("Idle")
        self.title.setFont(T.font(10, QFont.DemiBold))
        self.sub = label("Ready", "small")
        self.sub.setMinimumWidth(10)
        self.time = label("", "small")
        self.time.setFont(T.font(8, QFont.DemiBold, mono=True))
        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        sub_row.addWidget(self.sub, 1)
        sub_row.addWidget(self.time)
        col.addWidget(self.title)
        col.addLayout(sub_row)
        lay.addLayout(col, 1)
        self.state = None
        self.detail = "Ready"
        self._started = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_state("idle", "Ready")

    def set_state(self, state, detail=None):
        text, color, pulse = self.STATES[state]
        self.state = state
        if detail is not None:
            self.detail = detail
        self.title.setText(text)
        self.title.setStyleSheet(f"color: {T.mix(color, T.TEXT, 0.35).name() if state != 'idle' else T.TEXT};")
        self.sub.setText(QFontMetrics(self.sub.font()).elidedText(self.detail, Qt.ElideRight, 150))
        self.sub.setToolTip(self.detail)
        self.dot.set_state(color, pulse, 900 if state == "waiting" else 1600)

    def start_clock(self):
        self._started = time.time()
        self._timer.start(1000)
        self._tick()

    def stop_clock(self):
        self._timer.stop()
        self._started = None
        self.time.setText("")

    def _tick(self):
        if self._started:
            s = int(time.time() - self._started)
            self.time.setText(f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}")


class _Logo(QWidget):
    def __init__(self, size=38, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        dpr = self.devicePixelRatioF()
        p.drawPixmap(0, 0, T.logo_pixmap(self.width(), dpr))


class Sidebar(QFrame):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(236)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 20, 14, 16)
        lay.setSpacing(0)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 0)
        brand.setSpacing(12)
        brand.addWidget(_Logo(38))
        col = QVBoxLayout()
        col.setSpacing(0)
        name = label("Coc-Bot")
        name.setFont(T.font(14, QFont.Bold, display=True))
        col.addWidget(name)
        col.addWidget(label("Clash of Clans assistant", "small"))
        brand.addLayout(col, 1)
        lay.addLayout(brand)
        lay.addSpacing(26)

        menu = section("Menu")
        menu.setContentsMargins(8, 0, 0, 0)
        lay.addWidget(menu)
        lay.addSpacing(8)
        self.nav = NavBar(items)
        lay.addWidget(self.nav)
        lay.addStretch(1)

        self.status = StatusChip()
        lay.addWidget(self.status)
        lay.addSpacing(10)
        self.keys = QLabel()
        self.keys.setAlignment(Qt.AlignCenter)
        self.keys.setTextFormat(Qt.RichText)
        lay.addWidget(self.keys)
        self.set_hotkeys({"continue": "f8", "pause": "f9", "stop": "f10"})

    def set_hotkeys(self, keys):
        def cap(k):
            return (f"<span style='background:{T.SURFACE_2}; color:{T.TEXT_MUTED}; font-family:Cascadia Mono,"
                    f"Consolas; font-weight:700; font-size:7.5pt;'>&nbsp;{(k or '-').upper()}&nbsp;</span>")
        dim = f"color:{T.TEXT_DIM}; font-size:8pt;"
        self.keys.setText(f"<span style='{dim}'>{cap(keys.get('continue'))} Continue &nbsp;"
                          f"{cap(keys.get('pause'))} Pause &nbsp;{cap(keys.get('stop'))} Stop</span>")


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

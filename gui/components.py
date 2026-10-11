"""Animated building blocks: buttons, toggle switches, choice cards, segmented controls, bars, pills, cards."""

import shiboken6
from PySide6.QtCore import (QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
                           QTextLayout)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSpinBox, QCompleter, QFrame,
                               QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy, QStyle, QStyledItemDelegate, QTableWidget,
                               QVBoxLayout, QWidget)

from gui import icons
from gui import theme as T


# ----------------------------------------------------------------------------- helpers
class Tween(QVariantAnimation):
    """A float that glides to a target value and repaints its owner on every step."""

    def __init__(self, owner, value=0.0, ms=180, curve=QEasingCurve.OutCubic, on_change=None):
        super().__init__(owner)
        self.value = float(value)
        self._cb = on_change or owner.update
        self.setDuration(ms)
        self.setEasingCurve(curve)
        self.valueChanged.connect(self._step)

    def _step(self, v):
        self.value = float(v)
        self._cb()

    def to(self, end, animate=True):
        end = float(end)
        if self.state() == QVariantAnimation.Running:
            if self.endValue() == end:
                return
            self.stop()
        if not animate or abs(self.value - end) < 1e-4:
            self.value = end
            self._cb()
            return
        self.setStartValue(self.value)
        self.setEndValue(end)
        self.start()


def wrap_text(text, font, width, max_lines):
    """Split text into at most max_lines lines that fit width, eliding the last one."""
    fm = QFontMetrics(font)
    layout = QTextLayout(text, font)
    layout.beginLayout()
    lines = []
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(10, width))
        start, length = line.textStart(), line.textLength()
        if len(lines) == max_lines - 1:
            lines.append(fm.elidedText(text[start:].strip(), Qt.ElideRight, int(width)))
            break
        lines.append(text[start:start + length].strip())
    layout.endLayout()
    return lines


def label(text="", role=None, wrap=False):
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    if wrap:
        lb.setWordWrap(True)
    return lb


def section(text):
    return label(text.upper(), "section")


def divider():
    f = QFrame()
    f.setObjectName("Divider")
    f.setFrameShape(QFrame.NoFrame)
    return f


def scroll(content, margins=(0, 0, 12, 0)):
    """Wrap a page body in a transparent, frameless vertical scroll area."""
    content.setObjectName("ScrollContent")
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(content)
    if content.layout():
        content.layout().setContentsMargins(*margins)
    return area


def hbox(*items, spacing=10, margins=(0, 0, 0, 0)):
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return lay


def fmt_int(v):
    return f"{v:,}" if isinstance(v, int) else "—"


def fmt_short(v):
    if not isinstance(v, (int, float)):
        return "—"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M".replace(".0M", "M")
    if v >= 10_000:
        return f"{v / 1000:.0f}K"
    return f"{v:,}"


# ----------------------------------------------------------------------------- buttons
class Button(QPushButton):
    """Hand-painted push button: game-like gradient faces with a pressable lip, animated hover/press,
    optional icon and a key-cap hint (e.g. "F9")."""

    VARIANTS = {
        #            face top    face bottom  text        lip
        "primary": (T.GOLD_HI, T.GOLD_LO, "#2b1a00", "#a8600a"),
        "danger": ("#ff6f7b", "#d9374a", "#ffffff", "#8f1f2e"),
        "success": ("#4bdc98", "#1fa463", "#03230f", "#11693d"),
        "secondary": (None, None, T.TEXT, None),
        "ghost": (None, None, T.TEXT_MUTED, None),
        "outline": (None, None, T.GOLD_HI, None),
    }
    SIZES = {"sm": (30, 8.75, 12, 14), "md": (34, 9.5, 15, 16), "lg": (46, 11.0, 24, 18)}

    def __init__(self, text="", icon=None, variant="secondary", size="md", hint="", parent=None):
        super().__init__(text, parent)
        self._icon = icon
        self.variant = variant
        self.size_name = size
        self.hint = hint
        self._hover = Tween(self, ms=170, on_change=self._anim)
        self._press = Tween(self, ms=90)
        self._effect = None
        self._glow = None
        self._pulse = None
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedHeight(self.SIZES[size][0])

    # --- api
    def set_icon(self, name):
        self._icon = name
        self.updateGeometry()
        self.update()

    def set_text(self, text):
        self.setText(text)
        self.updateGeometry()

    def set_hint(self, hint):
        self.hint = hint
        self.updateGeometry()
        self.update()

    def set_variant(self, variant):
        self.variant = variant
        self.update()

    def enable_glow(self, color=T.GOLD):
        """Soft coloured glow under the button that brightens on hover."""
        self._glow = QColor(color)
        self._ensure_effect()
        self._anim()

    def set_attention(self, on, color=T.AMBER):
        """Pulsing glow that asks the user to press this button."""
        if on:
            if self._pulse is None:
                self._pulse = QVariantAnimation(self)
                self._pulse.setDuration(1300)
                self._pulse.setStartValue(0.0)
                self._pulse.setKeyValueAt(0.5, 1.0)
                self._pulse.setEndValue(0.0)
                self._pulse.setEasingCurve(QEasingCurve.InOutSine)
                self._pulse.setLoopCount(-1)
                self._pulse.valueChanged.connect(self._anim)
            self._pulse_color = QColor(color)
            self._ensure_effect()
            self._pulse.start()
        elif self._pulse is not None:
            self._pulse.stop()
            self._pulse = None
            self._anim()

    def _ensure_effect(self):
        if self._effect is None:
            self._effect = QGraphicsDropShadowEffect(self)
            self._effect.setOffset(0, 3)
            self.setGraphicsEffect(self._effect)

    def _anim(self, *_):
        if self._effect is not None:
            if self._pulse is not None:
                v = float(self._pulse.currentValue() or 0.0)
                c = QColor(self._pulse_color)
                c.setAlpha(int(70 + 150 * v))
                self._effect.setColor(c)
                self._effect.setBlurRadius(14 + 22 * v)
                self._effect.setOffset(0, 0)
                self._effect.setEnabled(True)
            elif self._glow is not None and self.isEnabled():
                c = QColor(self._glow)
                c.setAlpha(int(55 + 110 * self._hover.value))
                self._effect.setColor(c)
                self._effect.setBlurRadius(16 + 14 * self._hover.value)
                self._effect.setOffset(0, 4)
                self._effect.setEnabled(True)
            else:
                self._effect.setEnabled(False)
        self.update()

    # --- geometry
    def _font(self):
        return T.font(self.SIZES[self.size_name][1], QFont.DemiBold)

    def _hint_font(self):
        return T.font(7.5, QFont.Bold, mono=True)

    def _hint_w(self):
        return QFontMetrics(self._hint_font()).horizontalAdvance(self.hint) + 10 if self.hint else 0

    def sizeHint(self):
        h, _pt, pad, isz = self.SIZES[self.size_name]
        fm = QFontMetrics(self._font())
        w = pad * 2 + (fm.horizontalAdvance(self.text()) if self.text() else 0)
        if self._icon:
            w += isz + (8 if self.text() else 0)
        if self.hint:
            w += self._hint_w() + 10
        if not self.text() and self._icon:
            w = max(h, isz + 2 * (pad - 4))
        return QSize(int(w), h)

    def minimumSizeHint(self):
        return self.sizeHint()

    # --- events
    def enterEvent(self, e):
        self._hover.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover.to(0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._press.to(1.0)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._press.to(0.0)
        super().mouseReleaseEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.EnabledChange:
            if not self.isEnabled():
                self._hover.to(0.0, False)
            self._anim()
        super().changeEvent(e)

    # --- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        enabled = self.isEnabled()
        if not enabled:
            p.setOpacity(0.38)
        top, bottom, fg, lip = self.VARIANTS.get(self.variant, self.VARIANTS["secondary"])
        h = self._hover.value if enabled else 0.0
        pr = self._press.value
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 8.0 if self.size_name == "sm" else 10.0 if self.size_name == "md" else 12.0
        fg_c = QColor(fg)
        if lip:
            lip_h = 3.0
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(lip))
            p.drawRoundedRect(r, radius, radius)
            face = QRectF(r.left(), r.top() + 2 * pr, r.width(), r.height() - lip_h)
            g = QLinearGradient(face.topLeft(), face.bottomLeft())
            g.setColorAt(0, T.mix(top, "#ffffff", 0.12 * h))
            g.setColorAt(1, T.mix(bottom, "#ffffff", 0.10 * h))
            p.setBrush(g)
            p.drawRoundedRect(face, radius, radius)
            hl = QLinearGradient(face.topLeft(), face.bottomLeft())
            hl.setColorAt(0, QColor(255, 255, 255, 120))
            hl.setColorAt(0.5, QColor(255, 255, 255, 0))
            p.setPen(QPen(QBrush(hl), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(face.adjusted(0.8, 0.8, -0.8, -0.8), radius - 0.8, radius - 0.8)
            content = face
        elif self.variant == "secondary":
            face = r.translated(0, pr)
            p.setPen(QPen(T.mix(T.BORDER_STRONG, "#4a5486", h), 1))
            g = QLinearGradient(face.topLeft(), face.bottomLeft())
            g.setColorAt(0, T.mix("#232947", "#2c3357", h))
            g.setColorAt(1, T.mix(T.SURFACE_2, "#262c4b", h))
            p.setBrush(g)
            p.drawRoundedRect(face, radius, radius)
            content = face
        elif self.variant == "outline":
            face = r.translated(0, pr)
            p.setPen(QPen(T.qc(T.GOLD, 0.45 + 0.4 * h), 1))
            p.setBrush(T.qc(T.GOLD, 0.06 + 0.08 * h))
            p.drawRoundedRect(face, radius, radius)
            content = face
        else:  # ghost
            face = r.translated(0, pr)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(16 * h)))
            p.drawRoundedRect(face, radius, radius)
            fg_c = T.mix(T.TEXT_MUTED, T.TEXT, h)
            content = face

        _hh, _pt, _pad, isz = self.SIZES[self.size_name]
        f = self._font()
        fm = QFontMetrics(f)
        text = self.text()
        tw = fm.horizontalAdvance(text) if text else 0
        total = tw + ((isz + (8 if text else 0)) if self._icon else 0) + ((self._hint_w() + 10) if self.hint else 0)
        x = content.center().x() - total / 2
        cy = content.center().y()
        if self._icon:
            icons.paint(p, self._icon, fg_c, QRectF(x, cy - isz / 2, isz, isz))
            x += isz + (8 if text else 0)
        if text:
            p.setFont(f)
            p.setPen(fg_c)
            p.drawText(QRectF(x, content.top(), tw + 2, content.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
            x += tw
        if self.hint:
            x += 10
            hw = self._hint_w()
            hr = QRectF(x, cy - 9, hw, 18)
            dark_face = bool(lip) and self.variant in ("primary", "success")
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 40) if dark_face else T.qc(fg_c, 0.12))
            p.drawRoundedRect(hr, 5, 5)
            p.setFont(self._hint_font())
            hc = QColor(fg_c)
            hc.setAlphaF(0.75)
            p.setPen(hc)
            p.drawText(hr, Qt.AlignCenter, self.hint)
        if self.hasFocus():
            p.setPen(QPen(T.qc(T.GOLD, 0.7), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)


class IconButton(Button):
    """Square ghost button with only an icon (tooltip explains it)."""

    def __init__(self, icon, tooltip="", size="sm", variant="ghost", parent=None):
        super().__init__("", icon, variant, size, parent=parent)
        self.setToolTip(tooltip)
        h = self.SIZES[size][0]
        self.setFixedSize(h, h)


# ----------------------------------------------------------------------------- toggle switch
def paint_toggle(p, track, t, h=0.0):
    """Draw a switch track + knob in `track` (QRectF); t = 0 (off) .. 1 (on), h = hover 0..1."""
    rad = track.height() / 2
    off_fill = T.mix("#262c4a", "#2e3558", h)
    on_fill = T.mix(T.GOLD, T.GOLD_HI, h * 0.6)
    p.setPen(QPen(T.mix(T.mix("#3a4370", "#4b5588", h), T.GOLD_LO, t), 1))
    p.setBrush(T.mix(off_fill, on_fill, t))
    p.drawRoundedRect(track, rad, rad)
    d = track.height() - 6
    kx = track.left() + 3 + t * (track.width() - 6 - d)
    knob = QRectF(kx, track.top() + 3, d, d)
    p.setPen(Qt.NoPen)
    if h > 0:
        p.setBrush(T.qc(T.GOLD if t > 0.5 else "#ffffff", 0.10 * h))
        p.drawEllipse(knob.adjusted(-5, -5, 5, 5))
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawEllipse(knob.translated(0, 1))
    p.setBrush(T.mix("#aab2d0", "#ffffff", t))
    p.drawEllipse(knob)


def paint_pill(p, x, cy, text, color, height=20):
    """Draw a small rounded tag starting at x, vertically centred on cy. Returns its width."""
    f = T.font(7.75, QFont.Bold)
    w = QFontMetrics(f).horizontalAdvance(text) + 18
    r = QRectF(x, cy - height / 2, w, height)
    p.setPen(QPen(T.qc(color, 0.30), 1))
    p.setBrush(T.qc(color, 0.15))
    p.drawRoundedRect(r, height / 2, height / 2)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(r, Qt.AlignCenter, text)
    return w


class Toggle(QAbstractButton):
    """iOS-style animated switch with an optional label. Same API as QCheckBox (isChecked / toggled)."""

    TW, TH = 40, 22

    def __init__(self, text="", parent=None, checked=False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._pos = Tween(self, ms=220)
        self._hover = Tween(self, ms=150)
        self.setChecked(checked)
        self._pos.to(1.0 if checked else 0.0, False)
        self.toggled.connect(lambda on: self._pos.to(1.0 if on else 0.0, self.isVisible()))
        self.setSizePolicy(QSizePolicy.Preferred if text else QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _font(self):
        return T.font(10)

    def sizeHint(self):
        w = self.TW + 2
        if self.text():
            w += 10 + QFontMetrics(self._font()).horizontalAdvance(self.text())
        return QSize(w, max(self.TH + 4, QFontMetrics(self._font()).height() + 4))

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def enterEvent(self, e):
        self._hover.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover.to(0.0)
        super().leaveEvent(e)

    def showEvent(self, e):
        self._pos.to(1.0 if self.isChecked() else 0.0, False)
        super().showEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        track = QRectF(1, (self.height() - self.TH) / 2, self.TW, self.TH)
        paint_toggle(p, track, self._pos.value, self._hover.value)
        if self.text():
            p.setFont(self._font())
            p.setPen(QColor(T.TEXT))
            p.drawText(QRectF(track.right() + 10, 0, self.width() - track.right() - 10, self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())
        if self.hasFocus():
            p.setPen(QPen(T.qc(T.GOLD, 0.7), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2), self.TH / 2 + 2, self.TH / 2 + 2)


# ----------------------------------------------------------------------------- choice card
class ChoiceCard(QAbstractButton):
    """A selectable card (icon tile, title, description) with an animated gold border and glow.
    Use in an exclusive QButtonGroup."""

    def __init__(self, title, description="", icon="bolt", accent=T.GOLD, badge="", lines=1, height=None,
                 parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.title = title
        self.description = description
        self.icon_name = icon
        self.accent = QColor(accent)
        self.badge = badge
        self.lines = lines
        self._sel = Tween(self, ms=240, on_change=self._anim)
        self._hover = Tween(self, ms=160)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setOffset(0, 0)
        self._shadow.setBlurRadius(26)
        self._shadow.setEnabled(False)
        self.setGraphicsEffect(self._shadow)
        self.toggled.connect(lambda on: self._sel.to(1.0 if on else 0.0, self.isVisible()))
        self.setToolTip(description if len(description) > 60 else "")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(height or (46 + 17 * max(1, lines) if description else 56))

    def set_badge(self, text):
        self.badge = text
        self.update()

    def _anim(self):
        a = self._sel.value
        self._shadow.setEnabled(a > 0.02 and self.isEnabled())
        self._shadow.setColor(T.qc(T.GOLD, 0.38 * a))
        self.update()

    def enterEvent(self, e):
        self._hover.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover.to(0.0)
        super().leaveEvent(e)

    def showEvent(self, e):
        self._sel.to(1.0 if self.isChecked() else 0.0, False)
        super().showEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.EnabledChange:
            self._anim()
        super().changeEvent(e)

    def sizeHint(self):
        return QSize(260, self.height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        enabled = self.isEnabled()
        s = self._sel.value
        h = self._hover.value if enabled else 0.0
        if not enabled:
            p.setOpacity(0.5 if not self.isChecked() else 0.75)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, T.mix(T.SURFACE, "#1b2036", h))
        if s > 0:
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, T.qc(T.GOLD, 0.13 * s))
            g.setColorAt(1, T.qc(T.GOLD, 0.02 * s))
            p.fillPath(path, g)
        p.setPen(QPen(T.mix(T.mix(T.BORDER, "#363f66", h), T.GOLD, s), 1 + 0.4 * s))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # icon tile
        ts = 38.0
        tile = QRectF(r.left() + 13, r.center().y() - ts / 2, ts, ts)
        tint = QColor(self.accent)
        tint.setAlphaF(0.15 + 0.08 * s)
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(tile, 10, 10)
        icons.paint(p, self.icon_name, self.accent, tile.adjusted(9, 9, -9, -9))

        # right side: badge or radio check
        right = r.right() - 14
        if self.badge:
            bf = T.font(7.5, QFont.Bold)
            bw = QFontMetrics(bf).horizontalAdvance(self.badge.upper()) + 14
            br = QRectF(right - bw, r.top() + 10, bw, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(T.qc(T.TEXT_MUTED, 0.14))
            p.drawRoundedRect(br, 9, 9)
            p.setFont(bf)
            p.setPen(QColor(T.TEXT_MUTED))
            p.drawText(br, Qt.AlignCenter, self.badge.upper())
            text_right = br.left() - 8
        else:
            cr = QRectF(right - 18, r.center().y() - 9, 18, 18)
            p.setPen(QPen(T.mix("#465079", T.GOLD, s), 1.5))
            p.setBrush(T.qc(T.GOLD, s))
            p.drawEllipse(cr)
            if s > 0.05:
                p.save()
                p.setOpacity(p.opacity() * s)
                icons.paint(p, "check", "#2a1b00", cr.adjusted(4, 4, -4, -4))
                p.restore()
            text_right = cr.left() - 10

        tx = tile.right() + 12
        tw = text_right - tx
        tf = T.font(10.25, QFont.DemiBold)
        df = T.font(8.75)
        tfm, dfm = QFontMetrics(tf), QFontMetrics(df)
        lines = wrap_text(self.description, df, tw, self.lines) if self.description else []
        block = tfm.height() + (3 + len(lines) * dfm.height() if lines else 0)
        y = r.center().y() - block / 2
        p.setFont(tf)
        p.setPen(T.mix(T.TEXT, T.GOLD_HI, s * 0.35))
        p.drawText(QRectF(tx, y, tw, tfm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   tfm.elidedText(self.title, Qt.ElideRight, int(tw)))
        y += tfm.height() + 3
        p.setFont(df)
        p.setPen(QColor(T.TEXT_MUTED))
        for ln in lines:
            p.drawText(QRectF(tx, y, tw, dfm.height()), Qt.AlignLeft | Qt.AlignVCenter, ln)
            y += dfm.height()
        if self.hasFocus():
            p.setPen(QPen(T.qc(T.GOLD, 0.6), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 10, 10)


# ----------------------------------------------------------------------------- segmented control
class Segmented(QWidget):
    """Two-to-four options with a sliding highlight. Mirrors the QComboBox data API."""

    currentIndexChanged = Signal(int)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self._opts = list(options)          # [(data, text)]
        self._index = 0
        self._x = Tween(self, ms=240)
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _font(self):
        return T.font(9.25, QFont.DemiBold)

    def sizeHint(self):
        fm = QFontMetrics(self._font())
        seg = max(fm.horizontalAdvance(t) for _, t in self._opts) + 30
        return QSize(int(seg * len(self._opts) + 6), 34)

    def minimumSizeHint(self):
        return self.sizeHint()

    def count(self):
        return len(self._opts)

    def currentIndex(self):
        return self._index

    def currentData(self):
        return self._opts[self._index][0] if self._opts else None

    def findData(self, data):
        for i, (d, _t) in enumerate(self._opts):
            if d == data:
                return i
        return -1

    def setCurrentIndex(self, i):
        i = max(0, min(len(self._opts) - 1, i))
        if i == self._index:
            return
        self._index = i
        self._x.to(i, self.isVisible())
        self.currentIndexChanged.emit(i)

    def showEvent(self, e):
        self._x.to(self._index, False)
        super().showEvent(e)

    def _seg_w(self):
        return (self.width() - 6) / max(1, len(self._opts))

    def mouseMoveEvent(self, e):
        i = int((e.position().x() - 3) // self._seg_w())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.setCurrentIndex(int((e.position().x() - 3) // self._seg_w()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(T.BORDER_STRONG), 1))
        p.setBrush(QColor(T.INPUT))
        p.drawRoundedRect(r, 10, 10)
        sw = self._seg_w()
        pill = QRectF(3 + self._x.value * sw, 3, sw, self.height() - 6)
        g = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        g.setColorAt(0, QColor("#323a63"))
        g.setColorAt(1, QColor("#283053"))
        p.setPen(QPen(T.qc(T.GOLD, 0.55), 1))
        p.setBrush(g)
        p.drawRoundedRect(pill, 8, 8)
        p.setFont(self._font())
        for i, (_d, text) in enumerate(self._opts):
            seg = QRectF(3 + i * sw, 0, sw, self.height())
            near = max(0.0, 1.0 - abs(self._x.value - i))
            c = T.mix(T.TEXT_MUTED if i != self._hover else T.TEXT, T.GOLD_HI, near)
            p.setPen(c)
            p.drawText(seg, Qt.AlignCenter, text)


# ----------------------------------------------------------------------------- bars, dots, numbers
class AnimatedBar(QWidget):
    """Rounded progress bar whose fill glides to the new value."""

    def __init__(self, colors=(T.GOLD_HI, T.GOLD_LO), height=8, parent=None):
        super().__init__(parent)
        self.colors = colors
        self._v = Tween(self, ms=650)
        self.full = False
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, frac, full=False):
        self.full = full
        self._v.to(max(0.0, min(1.0, frac or 0.0)), self.isVisible())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#232845"))
        p.drawRoundedRect(r, rad, rad)
        v = self._v.value
        if v <= 0.001:
            return
        fr = QRectF(r.left(), r.top(), max(r.height(), r.width() * v), r.height())
        g = QLinearGradient(fr.topLeft(), fr.topRight())
        g.setColorAt(0, QColor(self.colors[1]))
        g.setColorAt(1, QColor(self.colors[0]))
        p.setBrush(g)
        p.drawRoundedRect(fr, rad, rad)
        p.setBrush(QColor(255, 255, 255, 45))
        p.drawRoundedRect(QRectF(fr.left() + rad / 2, fr.top() + 1, max(0, fr.width() - rad), fr.height() * 0.38),
                          rad / 3, rad / 3)


class PulseDot(QWidget):
    """Status dot; when pulsing a ring expands and fades around it."""

    def __init__(self, color=T.TEXT_DIM, size=22, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(size, size)
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1500)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._step)

    def _step(self, v):
        self._t = float(v)
        self.update()

    def set_state(self, color, pulse, speed=1500):
        self.color = QColor(color)
        if pulse:
            self._anim.setDuration(speed)
            if self._anim.state() != QVariantAnimation.Running:
                self._anim.start()
        else:
            self._anim.stop()
            self._t = 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        base = self.width() * 0.2
        p.setPen(Qt.NoPen)
        if self._anim.state() == QVariantAnimation.Running:
            ring = QColor(self.color)
            ring.setAlphaF(0.55 * (1 - self._t))
            p.setBrush(ring)
            rr = base + (self.width() / 2 - base) * self._t
            p.drawEllipse(c, rr, rr)
        glow = QColor(self.color)
        glow.setAlphaF(0.25)
        p.setBrush(glow)
        p.drawEllipse(c, base + 2, base + 2)
        p.setBrush(self.color)
        p.drawEllipse(c, base, base)


class CountLabel(QLabel):
    """Label showing a number that counts up/down to new values."""

    def __init__(self, fmt=fmt_int, role="value", parent=None):
        super().__init__("—", parent)
        self.setProperty("role", role)
        self.fmt = fmt
        self._val = None
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(550)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda v: self.setText(self.fmt(int(round(float(v))))))

    def value(self):
        return self._val

    def set_fmt(self, fmt):
        """Change the number format (e.g. compact "22.9M" in narrow cards) and redraw."""
        if fmt is not self.fmt:
            self.fmt = fmt
            if self._val is not None and self._anim.state() != QVariantAnimation.Running:
                self.setText(fmt(self._val))

    def set_value(self, v):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            self._anim.stop()
            self._val = None
            self.setText("—")
            return
        v = int(v)
        if self._val is None or not self.isVisible():
            self._anim.stop()
            self._val = v
            self.setText(self.fmt(v))
            return
        if v == self._val:
            return
        self._anim.stop()
        self._anim.setStartValue(float(self._val))
        self._anim.setEndValue(float(v))
        self._val = v
        self._anim.start()


class Pill(QLabel):
    """Small rounded tag, e.g. FULL / captured / 3 accounts."""

    def __init__(self, text="", color=T.TEXT_MUTED, parent=None, strong=False):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.set(text, color, strong)

    def set(self, text, color=None, strong=False):
        if color:
            self._color = color
        self.setText(text)
        c = self._color
        bg = T.rgba(c, 0.95) if strong else T.rgba(c, 0.15)
        fg = "#1e1400" if strong else c
        self.setStyleSheet(f"QLabel {{ background: {bg}; color: {fg}; border: 1px solid {T.rgba(c, 0.28)}; "
                           f"border-radius: 9px; padding: 1px 8px; font-size: 8pt; font-weight: 700; }}")


class IconTile(QWidget):
    """Rounded square with a tinted background and an icon (card headers)."""

    def __init__(self, icon, color=T.GOLD, size=32, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.color = QColor(color)
        self.setFixedSize(size, size)

    def set_icon(self, icon, color=None):
        self.icon_name = icon
        if color:
            self.color = QColor(color)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        bg = QColor(self.color)
        bg.setAlphaF(0.15)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, r.width() * 0.3, r.width() * 0.3)
        m = r.width() * 0.25
        icons.paint(p, self.icon_name, self.color, r.adjusted(m, m, -m, -m))


class ResourceIcon(QWidget):
    def __init__(self, res, size=26, parent=None):
        super().__init__(parent)
        self.res = res
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        icons.paint_resource(p, self.res, QRectF(self.rect()).adjusted(1, 1, -1, -1))


class Avatar(QWidget):
    """Round avatar with the account's initial on a gold gradient."""

    def __init__(self, size=40, parent=None):
        super().__init__(parent)
        self.text = ""
        self.setFixedSize(size, size)

    def set_name(self, name):
        name = (name or "").strip()
        self.text = name[:1].upper() if name else ""
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.text:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor(T.GOLD_HI))
            g.setColorAt(1, QColor(T.GOLD_LO))
            p.setBrush(g)
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.drawEllipse(r)
            p.setFont(T.font(self.width() * 0.3, QFont.Bold, display=True))
            p.setPen(QColor("#2b1a00"))
            p.drawText(r, Qt.AlignCenter, self.text)
        else:
            p.setBrush(QColor(T.SURFACE_3))
            p.setPen(Qt.NoPen)
            p.drawEllipse(r)
            m = r.width() * 0.26
            icons.paint(p, "user", T.TEXT_DIM, r.adjusted(m, m, -m, -m))


# ----------------------------------------------------------------------------- containers
class Card(QFrame):
    """Rounded surface with an optional header (icon tile, title, subtitle, actions on the right)."""

    def __init__(self, title="", subtitle="", icon=None, color=T.GOLD, padding=18, spacing=12, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(padding, padding - 2, padding, padding)
        lay.setSpacing(spacing)
        self.actions = None
        if title:
            head = QHBoxLayout()
            head.setSpacing(12)
            if icon:
                self.tile = IconTile(icon, color, 32)
                head.addWidget(self.tile, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(1)
            self.title_label = label(title, "cardTitle")
            col.addWidget(self.title_label)
            if subtitle:
                self.subtitle_label = label(subtitle, "rowDesc", wrap=True)
                col.addWidget(self.subtitle_label)
            head.addLayout(col, 1)
            self.actions = QHBoxLayout()
            self.actions.setSpacing(6)
            head.addLayout(self.actions)
            lay.addLayout(head)
            lay.addSpacing(2)

    def add(self, w, stretch=0):
        if isinstance(w, QWidget):
            self.layout().addWidget(w, stretch)
        else:
            self.layout().addLayout(w, stretch)
        return w

    def add_action(self, w):
        self.actions.addWidget(w)
        return w


class SettingRow(QWidget):
    """Settings-list row: title + description on the left, a control on the right.
    Clicking the text of a Toggle row flips the toggle."""

    def __init__(self, title, description="", control=None, control_width=None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(16)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = label(title, "rowTitle", wrap=True)
        col.addWidget(self.title)
        if description:
            self.desc = label(description, "rowDesc", wrap=True)
            col.addWidget(self.desc)
        lay.addLayout(col, 1)
        self.control = control
        if control is not None:
            if control_width:
                control.setFixedWidth(control_width)
            lay.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)

    def mouseReleaseEvent(self, e):
        if isinstance(self.control, Toggle) and self.control.isEnabled() and e.button() == Qt.LeftButton:
            self.control.toggle()
        super().mouseReleaseEvent(e)


class Banner(QFrame):
    """Coloured callout with an icon and text (info / warning / success / error)."""

    KINDS = {"info": ("info", T.BLUE), "warning": ("warning", T.AMBER), "success": ("check-circle", T.GREEN),
             "error": ("x-circle", T.RED)}

    def __init__(self, text, kind="info", parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setProperty("kind", kind)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 10)
        lay.setSpacing(12)
        icon, color = self.KINDS[kind]
        self.icon = QLabel()
        self.icon.setPixmap(icons.pixmap(icon, color, 18))
        self.icon.setFixedSize(20, 20)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        self.text = label(text, wrap=True)
        self.text.setTextFormat(Qt.RichText)
        self.text.setStyleSheet(f"color: {T.mix(color, T.TEXT, 0.55).name()};")
        lay.addWidget(self.text, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        lay.addLayout(self.buttons)

    def add_button(self, b):
        self.buttons.addWidget(b, 0, Qt.AlignVCenter)
        return b


# ----------------------------------------------------------------------------- tables
class _RowDelegate(QStyledItemDelegate):
    def updateEditorGeometry(self, editor, option, index):
        # The default insets editors/cell widgets by the item padding; use the whole cell instead and
        # centre input-like widgets vertically at their natural height.
        r = option.rect
        if hasattr(editor, "inner"):
            editor.setGeometry(r)
            return
        h = min(r.height() - 6, max(30, min(editor.sizeHint().height(), editor.maximumHeight())))
        editor.setGeometry(r.left() + 3, r.top() + (r.height() - h) // 2, r.width() - 6, h)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        table = self.parent()
        if index.row() == getattr(table, "hover_row", -1) and not option.state & QStyle.State_Selected:
            option.backgroundBrush = QBrush(QColor(255, 255, 255, 11))


class Table(QTableWidget):
    """Styled table: alternating rows, whole-row hover, rounded header, comfortable row height."""

    def __init__(self, columns, row_height=46, parent=None):
        super().__init__(0, len(columns), parent)
        self.hover_row = -1
        self.setHorizontalHeaderLabels(columns)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(row_height)
        self.verticalHeader().setMinimumSectionSize(row_height)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self.setWordWrap(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setItemDelegate(_RowDelegate(self))
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setMinimumSectionSize(40)
        h.setFixedHeight(38)
        h.setSectionsClickable(False)

    def resize_modes(self, stretch, fixed=None):
        """stretch: column that takes the free space; fixed: {col: width}; others fit their contents."""
        h = self.horizontalHeader()
        for c in range(self.columnCount()):
            if c == stretch:
                h.setSectionResizeMode(c, QHeaderView.Stretch)
            elif fixed and c in fixed:
                h.setSectionResizeMode(c, QHeaderView.Fixed)
                h.resizeSection(c, fixed[c])
            else:
                h.setSectionResizeMode(c, QHeaderView.ResizeToContents)

    def _set_hover(self, row):
        if row != self.hover_row:
            self.hover_row = row
            self.viewport().update()

    def viewportEvent(self, e):
        t = e.type()
        if t in (QEvent.MouseMove, QEvent.HoverMove):
            self._set_hover(self.rowAt(int(e.position().y())))
        elif t == QEvent.Leave:
            self._set_hover(-1)
        return super().viewportEvent(e)

    def setCellWidget(self, row, col, w):
        w.installEventFilter(self)
        if isinstance(w, QAbstractSpinBox):
            w.setButtonSymbols(QAbstractSpinBox.NoButtons)
            w.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        super().setCellWidget(row, col, w)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Enter and isinstance(obj, QWidget):
            pt = obj.mapTo(self.viewport(), QPoint(0, obj.height() // 2))
            self._set_hover(self.rowAt(pt.y()))
        return False

    empty_text = ""

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.rowCount() == 0 and self.empty_text:
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(self.viewport().rect())
            ic = QRectF(r.center().x() - 18, r.center().y() - 46, 36, 36)
            icons.paint(p, self.empty_icon if hasattr(self, "empty_icon") else "info", T.TEXT_DIM, ic)
            p.setFont(T.font(10))
            p.setPen(QColor(T.TEXT_MUTED))
            p.drawText(QRectF(r.left() + 20, ic.bottom() + 10, r.width() - 40, 60), Qt.AlignHCenter | Qt.AlignTop
                       | Qt.TextWordWrap, self.empty_text)

    def centered(self, w):
        """Wrap a small widget so it sits centred in its cell."""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(10, 0, 4, 0)
        lay.addWidget(w, 0, Qt.AlignLeft | Qt.AlignVCenter)
        box.inner = w
        return box


# ----------------------------------------------------------------------------- table delegates
ROLE = Qt.UserRole


def _hover_box(p, r):
    p.setPen(QPen(QColor(T.BORDER_STRONG), 1))
    p.setBrush(QColor(T.INPUT))
    p.drawRoundedRect(QRectF(r).adjusted(4, 8, -4, -8), 7, 7)


class ToggleDelegate(_RowDelegate):
    """On/off switch painted in the cell (bool in UserRole); a click flips it with a short animation."""

    def __init__(self, table):
        super().__init__(table)
        self._anims = {}

    @staticmethod
    def _track(rect):
        return QRectF(rect.left() + 12, rect.center().y() - 11, 40, 22)

    def paint(self, p, option, index):
        super().paint(p, option, index)
        a = self._anims.get((index.row(), index.column()))
        t = a.value if a is not None else (1.0 if index.data(ROLE) else 0.0)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if not option.state & QStyle.State_Enabled:
            p.setOpacity(0.4)
        paint_toggle(p, self._track(option.rect), t, 0.6 if index.row() == self.parent().hover_row else 0.0)
        p.restore()

    def editorEvent(self, event, model, option, index):
        if not index.flags() & Qt.ItemIsEnabled:
            return False
        t = event.type()
        inside = (t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick)
                  and self._track(option.rect).adjusted(-8, -8, 8, 8).contains(event.position()))
        flip = ((t == QEvent.MouseButtonRelease and inside and event.button() == Qt.LeftButton)
                or (t == QEvent.KeyPress and event.key() == Qt.Key_Space))
        if flip:
            old = bool(index.data(ROLE))
            key = (index.row(), index.column())
            tw = Tween(self, 1.0 if old else 0.0, ms=200, on_change=self.parent().viewport().update)
            tw.finished.connect(lambda k=key, a=tw: self._anims.pop(k, None) if self._anims.get(k) is a else None)
            self._anims[key] = tw
            model.setData(index, not old, ROLE)
            tw.to(0.0 if old else 1.0)
            return True
        return inside


class ChoiceDelegate(_RowDelegate):
    """Shows icon + label for the key in UserRole; a click opens a combo box with the choices."""

    def __init__(self, table, options):
        super().__init__(table)
        self.options = options              # [(key, text, icon, colour, tooltip)]

    def _opt(self, key):
        for o in self.options:
            if o[0] == key:
                return o
        return self.options[0]

    def paint(self, p, option, index):
        super().paint(p, option, index)
        _key, text, icon, color = self._opt(index.data(ROLE))[:4]
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if index.row() == self.parent().hover_row and index.flags() & Qt.ItemIsEnabled:
            _hover_box(p, r)
        icons.paint(p, icon, color, QRectF(r.left() + 13, r.center().y() - 8, 16, 16))
        p.setFont(T.font(10))
        p.setPen(QColor(T.TEXT))
        p.drawText(QRectF(r.left() + 37, r.top(), r.width() - 66, r.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        icons.paint(p, "chevron-down", T.TEXT_MUTED, QRectF(r.right() - 26, r.center().y() - 6, 12, 12))
        p.restore()

    def editorEvent(self, event, model, option, index):
        if (event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton
                and index.flags() & Qt.ItemIsEnabled):
            view = self.parent()
            view.setCurrentIndex(index)
            view.edit(index)
            return True
        return False

    def createEditor(self, parent, option, index):
        from gui.widgets import Combo
        cb = Combo(parent=parent)
        for key, text, icon, color, *tip in self.options:
            cb.addItem(icons.icon(icon, color, 16), text, key)
            if tip:
                cb.setItemData(cb.count() - 1, tip[0], Qt.ToolTipRole)

        def done(*_):
            self.commitData.emit(cb)
            self.closeEditor.emit(cb)
        cb.activated.connect(done)
        QTimer.singleShot(0, lambda: cb.showPopup() if shiboken6.isValid(cb) and cb.isVisible() else None)
        return cb

    def setEditorData(self, editor, index):
        editor.select(index.data(ROLE))

    def setModelData(self, editor, model, index):
        if editor.currentData() != index.data(ROLE):
            model.setData(index, editor.currentData(), ROLE)


class NumberDelegate(_RowDelegate):
    """Number in UserRole shown as text (dim when it is the "special" value); edits with a spin box."""

    def __init__(self, table, fmt, make_editor):
        super().__init__(table)
        self.fmt = fmt                      # value -> (text, dim)
        self.make_editor = make_editor      # parent -> spin box

    def paint(self, p, option, index):
        super().paint(p, option, index)
        text, dim = self.fmt(index.data(ROLE))
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        editable = bool(index.flags() & Qt.ItemIsEditable)
        if editable and index.row() == self.parent().hover_row:
            _hover_box(p, r)
        p.setFont(T.font(10))
        p.setPen(QColor(T.TEXT_DIM if dim or not editable else T.TEXT))
        p.drawText(QRectF(r.left() + 13, r.top(), r.width() - 20, r.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.restore()

    def createEditor(self, parent, option, index):
        sp = self.make_editor(parent)
        sp.setButtonSymbols(QAbstractSpinBox.NoButtons)
        sp.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return sp

    def setEditorData(self, editor, index):
        editor.setValue(index.data(ROLE) or 0)
        editor.selectAll()

    def setModelData(self, editor, model, index):
        editor.interpretText()
        if editor.value() != index.data(ROLE):
            model.setData(index, editor.value(), ROLE)


class TwoLineDelegate(_RowDelegate):
    """UserRole = (title, subtitle, bold): a title with a muted second line."""

    def paint(self, p, option, index):
        super().paint(p, option, index)
        title, sub, bold = index.data(ROLE) or ("", "", False)
        r = option.rect
        tf = T.font(10, QFont.Bold if bold else QFont.Normal)
        sf = T.font(8.25)
        tfm, sfm = QFontMetrics(tf), QFontMetrics(sf)
        y = r.center().y() - (tfm.height() + sfm.height()) / 2
        p.save()
        p.setFont(tf)
        p.setPen(QColor(T.TEXT))
        p.drawText(QRectF(r.left() + 12, y, r.width() - 16, tfm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   tfm.elidedText(title, Qt.ElideRight, r.width() - 16))
        p.setFont(sf)
        p.setPen(QColor(T.TEXT_DIM))
        p.drawText(QRectF(r.left() + 12, y + tfm.height(), r.width() - 16, sfm.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, sfm.elidedText(sub, Qt.ElideRight, r.width() - 16))
        p.restore()


class PlaceholderDelegate(_RowDelegate):
    """Plain editable text; an empty cell shows a dim hint from placeholder(index) instead."""

    def __init__(self, table, placeholder):
        super().__init__(table)
        self.placeholder = placeholder      # index -> str

    def paint(self, p, option, index):
        super().paint(p, option, index)
        if (index.data(Qt.DisplayRole) or "").strip():
            return
        hint = self.placeholder(index) or ""
        if not hint:
            return
        r = option.rect
        f = T.font(9.25)
        f.setItalic(True)
        p.save()
        p.setFont(f)
        p.setPen(QColor(T.TEXT_DIM))
        p.drawText(QRectF(r.left() + 11, r.top(), r.width() - 20, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f).elidedText(hint, Qt.ElideRight, r.width() - 20))
        p.restore()


class PillDelegate(_RowDelegate):
    """UserRole = (text, colour): a small status tag."""

    def paint(self, p, option, index):
        super().paint(p, option, index)
        data = index.data(ROLE)
        if data:
            p.save()
            p.setRenderHint(QPainter.Antialiasing)
            paint_pill(p, option.rect.left() + 10, option.rect.center().y(), *data)
            p.restore()


def field(title, control, hint=""):
    """Label above a control (and an optional hint below) — for text inputs that need width."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(6)
    lay.addWidget(label(title, "field"))
    if isinstance(control, QWidget):
        lay.addWidget(control)
    else:
        lay.addLayout(control)
    if hint:
        lay.addWidget(label(hint, "small", wrap=True))
    return w


class ChipToggle(QAbstractButton):
    """Pill-shaped on/off chip with a resource glyph (or icon); tints with its colour when on."""

    def __init__(self, text, color=T.GOLD, resource=None, icon=None, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self.color = QColor(color)
        self.resource = resource
        self.icon_name = icon
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._on = Tween(self, ms=200)
        self._hover = Tween(self, ms=150)
        self.toggled.connect(lambda on: self._on.to(1.0 if on else 0.0, self.isVisible()))
        self.setFixedHeight(36)

    def _font(self):
        return T.font(9.5, QFont.DemiBold)

    def sizeHint(self):
        return QSize(QFontMetrics(self._font()).horizontalAdvance(self.text()) + 74, 36)

    def minimumSizeHint(self):
        return self.sizeHint()

    def showEvent(self, e):
        self._on.to(1.0 if self.isChecked() else 0.0, False)
        super().showEvent(e)

    def enterEvent(self, e):
        self._hover.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover.to(0.0)
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        t, h = self._on.value, self._hover.value
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = r.height() / 2
        bg = T.mix(T.mix(T.INPUT, "#1a1f38", h), T.mix(T.INPUT, self.color, 0.16), t)
        p.setPen(QPen(T.mix(T.mix(T.BORDER_STRONG, "#46507f", h), self.color, t * 0.85), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, rad, rad)
        ir = QRectF(r.left() + 9, r.center().y() - 10, 20, 20)
        p.save()
        p.setOpacity(p.opacity() * (0.45 + 0.55 * t))
        if self.resource:
            icons.paint_resource(p, self.resource, ir)
        elif self.icon_name:
            icons.paint(p, self.icon_name, self.color, ir.adjusted(2, 2, -2, -2))
        p.restore()
        p.setFont(self._font())
        p.setPen(T.mix(T.TEXT_MUTED, T.TEXT, max(t, h * 0.6)))
        p.drawText(QRectF(ir.right() + 8, r.top(), r.width() - 70, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   self.text())
        # check mark circle on the right
        cr = QRectF(r.right() - 26, r.center().y() - 8, 16, 16)
        p.setPen(QPen(T.mix("#465079", self.color, t), 1.4))
        p.setBrush(T.qc(self.color, t))
        p.drawEllipse(cr)
        if t > 0.05:
            p.save()
            p.setOpacity(p.opacity() * t)
            icons.paint(p, "check", "#1d1300", cr.adjusted(3.5, 3.5, -3.5, -3.5))
            p.restore()


class ElidedLabel(QWidget):
    """Wrapped text limited to `lines` lines (last one elided). Reserves its height so layouts never jump."""

    def __init__(self, text="", lines=2, pt=8.75, color=T.TEXT_MUTED, weight=QFont.Normal, parent=None):
        super().__init__(parent)
        self._text = text
        self.lines = lines
        self._font = T.font(pt, weight)
        self.color = QColor(color)
        self.setFixedHeight(QFontMetrics(self._font).lineSpacing() * lines + 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(40)

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text or ""
        self.setToolTip(self._text if len(self._text) > 80 else "")
        self.update()

    def set_color(self, color):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, _):
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(self._font)
        p.setPen(self.color)
        fm = QFontMetrics(self._font)
        y = 0
        for ln in wrap_text(self._text, self._font, self.width(), self.lines):
            p.drawText(QRectF(0, y, self.width(), fm.lineSpacing()), Qt.AlignLeft | Qt.AlignVCenter, ln)
            y += fm.lineSpacing()


# ----------------------------------------------------------------------------- tag list editor
class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps onto new lines (chips, tags). Height follows the width."""

    def __init__(self, parent=None, hspacing=6, vspacing=6):
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspacing, vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._arrange(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize(0, 0)
        for it in self._items:
            if not it.isEmpty():
                s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect, move):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            if it.isEmpty():
                continue
            sz = it.sizeHint()
            if line_h and x + sz.width() > r.x() + r.width():
                x, y, line_h = r.x(), y + line_h + self._v, 0
            if move:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self._h
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y() + m.bottom()


class TagChip(QWidget):
    """Rounded tag with a small remove (×) button on the right."""

    removed = Signal(str)
    H = 30

    def __init__(self, text, icon=None, color=T.TEXT_DIM, parent=None):
        super().__init__(parent)
        self.text = text
        self.icon_name = icon
        self.color = QColor(color)
        self._hover = Tween(self, ms=150)
        self._x_hover = Tween(self, ms=120)
        self._on_x = False
        self.setMouseTracking(True)
        self.setFixedHeight(self.H)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _font(self):
        return T.font(9.25, QFont.Medium)

    def _text_x(self):
        return 30 if self.icon_name else 13

    def sizeHint(self):
        return QSize(self._text_x() + QFontMetrics(self._font()).horizontalAdvance(self.text) + 34, self.H)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _x_rect(self):
        return QRectF(self.width() - 26, (self.H - 20) / 2, 20, 20)

    def _set_on_x(self, on):
        on = on and self.isEnabled()
        if on != self._on_x:
            self._on_x = on
            self._x_hover.to(1.0 if on else 0.0)
            self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)
            self.setToolTip(f"Remove “{self.text}”" if on else "")

    def enterEvent(self, e):
        self._hover.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover.to(0.0)
        self._set_on_x(False)
        super().leaveEvent(e)

    def mouseMoveEvent(self, e):
        self._set_on_x(self._x_rect().adjusted(-4, -4, 4, 4).contains(e.position()))
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if (e.button() == Qt.LeftButton and self.isEnabled()
                and self._x_rect().adjusted(-4, -4, 4, 4).contains(e.position())):
            self.removed.emit(self.text)
            return
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        h, xh = self._hover.value, self._x_hover.value
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = r.height() / 2
        p.setPen(QPen(T.mix(T.BORDER_STRONG, "#46507f", h), 1))
        p.setBrush(T.mix(T.INPUT, "#1a1f38", h))
        p.drawRoundedRect(r, rad, rad)
        if self.icon_name:
            icons.paint(p, self.icon_name, self.color, QRectF(r.left() + 11, r.center().y() - 7, 14, 14))
        p.setFont(self._font())
        p.setPen(QColor(T.TEXT))
        tx = self._text_x()
        p.drawText(QRectF(tx, r.top(), r.width() - tx - 30, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        xr = self._x_rect()
        if xh > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(T.qc(T.RED, 0.18 * xh))
            p.drawEllipse(xr)
        icons.paint(p, "x", T.mix(T.mix(T.TEXT_DIM, T.TEXT_MUTED, h), T.RED, xh), xr.adjusted(5, 5, -5, -5))


def _popup_style():
    return (f"QListView {{ background: {T.SURFACE_2}; color: {T.TEXT}; border: 1px solid {T.BORDER_STRONG}; "
            f"border-radius: 8px; padding: 4px; outline: 0; }}"
            f"QListView::item {{ min-height: 28px; padding: 0 10px; border-radius: 6px; }}"
            f"QListView::item:hover {{ background: {T.SURFACE_3}; }}"
            f"QListView::item:selected {{ background: {T.rgba(T.GOLD, 0.14)}; color: {T.GOLD_HI}; }}")


class TagEditor(QWidget):
    """Editable list of short names shown as removable chips, with a box to add more
    (Enter or Add; commas add several at once). Optional suggestions and a reset-to-defaults button."""

    changed = Signal()

    def __init__(self, placeholder="Add a name…", suggestions=(), empty_text="Nothing in the list.", defaults=None,
                 icon=None, icon_color=T.TEXT_DIM, parent=None):
        super().__init__(parent)
        self._values = []
        self._chips = {}
        self.icon = icon
        self.icon_color = icon_color
        self.defaults = list(defaults) if defaults is not None else None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)
        self.chip_box = QWidget()
        self.flow = FlowLayout(self.chip_box, 6, 6)
        lay.addWidget(self.chip_box)
        self.empty = label(empty_text, "small", wrap=True)
        self.empty.setStyleSheet(f"color: {T.TEXT_DIM};")
        lay.addWidget(self.empty)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMaxLength(80)
        self.add_btn = Button("Add", "plus", "secondary")
        self.add_btn.setEnabled(False)
        row = hbox(self.edit, self.add_btn, spacing=8)
        self.reset_btn = None
        if self.defaults is not None:
            self.reset_btn = IconButton("refresh", "Back to the default list", size="md", variant="secondary")
            row.addWidget(self.reset_btn)
            self.reset_btn.clicked.connect(self.reset)
        lay.addLayout(row)
        if suggestions:
            comp = QCompleter(sorted(set(suggestions), key=str.lower), self)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            comp.setMaxVisibleItems(8)
            comp.popup().setStyleSheet(_popup_style())
            comp.popup().setFont(T.font(9.5))
            self.edit.setCompleter(comp)
            comp.activated[str].connect(self._completed)
        self.edit.returnPressed.connect(self._add_typed)
        self.add_btn.clicked.connect(self._add_typed)
        self.edit.textChanged.connect(lambda t: self.add_btn.setEnabled(bool(t.strip())))
        self._sync()

    # --- api
    def values(self):
        return list(self._values)

    def set_values(self, values):
        for chip in self._chips.values():
            self.flow.removeWidget(chip)
            chip.hide()
            chip.deleteLater()
        self._chips = {}
        self._values = []
        self._add_many(values or [], emit=False)

    def add(self, text):
        return self._add_many(self._split(text))

    def remove(self, text):
        if text in self._values:
            self._values.remove(text)
            chip = self._chips.pop(text, None)
            if chip is not None:
                self.flow.removeWidget(chip)
                chip.hide()
                chip.deleteLater()
            self._sync()
            self.changed.emit()

    def reset(self):
        if self.defaults is not None and self._values != self.defaults:
            self.set_values(self.defaults)
            self.changed.emit()

    # --- internals
    @staticmethod
    def _split(text):
        return [t.strip() for t in str(text or "").replace(";", ",").replace("\n", ",").split(",")]

    def _add_many(self, items, emit=True):
        added = False
        have = {v.casefold() for v in self._values}
        for t in items:
            t = str(t).strip()
            if not t or t.casefold() in have:
                continue
            have.add(t.casefold())
            self._values.append(t)
            chip = TagChip(t, self.icon, self.icon_color)
            chip.removed.connect(self.remove)
            self._chips[t] = chip
            self.flow.addWidget(chip)
            added = True
        self._sync()
        if added and emit:
            self.changed.emit()
        return added

    def _add_typed(self):
        if self.edit.text().strip():
            self.add(self.edit.text())
            self.edit.clear()

    def _completed(self, text):
        self.add(text)
        QTimer.singleShot(0, self.edit.clear)

    def _sync(self):
        has = bool(self._values)
        self.chip_box.setVisible(has)
        self.empty.setVisible(not has)
        if self.reset_btn is not None:
            self.reset_btn.setEnabled(self._values != self.defaults)
        self.flow.invalidate()
        self.updateGeometry()

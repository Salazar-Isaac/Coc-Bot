"""Line icons (24x24 SVG, drawn for this app) rendered in any colour, plus resource glyphs."""

from functools import lru_cache

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtSvg import QSvgRenderer

# stroke icons (fill="none")
_STROKE = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.6"/><rect x="14" y="3" width="7" height="5" rx="1.6"/>'
                 '<rect x="14" y="12" width="7" height="9" rx="1.6"/><rect x="3" y="16" width="7" height="5" rx="1.6"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a7 7 0 0 1 14 0v1"/>',
    "swords": '<path d="M14.5 17.5 3 6V3h3l11.5 11.5"/><path d="m13 19 6-6"/><path d="m16 16 4 4"/>'
              '<path d="m19 21 2-2"/><path d="M14.5 6.5 18 3h3v3l-3.5 3.5"/><path d="m5 14 4 4"/>'
              '<path d="m7 17-3 3"/><path d="m3 19 2 2"/>',
    "coins": '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/>'
             '<path d="m16.71 13.88.7.71-2.82 2.82"/>',
    "gift": '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13"/>'
            '<path d="M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7"/>'
            '<path d="M7.5 8a2.5 2.5 0 0 1 0-5C10 3 12 8 12 8s2-5 4.5-5a2.5 2.5 0 0 1 0 5"/>',
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2'
             'A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2.2"/><path d="M8 21h8"/><path d="M12 17v4"/>',
    "phone": '<rect x="6" y="2" width="12" height="20" rx="2.6"/><path d="M11 18h2"/>',
    "scan": '<path d="M3 7.5V6a3 3 0 0 1 3-3h1.5"/><path d="M16.5 3H18a3 3 0 0 1 3 3v1.5"/>'
            '<path d="M21 16.5V18a3 3 0 0 1-3 3h-1.5"/><path d="M7.5 21H6a3 3 0 0 1-3-3v-1.5"/>'
            '<rect x="7.5" y="7.5" width="9" height="9" rx="1.5"/>',
    "terminal": '<rect x="2" y="3" width="20" height="18" rx="2.5"/><path d="m7 9 3 3-3 3"/><path d="M13 15h4"/>',
    "power": '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
             '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    "arrow-up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    "camera": '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/>'
              '<circle cx="12" cy="13" r="3.5"/>',
    "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "hash": '<path d="M4 9h16"/><path d="M4 15h16"/><path d="M10 3 8 21"/><path d="m16 3-2 18"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "warning": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>'
               '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "check-circle": '<circle cx="12" cy="12" r="10"/><path d="m8 12.5 2.8 2.8L16 9.5"/>',
    "x-circle": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/>'
            '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "keyboard": '<rect x="2" y="5" width="20" height="14" rx="2.2"/><path d="M6 9h1"/><path d="M10 9h1"/>'
                '<path d="M14 9h1"/><path d="M18 9h0.5"/><path d="M6 13h1"/><path d="M17.5 13h0.5"/>'
                '<path d="M10 13h4"/><path d="M7 16h10"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "sliders": '<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/>'
               '<path d="M20 12V3"/><path d="M1 14h6"/><path d="M9 8h6"/><path d="M17 16h6"/>',
    "crown": '<path d="M3 17 2 7l5.5 4L12 4l4.5 7L22 7l-1 10z"/><path d="M4 21h16"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "bolt": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    "sparkles": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8'
                'L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "list": '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.5"/><path d="M3 12h.5"/>'
            '<path d="M3 18h.5"/>',
    "box": '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5"/><path d="M12 13v8"/>',
    "send": '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
    "plug": '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z"/>',
    "home": '<path d="M3 10.2a2 2 0 0 1 .7-1.52l7-6a2 2 0 0 1 2.6 0l7 6a2 2 0 0 1 .7 1.52V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
            '<path d="M9.5 21v-6.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V21"/>',
    "hammer": '<path d="m15 12-8.4 8.4a2.1 2.1 0 0 1-3-3L12 9"/><path d="m18 15 4-4"/>'
              '<path d="m21.5 11.5-1.9-1.9A2 2 0 0 1 19 8.2V7l-2.3-2.3a6 6 0 0 0-4.2-1.7H9l.9.8A6.2 6.2 0 0 1 12 8.4V10l2 2h1.2'
              'a2 2 0 0 1 1.4.6l1.9 1.9"/>',
    "flask": '<path d="M9.5 2h5"/><path d="M10 2v6.4L4.3 18.6A2.3 2.3 0 0 0 6.3 22h11.4a2.3 2.3 0 0 0 2-3.4L14 8.4V2"/>'
             '<path d="M6.8 15h10.4"/>',
    "pickaxe": '<path d="M14.5 12.5 6.6 20.4a2.1 2.1 0 0 1-3-3l7.9-7.9"/>'
               '<path d="M17.7 3.7a1 1 0 0 0-1.4 0l-4.6 4.6a1 1 0 0 0 0 1.4l2.6 2.6a1 1 0 0 0 1.4 0l4.6-4.6a1 1 0 0 0 0-1.4z"/>'
               '<path d="M15.7 4.3A12.5 12.5 0 0 0 5.5 3a1 1 0 0 0 .1 1.7 22 22 0 0 1 6.3 3.4"/>'
               '<path d="M19.7 8.3A12.5 12.5 0 0 1 21 18.5a1 1 0 0 1-1.7-.1 22 22 0 0 0-3.4-6.3"/>',
    "castle": '<path d="M2 21h20"/><path d="M4 21V9h4v2h3V9h2v2h3V9h4v12"/><path d="M4 9V4h3v2h2V4h6v2h2V4h3v5"/>'
              '<path d="M10 21v-4a2 2 0 0 1 4 0v4"/>',
    "ban": '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
    "boat": '<path d="M12 2.5V17"/><path d="M12 3.5 19.5 14H12"/><path d="M10 7 5 14h5"/>'
            '<path d="M2.5 17h19l-2.1 3.1a2 2 0 0 1-1.66.9H6.26a2 2 0 0 1-1.66-.9z"/>',
    "star": '<path d="m12 2.8 2.83 5.74 6.33.92-4.58 4.47 1.08 6.3L12 17.25l-5.66 2.98 1.08-6.3-4.58-4.47 '
            '6.33-.92z"/>',
}

# filled icons (stroke="none")
_FILL = {
    "play": '<path d="M7 4.6v14.8a1.1 1.1 0 0 0 1.66.95l12.3-7.4a1.1 1.1 0 0 0 0-1.9L8.66 3.65A1.1 1.1 0 0 0 7 4.6z"/>',
    "pause": '<rect x="5.5" y="4" width="4.6" height="16" rx="1.4"/><rect x="13.9" y="4" width="4.6" height="16" rx="1.4"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2.8"/>',
    "next": '<path d="M4.5 5.4v13.2a1.1 1.1 0 0 0 1.7.92l9.6-6.6a1.1 1.1 0 0 0 0-1.84l-9.6-6.6a1.1 1.1 0 0 0-1.7.92z"/>'
            '<rect x="17" y="4.5" width="3" height="15" rx="1.3"/>',
    "dot": '<circle cx="12" cy="12" r="5"/>',
}


def svg(name, color):
    c = QColor(color)
    hexc = c.name()
    op = f'{c.alphaF():.3f}'
    if name in _FILL:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="{hexc}" fill-opacity="{op}" '
                f'stroke="none">{_FILL[name]}</g></svg>')
    body = _STROKE.get(name, _STROKE["info"])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="none" stroke="{hexc}" '
            f'stroke-opacity="{op}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</g></svg>')


@lru_cache(maxsize=512)
def renderer(name, color):
    return QSvgRenderer(QByteArray(svg(name, color).encode()))


def paint(painter, name, color, rect):
    """Draw icon `name` into `rect` with `color` (str or QColor; vector, crisp at any scale)."""
    c = QColor(color)
    if c.alpha() < 255:
        painter.save()
        painter.setOpacity(painter.opacity() * c.alphaF())
        renderer(name, c.name()).render(painter, QRectF(rect))
        painter.restore()
    else:
        renderer(name, c.name()).render(painter, QRectF(rect))


@lru_cache(maxsize=512)
def pixmap(name, color, size=18, dpr=1.25):
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer(name, color).render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name, color, size=18):
    ic = QIcon()
    for dpr in (1.0, 1.25, 1.5, 2.0):
        ic.addPixmap(pixmap(name, color, size, dpr))
    return ic


# ----------------------------------------------------------------------------- resource glyphs
def drop_path(r):
    w = r.width()
    cx = r.center().x()
    mid = r.bottom() - w / 2
    path = QPainterPath(QPointF(cx, r.top()))
    path.cubicTo(cx + w * 0.16, r.top() + r.height() * 0.2, r.right(), mid - w * 0.32, r.right(), mid)
    path.arcTo(QRectF(r.left(), r.bottom() - w, w, w), 0, -180)
    path.cubicTo(r.left(), mid - w * 0.32, cx - w * 0.16, r.top() + r.height() * 0.2, cx, r.top())
    path.closeSubpath()
    return path


def paint_resource(p, res, rect):
    """A small game-like glyph: gold coin, pink elixir drop, dark elixir drop."""
    r = QRectF(rect)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if res == "gold":
        g = QRadialGradient(r.center() - QPointF(r.width() * 0.18, r.height() * 0.2), r.width() * 0.75)
        g.setColorAt(0, QColor("#fff1b0"))
        g.setColorAt(0.45, QColor("#f8c845"))
        g.setColorAt(1, QColor("#c47a0c"))
        p.setPen(QPen(QColor("#8a5206"), max(1.0, r.width() * 0.06)))
        p.setBrush(g)
        p.drawEllipse(r.adjusted(1, 1, -1, -1))
        p.setPen(QPen(QColor(255, 244, 200, 150), max(1.0, r.width() * 0.05)))
        p.setBrush(Qt.NoBrush)
        inner = r.adjusted(r.width() * 0.24, r.height() * 0.24, -r.width() * 0.24, -r.height() * 0.24)
        p.drawEllipse(inner)
    else:
        top, bottom, edge = (("#f7a8ff", "#a62ac4", "#5d1170") if res == "elixir"
                             else ("#9d8ee0", "#2f2558", "#140f2a"))
        dr = r.adjusted(r.width() * 0.14, 0.5, -r.width() * 0.14, -0.5)
        path = drop_path(dr)
        g = QLinearGradient(dr.topLeft(), dr.bottomRight())
        g.setColorAt(0, QColor(top))
        g.setColorAt(1, QColor(bottom))
        p.setPen(QPen(QColor(edge), max(1.0, r.width() * 0.05)))
        p.setBrush(g)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 120))
        hl = QRectF(dr.left() + dr.width() * 0.22, dr.bottom() - dr.width() * 0.78, dr.width() * 0.2, dr.width() * 0.32)
        p.drawEllipse(hl)
    p.restore()

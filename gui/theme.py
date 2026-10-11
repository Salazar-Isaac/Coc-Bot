"""Colours, fonts, the Qt style sheet, the app icon and the dark Windows title bar."""

import ctypes
import os
import sys
from string import Template

from PySide6.QtCore import QByteArray, QLocale, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")

# ----------------------------------------------------------------------------- palette
BG = "#0f1220"
SIDEBAR = "#0b0e1a"
SURFACE = "#161a2d"
SURFACE_2 = "#1c2139"
SURFACE_3 = "#262c4a"
INPUT = "#121628"
BORDER = "#232944"
BORDER_STRONG = "#323a5e"
TEXT = "#e8ebf7"
TEXT_MUTED = "#98a1c3"
TEXT_DIM = "#636c91"
GOLD = "#f5b942"
GOLD_HI = "#ffd36b"
GOLD_LO = "#e48f1b"
ELIXIR = "#c03fd8"
ELIXIR_HI = "#e27df6"
DARK = "#7c6bbd"
DARK_HI = "#a898ec"
GREEN = "#2fc27a"
RED = "#ef4f5f"
AMBER = "#f5a524"
BLUE = "#5b8cff"

RESOURCES = ("gold", "elixir", "dark")
RESOURCE_NAME = {"gold": "Gold", "elixir": "Elixir", "dark": "Dark elixir"}
RESOURCE_COLOR = {"gold": GOLD, "elixir": ELIXIR_HI, "dark": DARK_HI}
RESOURCE_BAR = {"gold": (GOLD_HI, GOLD_LO), "elixir": (ELIXIR_HI, "#9b2bb8"), "dark": (DARK_HI, "#54458f")}

UI_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Arial"]
DISPLAY_FAMILIES = ["Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI", "Arial"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "Courier New"]


def font(pt=10.0, weight=QFont.Normal, display=False, mono=False):
    f = QFont()
    f.setFamilies(MONO_FAMILIES if mono else DISPLAY_FAMILIES if display else UI_FAMILIES)
    f.setPointSizeF(pt)
    f.setWeight(weight)
    return f


def qc(color, alpha=None):
    c = QColor(color)
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def mix(a, b, t):
    a, b = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t, a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t, a.alphaF() + (b.alphaF() - a.alphaF()) * t)


def rgba(color, alpha):
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


# ----------------------------------------------------------------------------- style sheet
QSS = Template("""
* { outline: 0; }
QMainWindow, QWidget#Root { background: $BG; }
QWidget#Content { background: $BG; }
QDialog, QMessageBox, QInputDialog { background: $SURFACE; }
QLabel { background: transparent; color: $TEXT; }
QLabel[role="h1"] { font-size: 19pt; font-weight: 600; color: $TEXT; }
QLabel[role="subtitle"] { color: $TEXT_MUTED; font-size: 9.5pt; }
QLabel[role="cardTitle"] { font-size: 11pt; font-weight: 600; color: $TEXT; }
QLabel[role="muted"] { color: $TEXT_MUTED; }
QLabel[role="dim"] { color: $TEXT_DIM; }
QLabel[role="small"] { color: $TEXT_MUTED; font-size: 8.5pt; }
QLabel[role="section"] { color: $TEXT_DIM; font-size: 8pt; font-weight: 700; letter-spacing: 1.2px; }
QLabel[role="caption"] { color: $TEXT_MUTED; font-size: 8pt; font-weight: 600; letter-spacing: 0.8px; }
QLabel[role="value"] { font-size: 17pt; font-weight: 600; color: $TEXT; }
QLabel[role="metric"] { font-size: 11pt; font-weight: 600; color: $TEXT; }
QLabel[role="rowTitle"] { color: $TEXT; font-size: 10pt; }
QLabel[role="rowDesc"] { color: $TEXT_MUTED; font-size: 8.75pt; }
QLabel[role="field"] { color: $TEXT_MUTED; font-size: 8.75pt; font-weight: 600; }
QLabel:disabled { color: $TEXT_DIM; }

QToolTip { background: $SURFACE_2; color: $TEXT; border: 1px solid $BORDER_STRONG; border-radius: 6px;
           padding: 6px 8px; }

QFrame#Card { background: $SURFACE; border: 1px solid $BORDER; border-radius: 14px; }
QFrame#Sidebar { background: $SIDEBAR; border: none; border-right: 1px solid $BORDER; }
QFrame#Divider { background: $BORDER; border: none; max-height: 1px; min-height: 1px; }
QFrame#Banner { border-radius: 10px; }
QFrame#Banner[kind="info"] { background: $INFO_BG; border: 1px solid $INFO_BORDER; }
QFrame#Banner[kind="warning"] { background: $WARN_BG; border: 1px solid $WARN_BORDER; }
QFrame#Banner[kind="success"] { background: $OK_BG; border: 1px solid $OK_BORDER; }
QFrame#Banner[kind="error"] { background: $ERR_BG; border: 1px solid $ERR_BORDER; }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: $INPUT; color: $TEXT; border: 1px solid $BORDER_STRONG; border-radius: 8px;
    padding: 6px 10px; min-height: 20px;
    selection-background-color: $SEL; selection-color: $TEXT;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #46507f; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:on { border-color: $GOLD; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: $TEXT_DIM; background: #12152400; border-color: $BORDER;
}
QSpinBox[dim="true"] { color: $TEXT_DIM; }
QLineEdit[role="key"] { font-family: "Cascadia Mono", "Consolas"; font-weight: 600; qproperty-alignment: AlignCenter; }
QLineEdit[role="search"] { border-radius: 9px; }

QComboBox { padding-right: 30px; combobox-popup: 0; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 28px; border: none; }
QComboBox::down-arrow { image: url($ASSETS/chevron-down.svg); width: 12px; height: 12px; }
QComboBox::down-arrow:on { image: url($ASSETS/chevron-down-gold.svg); }
QComboBox::down-arrow:disabled { image: url($ASSETS/chevron-down-dim.svg); }
QComboBox QAbstractItemView {
    background: $SURFACE_2; color: $TEXT; border: 1px solid $BORDER_STRONG; border-radius: 8px; padding: 4px;
    selection-background-color: $SURFACE_3; selection-color: $TEXT; outline: 0;
}
QComboBox QAbstractItemView::item { min-height: 30px; padding: 0 10px; border-radius: 6px; }
QComboBox QAbstractItemView::item:hover { background: $SURFACE_3; }
QComboBox QAbstractItemView::item:selected { background: $SEL_SOFT; color: $GOLD_HI; }

QSpinBox, QDoubleSpinBox { padding-right: 4px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right; width: 24px; border: none;
    border-top-right-radius: 8px; margin: 1px 1px 0 0;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border: none;
    border-bottom-right-radius: 8px; margin: 0 1px 1px 0;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: $SURFACE_3; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url($ASSETS/chevron-up.svg); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url($ASSETS/chevron-down.svg); width: 10px; height: 10px; }
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off,
QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:off { image: url($ASSETS/chevron-up-dim.svg); }
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off,
QDoubleSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:off { image: url($ASSETS/chevron-down-dim.svg); }

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget#qt_scrollarea_viewport { background: transparent; }
QWidget#ScrollContent { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 2px 2px 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0 2px 2px 2px; }
QScrollBar::handle:vertical { background: #2a3152; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:horizontal { background: #2a3152; border-radius: 4px; min-width: 36px; }
QScrollBar::handle:hover { background: #3b4473; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QTableView {
    background: transparent; alternate-background-color: $ALT_ROW; border: none; gridline-color: transparent;
    selection-background-color: $SEL_ROW; selection-color: $TEXT; color: $TEXT;
}
QTableView::item { padding: 0 10px; }
QTableView::item:selected { background: $SEL_ROW; color: $TEXT; }
QHeaderView { background: transparent; border: none; }
QHeaderView::section {
    background: $SURFACE_2; color: $TEXT_MUTED; padding: 9px 10px; border: none; border-bottom: 1px solid $BORDER;
    font-size: 8.5pt; font-weight: 600;
}
QHeaderView::section:first { border-top-left-radius: 12px; }
QHeaderView::section:last { border-top-right-radius: 12px; }
QHeaderView::section:only-one { border-top-left-radius: 12px; border-top-right-radius: 12px; }
QTableCornerButton::section { background: $SURFACE_2; border: none; }
QTableView QComboBox, QTableView QSpinBox, QTableView QDoubleSpinBox {
    background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 3px 8px; min-height: 18px;
}
QTableView QSpinBox, QTableView QDoubleSpinBox { padding-right: 8px; }
QTableView QComboBox { padding-right: 28px; }
QTableView QComboBox:hover, QTableView QSpinBox:hover, QTableView QDoubleSpinBox:hover {
    background: $INPUT; border-color: $BORDER_STRONG;
}
QTableView QComboBox:focus, QTableView QSpinBox:focus, QTableView QDoubleSpinBox:focus {
    background: $INPUT; border-color: $GOLD;
}
QTableView QLineEdit { background: $INPUT; border: 1px solid $GOLD; border-radius: 6px; padding: 2px 8px; }

QPlainTextEdit#Log {
    background: #0b0e1a; color: #cdd3ec; border: 1px solid $BORDER; border-radius: 10px; padding: 6px 4px 6px 10px;
    selection-background-color: $SEL;
}

.QPushButton {
    background: $SURFACE_2; color: $TEXT; border: 1px solid $BORDER_STRONG; border-radius: 8px;
    padding: 7px 18px; min-width: 64px;
}
.QPushButton:hover { background: $SURFACE_3; border-color: #46507f; }
.QPushButton:pressed { background: $SURFACE_2; }
.QPushButton:default { background: $GOLD; color: #241700; border: none; font-weight: 600; }
.QPushButton:default:hover { background: $GOLD_HI; }
.QPushButton:disabled { color: $TEXT_DIM; border-color: $BORDER; }
QDialogButtonBox { dialogbuttonbox-buttons-have-icons: 0; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 1px solid $BORDER_STRONG; background: $INPUT; }
QCheckBox::indicator:checked { background: $GOLD; border-color: $GOLD; image: url($ASSETS/check.svg); }

QMenu { background: $SURFACE_2; color: $TEXT; border: 1px solid $BORDER_STRONG; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 22px 6px 12px; border-radius: 6px; }
QMenu::item:selected { background: $SURFACE_3; }
QMenu::item:disabled { color: $TEXT_DIM; }
QMenu::separator { height: 1px; background: $BORDER; margin: 4px 6px; }
""")


def stylesheet():
    v = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, str)}
    v.update(
        SEL=rgba(GOLD, 0.35), SEL_SOFT=rgba(GOLD, 0.14), SEL_ROW=rgba(GOLD, 0.11), ALT_ROW="#181c31",
        INFO_BG=rgba(BLUE, 0.09), INFO_BORDER=rgba(BLUE, 0.30),
        WARN_BG=rgba(AMBER, 0.09), WARN_BORDER=rgba(AMBER, 0.32),
        OK_BG=rgba(GREEN, 0.09), OK_BORDER=rgba(GREEN, 0.30),
        ERR_BG=rgba(RED, 0.09), ERR_BORDER=rgba(RED, 0.32),
    )
    return QSS.substitute(v)


def palette():
    p = QPalette()
    roles = {
        QPalette.Window: BG, QPalette.WindowText: TEXT, QPalette.Base: INPUT, QPalette.AlternateBase: SURFACE,
        QPalette.Text: TEXT, QPalette.Button: SURFACE_2, QPalette.ButtonText: TEXT, QPalette.BrightText: "#ffffff",
        QPalette.ToolTipBase: SURFACE_2, QPalette.ToolTipText: TEXT, QPalette.PlaceholderText: TEXT_DIM,
        QPalette.Link: GOLD, QPalette.Highlight: GOLD, QPalette.HighlightedText: "#1d1300",
        QPalette.Light: SURFACE_3, QPalette.Midlight: SURFACE_2, QPalette.Mid: BORDER_STRONG, QPalette.Dark: SIDEBAR,
        QPalette.Shadow: "#000000",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(TEXT_DIM))
    return p


def apply_theme(app):
    """Fusion + dark palette + the style sheet + the app icon and font."""
    QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))   # 1,200,000 like the rest of the UI
    app.setStyle("Fusion")
    app.setPalette(palette())
    app.setFont(font(10))
    app.setStyleSheet(stylesheet())
    app.setWindowIcon(app_icon())
    app.setEffectEnabled(Qt.UI_AnimateCombo, False)


# ----------------------------------------------------------------------------- window chrome
def _colorref(color):
    c = QColor(color)
    return ctypes.c_uint(c.red() | (c.green() << 8) | (c.blue() << 16))


def style_window(widget, caption=BG):
    """Dark native title bar (Windows 10/11) coloured like the window. Harmless elsewhere."""
    if sys.platform != "win32" or widget.testAttribute(Qt.WA_DontShowOnScreen):
        return
    try:
        hwnd = ctypes.c_void_p(int(widget.winId()))
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on)):   # DWMWA_USE_IMMERSIVE_DARK_MODE
            dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(on), ctypes.sizeof(on))   # older Windows 10 builds
        for attr, color in ((35, caption), (34, BORDER), (36, TEXT)):  # caption, border, caption text (Win 11)
            ref = _colorref(color)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ref), ctypes.sizeof(ref))
    except Exception:  # noqa: BLE001 - purely cosmetic
        pass


# ----------------------------------------------------------------------------- logo / icon
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs>
 <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#2d3570"/><stop offset="1" stop-color="#151935"/></linearGradient>
 <linearGradient id="gold" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#ffe391"/><stop offset="0.55" stop-color="#f5b942"/>
  <stop offset="1" stop-color="#d9800f"/></linearGradient>
 <linearGradient id="edge" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#ffffff" stop-opacity="0.35"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
 </linearGradient>
</defs>
<rect x="2" y="2" width="60" height="60" rx="15" fill="url(#bg)"/>
<rect x="2.75" y="2.75" width="58.5" height="58.5" rx="14.25" fill="none" stroke="url(#edge)" stroke-width="1.5"/>
<path d="M32 9.5 L50.5 16.2 V30 C50.5 42.6 42.3 51.3 32 55.6 C21.7 51.3 13.5 42.6 13.5 30 V16.2 Z"
      fill="url(#gold)" stroke="#8c4f08" stroke-width="1.6" stroke-linejoin="round"/>
<path d="M35.6 17 L23.4 34.2 H31.2 L28.2 47.4 L41.2 28.8 H33.4 Z" fill="#1b2050"/>
</svg>"""


def _render_svg(svg, size, dpr=1.0):
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def logo_pixmap(size, dpr=1.0):
    return _render_svg(LOGO_SVG, size, dpr)


def app_icon():
    icon = QIcon()
    for s in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(_render_svg(LOGO_SVG, s))
    return icon


# ----------------------------------------------------------------------------- dialogs
def ask(parent, title, text):
    """Yes/No question in a dark dialog. Returns True for Yes."""
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.Yes | QMessageBox.No, parent)
    box.setDefaultButton(QMessageBox.No)
    style_window(box, SURFACE)
    return box.exec() == QMessageBox.Yes


def ask_text(parent, title, prompt):
    """Single-line text input in a dark dialog. Returns the text or None."""
    from PySide6.QtWidgets import QInputDialog
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(prompt)
    dlg.resize(460, dlg.sizeHint().height())
    style_window(dlg, SURFACE)
    return dlg.textValue() if dlg.exec() else None

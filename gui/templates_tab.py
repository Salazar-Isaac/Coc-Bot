"""Templates page: capture and test the images the bot recognises, and teach it digits."""

import os
import time

import cv2
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from bot import catalog
from bot.core import vision
from bot.core.profile import profile
from gui import icons
from gui import theme as T
from gui.components import (ROLE, Button, Card, NumberDelegate, Pill, PillDelegate, Table, Toggle, TwoLineDelegate,
                            hbox, label)
from gui.widgets import CropDialog, DoubleSpin, to_pixmap

COLS = ["Template", "How to capture", "Status", "Score now", "Threshold"]


def _item(value, flags):
    it = QTableWidgetItem("")
    it.setData(ROLE, value)
    it.setFlags(flags)
    return it


def _thr_text(v):
    return (f"{v:.2f}" if isinstance(v, float) else "", False)


def _thr_editor(parent):
    sp = DoubleSpin(parent)
    sp.setRange(0.5, 0.99)
    sp.setSingleStep(0.01)
    return sp


class PreviewBox(QWidget):
    """Screenshot preview with rounded corners (or a placeholder)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.setMinimumHeight(150)

    def set_pixmap(self, pm):
        self.pixmap = pm
        self.update()

    def heightForWidth(self, w):
        return int(w * 9 / 16)

    def hasHeightForWidth(self):
        return True

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, QColor(T.SIDEBAR))
        if self.pixmap is not None:
            p.setClipPath(path)
            pw, ph = self.pixmap.width(), self.pixmap.height()
            s = min(r.width() / pw, r.height() / ph)
            tr = QRectF(r.center().x() - pw * s / 2, r.center().y() - ph * s / 2, pw * s, ph * s)
            p.drawPixmap(tr, self.pixmap, QRectF(self.pixmap.rect()))
            p.setClipping(False)
        else:
            ic = QRectF(r.center().x() - 16, r.center().y() - 26, 32, 32)
            icons.paint(p, "camera", T.TEXT_DIM, ic)
            p.setFont(T.font(9))
            p.setPen(QColor(T.TEXT_MUTED))
            p.drawText(QRectF(r.left(), ic.bottom() + 6, r.width(), 22), Qt.AlignCenter, "No screenshot yet")
        p.setPen(QColor(T.BORDER_STRONG))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class TemplatesTab(QWidget):
    screenshot_requested = Signal()
    templates_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = None
        self.extra = []          # donate item templates that are not in the catalog
        self.rows = list(catalog.CATALOG)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.shot_btn = Button("Take screenshot", "camera", "primary", "md")
        self.capture_btn = Button("Capture selected…", "crop", "secondary", "md")
        self.test_btn = Button("Test all", "target", "secondary", "md")
        self.digits_btn = Button("Teach digits…", "hash", "secondary", "md")
        self.folder_btn = Button("Open folder", "folder", "ghost", "md")
        self.capture_btn.setToolTip("Drag a box on the screenshot around the selected template (or double-click a row)")
        self.digits_btn.setToolTip("Select one number on the screenshot and type it, to teach the resource font")
        lay.addLayout(hbox(self.shot_btn, self.capture_btn, self.test_btn, self.digits_btn, None, self.folder_btn,
                           spacing=8))

        body = QHBoxLayout()
        body.setSpacing(16)
        lay.addLayout(body, 1)

        card = Card(padding=14, spacing=10)
        self.count_pill = Pill("", T.GREEN)
        self.missing_pill = Pill("", T.RED)
        self.search = QLineEdit()
        self.search.setProperty("role", "search")
        self.search.setPlaceholderText("Filter templates")
        self.search.addAction(icons.icon("search", T.TEXT_DIM, 16), QLineEdit.LeadingPosition)
        self.search.setFixedWidth(190)
        self.only_missing = Toggle("Missing only")
        card.add(hbox(self.count_pill, self.missing_pill, None, self.search, 6, self.only_missing, spacing=8))
        t = self.table = Table(COLS, row_height=52)
        t.setEditTriggers(Table.SelectedClicked | Table.EditKeyPressed)
        t.resize_modes(1, {0: 214, 2: 104, 3: 84, 4: 80})
        self._delegates = [TwoLineDelegate(t), PillDelegate(t), NumberDelegate(t, _thr_text, _thr_editor)]
        t.setItemDelegateForColumn(0, self._delegates[0])
        t.setItemDelegateForColumn(2, self._delegates[1])
        t.setItemDelegateForColumn(4, self._delegates[2])
        t.doubleClicked.connect(lambda idx: idx.column() != 4 and self.capture_selected())
        t.itemChanged.connect(self._item_changed)
        card.add(self.table, 1)
        body.addWidget(card, 1)

        side = QVBoxLayout()
        side.setSpacing(16)
        shot = Card("Screenshot", icon="camera", padding=14, spacing=10)
        self.preview = PreviewBox()
        shot.add(self.preview)
        self.shot_info = label("Take a screenshot of the screen that shows a template, select its row, then "
                               "Capture. Required templates are bold.", "small", wrap=True)
        shot.add(self.shot_info)
        side.addWidget(shot)
        digits = Card("Digits", "Resource font, learned per profile.", icon="hash", color="#5cc8ff", padding=14,
                      spacing=10)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.digit_chips = {}
        for i, d in enumerate("0123456789"):
            chip = QLabel()
            chip.setAlignment(Qt.AlignCenter)
            chip.setFixedHeight(44)
            chip.setTextFormat(Qt.RichText)
            self.digit_chips[d] = chip
            grid.addWidget(chip, i // 5, i % 5)
        digits.add(grid)
        self.digits_info = label("", "small", wrap=True)
        digits.add(self.digits_info)
        side.addWidget(digits)
        side.addStretch(1)
        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(276)
        side.setContentsMargins(0, 0, 0, 0)
        body.addWidget(side_w)

        self.shot_btn.clicked.connect(self.screenshot_requested)
        self.capture_btn.clicked.connect(self.capture_selected)
        self.test_btn.clicked.connect(self.test_all)
        self.digits_btn.clicked.connect(self.teach_digits)
        self.folder_btn.clicked.connect(lambda: os.startfile(profile.templates))
        self.search.textChanged.connect(self._filter)
        self.only_missing.toggled.connect(self._filter)
        self.refresh()

    # ------------------------------------------------------------------ rows
    def set_extra_items(self, items):
        """Also list the donate item templates (settings["donate"]["items"]) that the catalog does not have."""
        extra, seen = [], set(catalog.KEYS)
        for it in items or []:
            if not isinstance(it, dict):
                continue
            key = (it.get("template") or "").strip()
            if key and key not in seen:
                seen.add(key)
                name = it.get("name") or key.split("/")[-1]
                extra.append((key, "Donate", f"The {name} icon in the donate window", None))
        if extra != self.extra:
            self.extra = extra
            self.refresh()

    def refresh(self, scores=None):
        vision.templates.reload()
        self.rows = list(catalog.CATALOG) + self.extra
        current = self.table.currentRow()
        t = self.table
        t.blockSignals(True)
        t.setRowCount(len(self.rows))
        have = 0
        req_missing = 0
        fixed = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        for r, (key, screen, how, required) in enumerate(self.rows):
            has = vision.templates.has(key)
            have += has
            req_missing += bool(required) and not has
            kind = "required" if required else "donate item" if required is None else ""
            t.setItem(r, 0, _item((key, f"{screen}  ·  {kind}" if kind else screen, bool(required)), fixed))
            item = QTableWidgetItem(how)
            item.setFont(T.font(9))
            item.setToolTip(how)
            item.setForeground(QColor(T.TEXT_MUTED))
            item.setFlags(fixed)
            t.setItem(r, 1, item)
            status = (("Captured", T.GREEN) if has else ("Missing", T.RED) if required
                      else ("Missing", T.AMBER) if required is None else ("Optional", T.TEXT_DIM))
            t.setItem(r, 2, _item(status, fixed))
            sc = QTableWidgetItem("")
            sc.setFlags(fixed)
            if scores and key in scores:
                s_, ok = scores[key]
                sc.setText(f"{s_:.2f}" + ("  ✓" if ok else ""))
                sc.setForeground(QColor(T.GREEN if ok else T.TEXT_DIM))
                f = sc.font()
                f.setWeight(QFont.DemiBold if ok else QFont.Normal)
                sc.setFont(f)
            t.setItem(r, 3, sc)
            thr = float(vision.templates.meta(key).get("threshold", vision.DEFAULT_THRESHOLD))
            t.setItem(r, 4, _item(thr, fixed | (Qt.ItemIsEditable if has else Qt.NoItemFlags)))
        t.blockSignals(False)
        t.viewport().update()
        if 0 <= current < len(self.rows):
            self.table.selectRow(current)
        self.count_pill.set(f"{have} / {len(self.rows)} captured")
        self.missing_pill.set(f"{req_missing} required missing")
        self.missing_pill.setVisible(req_missing > 0)

        counts = {d: 0 for d in "0123456789"}
        if os.path.isdir(profile.digits):
            for n in os.listdir(profile.digits):
                if n[:1] in counts:
                    counts[n[0]] += 1
        for d, chip in self.digit_chips.items():
            c = counts[d]
            color = T.GREEN if c else T.RED
            chip.setText(f"<div style='font-family:Cascadia Mono,Consolas; font-size:13pt; font-weight:700; "
                         f"color:{T.TEXT}'>{d}</div><div style='font-size:7.5pt; color:{color}'>{c}</div>")
            chip.setStyleSheet(f"QLabel {{ background: {T.rgba(color, 0.07)}; border: 1px solid "
                               f"{T.rgba(color, 0.35)}; border-radius: 8px; }}")
        missing = [d for d, c in counts.items() if c == 0]
        self.digits_info.setText(f"Missing digits: {', '.join(missing)}. Use “Teach digits…”." if missing
                                 else "All digits learned ✓")
        self._filter()
        self.templates_changed.emit()

    def _item_changed(self, item):
        if item.column() == 4 and 0 <= item.row() < len(self.rows):
            vision.templates.set_meta(self.rows[item.row()][0], threshold=round(float(item.data(ROLE)), 2))

    def _filter(self, *_):
        q = self.search.text().strip().lower()
        only = self.only_missing.isChecked()
        for r, (key, screen, how, _req) in enumerate(self.rows):
            hide = (only and vision.templates.has(key)) or (q and q not in f"{key} {screen} {how}".lower())
            self.table.setRowHidden(r, bool(hide))

    def show_missing(self):
        self.only_missing.setChecked(True)

    # ------------------------------------------------------------------ actions
    def set_frame(self, frame):
        self.frame = frame
        self.preview.set_pixmap(to_pixmap(frame))
        self.shot_info.setText(f"Screenshot {time.strftime('%H:%M:%S')}  ·  {frame.shape[1]}×{frame.shape[0]}. "
                               "Select a row, then Capture.")
        self.test_all()

    def _need_frame(self):
        if self.frame is None:
            box = QMessageBox(QMessageBox.Information, "Screenshot needed", "Take a screenshot from the game first.",
                              QMessageBox.Ok, self)
            T.style_window(box, T.SURFACE)
            box.exec()
            return False
        return True

    def capture_selected(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self.rows) or not self._need_frame():
            return
        key, screen, how, _ = self.rows[r]
        old = vision.templates.meta(key).get("box")
        dlg = CropDialog(self.frame, f"Capture {key}", f"{how}  ({screen} screen)", self, box=old)
        if dlg.exec():
            thr = vision.templates.meta(key).get("threshold", vision.DEFAULT_THRESHOLD)
            vision.templates.save(key, self.frame, dlg.result_box(), threshold=thr)
            self.test_all()

    def test_all(self):
        if self.frame is None:
            self.refresh()
            return
        vision.templates.reload()
        scores = {}
        for key, *_ in self.rows:
            if vision.templates.has(key):
                try:
                    m = vision.find(self.frame, key, threshold=0, any_brightness=True)
                    scores[key] = (m.score if m else 0.0, vision.find(self.frame, key) is not None)
                except Exception:  # noqa: BLE001
                    scores[key] = (0.0, False)
        self.refresh(scores)

    def teach_digits(self):
        if not self._need_frame():
            return
        dlg = CropDialog(self.frame, "Teach digits",
                         "ONE number, e.g. your gold at the top right (only the digits, not the icon)",
                         self, ask_value="Type exactly the number you see (digits only):")
        if not dlg.exec():
            return
        truth = "".join(ch for ch in dlg.result_value() if ch.isdigit())
        box = dlg.result_box()
        glyphs = vision.digits.glyphs(self.frame, box)
        if len(glyphs) != len(truth):
            box_ = QMessageBox(QMessageBox.Warning, "Did not match",
                               f"Found {len(glyphs)} digits in the box but you typed {len(truth)}. "
                               "Draw the box a bit tighter around the number and try again.", QMessageBox.Ok, self)
            T.style_window(box_, T.SURFACE)
            box_.exec()
            return
        stamp = time.strftime("%Y%m%d%H%M%S")
        for i, ((img, _), d) in enumerate(zip(glyphs, truth)):
            cv2.imencode(".png", img)[1].tofile(os.path.join(profile.digits, f"{d}_{stamp}_{i}.png"))
        vision.digits.reload()
        self.refresh()
        self.digits_info.setText(f"Saved {len(truth)} digit images from {truth}. ✓")

    def set_running(self, running):
        for b in (self.shot_btn, self.capture_btn, self.digits_btn):
            b.setEnabled(not running)

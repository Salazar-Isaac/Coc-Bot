"""Templates tab: capture and test the images the bot recognises, and teach it digits."""

import os
import time

import cv2
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from bot import catalog
from bot.core import vision
from bot.core.profile import profile
from gui.widgets import CropDialog, to_pixmap

COLS = ["Template", "Screen", "How to capture", "Status", "Score now", "Threshold"]
GREEN, RED, GREY = QColor(30, 140, 60), QColor(200, 50, 50), QColor(120, 120, 120)


class TemplatesTab(QWidget):
    screenshot_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.shot_btn = QPushButton("📷  Take screenshot from the game")
        self.capture_btn = QPushButton("Capture selected template…")
        self.test_btn = QPushButton("Test all on screenshot")
        self.digits_btn = QPushButton("Teach digits…")
        self.folder_btn = QPushButton("Open folder")
        for b in (self.shot_btn, self.capture_btn, self.test_btn, self.digits_btn):
            top.addWidget(b)
        top.addStretch(1)
        top.addWidget(self.folder_btn)
        lay.addLayout(top)
        self.info = QLabel("Take a screenshot of the screen that shows a template, select its row, "
                           "then Capture. Required templates are bold.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        body = QHBoxLayout()
        self.table = QTableWidget(len(catalog.CATALOG), len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        for c in (0, 1, 3, 4, 5):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(lambda *_: self.capture_selected())
        body.addWidget(self.table, 3)

        side = QVBoxLayout()
        self.preview = QLabel("No screenshot yet")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(384, 216)
        self.preview.setStyleSheet("background:#222; color:#aaa;")
        side.addWidget(self.preview)
        self.shot_info = QLabel("")
        side.addWidget(self.shot_info)
        self.digits_info = QLabel("")
        self.digits_info.setWordWrap(True)
        side.addWidget(self.digits_info)
        side.addStretch(1)
        body.addLayout(side, 1)
        lay.addLayout(body, 1)

        self.shot_btn.clicked.connect(self.screenshot_requested)
        self.capture_btn.clicked.connect(self.capture_selected)
        self.test_btn.clicked.connect(self.test_all)
        self.digits_btn.clicked.connect(self.teach_digits)
        self.folder_btn.clicked.connect(lambda: os.startfile(profile.templates))
        self.refresh()

    # ------------------------------------------------------------------ table
    def refresh(self, scores=None):
        vision.templates.reload()
        for r, (key, screen, how, required) in enumerate(catalog.CATALOG):
            item = QTableWidgetItem(key)
            if required:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.table.setItem(r, 0, item)
            self.table.setItem(r, 1, QTableWidgetItem(screen))
            self.table.setItem(r, 2, QTableWidgetItem(how))
            has = vision.templates.has(key)
            st = QTableWidgetItem("✓ captured" if has else ("✗ missing" if required else "– optional"))
            st.setForeground(GREEN if has else (RED if required else GREY))
            self.table.setItem(r, 3, st)
            sc = QTableWidgetItem("")
            if scores and key in scores:
                s, ok = scores[key]
                sc.setText(f"{s:.2f}" + ("  FOUND" if ok else ""))
                sc.setForeground(GREEN if ok else GREY)
            self.table.setItem(r, 4, sc)
            thr = QDoubleSpinBox()
            thr.setRange(0.5, 0.99)
            thr.setSingleStep(0.01)
            thr.setValue(vision.templates.meta(key).get("threshold", vision.DEFAULT_THRESHOLD))
            thr.setEnabled(has)
            thr.valueChanged.connect(lambda v, k=key: vision.templates.set_meta(k, threshold=round(v, 2)))
            self.table.setCellWidget(r, 5, thr)
        counts = {d: 0 for d in "0123456789"}
        if os.path.isdir(profile.digits):
            for n in os.listdir(profile.digits):
                if n[:1] in counts:
                    counts[n[0]] += 1
        missing = [d for d, c in counts.items() if c == 0]
        self.digits_info.setText("Digit images: " + "  ".join(f"{d}:{c}" for d, c in counts.items())
                                 + (f"\nMissing digits: {', '.join(missing)}" if missing else "\nAll digits learned ✓"))

    # ------------------------------------------------------------------ actions
    def set_frame(self, frame):
        self.frame = frame
        pm = to_pixmap(frame).scaled(self.preview.width(), self.preview.height(), Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
        self.preview.setPixmap(pm)
        self.shot_info.setText(f"Screenshot {time.strftime('%H:%M:%S')}  ({frame.shape[1]}x{frame.shape[0]})")
        self.test_all()

    def _need_frame(self):
        if self.frame is None:
            QMessageBox.information(self, "Screenshot needed", "Take a screenshot from the game first.")
            return False
        return True

    def capture_selected(self):
        r = self.table.currentRow()
        if r < 0 or not self._need_frame():
            return
        key, screen, how, _ = catalog.CATALOG[r]
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
        for key in catalog.KEYS:
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
            QMessageBox.warning(self, "Did not match",
                                f"Found {len(glyphs)} digits in the box but you typed {len(truth)}. "
                                "Draw the box a bit tighter around the number and try again.")
            return
        stamp = time.strftime("%Y%m%d%H%M%S")
        for i, ((img, _), d) in enumerate(zip(glyphs, truth)):
            cv2.imencode(".png", img)[1].tofile(os.path.join(profile.digits, f"{d}_{stamp}_{i}.png"))
        vision.digits.reload()
        self.refresh()
        QMessageBox.information(self, "Digits learned", f"Saved {len(truth)} digit images from {truth}.")

    def set_running(self, running):
        for b in (self.shot_btn, self.capture_btn, self.digits_btn):
            b.setEnabled(not running)

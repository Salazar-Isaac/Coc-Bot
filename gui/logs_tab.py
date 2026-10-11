"""Logs page: the full session log with level filter and search. Also provides LogView (used on the dashboard)."""

import logging
import os
from collections import deque

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from bot import paths
from gui import icons
from gui import theme as T
from gui.components import Button, Card, IconButton, Pill, Segmented, hbox

LEVEL_COLORS = {logging.DEBUG: T.TEXT_DIM, logging.INFO: "#cdd3ec", logging.WARNING: T.AMBER,
                logging.ERROR: T.RED, logging.CRITICAL: T.RED}


class LogView(QPlainTextEdit):
    """Read-only, monospace, coloured by level; follows new lines only while scrolled to the bottom."""

    def __init__(self, max_lines=3000, parent=None):
        super().__init__(parent)
        self.setObjectName("Log")
        self.setReadOnly(True)
        self.setMaximumBlockCount(max_lines)
        self.setFont(T.font(9, mono=True))
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setPlaceholderText("Nothing logged yet.")
        self._time_fmt = QTextCharFormat()
        self._time_fmt.setForeground(QColor(T.TEXT_DIM))
        self._fmts = {}
        for lvl, color in LEVEL_COLORS.items():
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if lvl >= logging.ERROR:
                f.setFontWeight(QFont.DemiBold)
            self._fmts[lvl] = f

    def _fmt(self, level):
        for lvl in (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO):
            if level >= lvl:
                return self._fmts[lvl]
        return self._fmts[logging.DEBUG]

    def append(self, msg, level=logging.INFO, follow=None):
        sb = self.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4 if follow is None else follow
        cur = QTextCursor(self.document())
        cur.movePosition(QTextCursor.End)
        if not self.document().isEmpty():
            cur.insertBlock()
        head, sep, rest = msg.partition("  ")
        if sep and len(head) == 8 and head[2:3] == ":":
            cur.insertText(head + "  ", self._time_fmt)
            cur.insertText(rest, self._fmt(level))
        else:
            cur.insertText(msg, self._fmt(level))
        if at_bottom:
            sb.setValue(sb.maximum())


class LogsTab(QWidget):
    """Every log line of this session; filter by level and text."""

    seen = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = deque(maxlen=6000)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        card = Card(padding=16)
        self.level = Segmented([(logging.INFO, "All"), (logging.WARNING, "Warnings"), (logging.ERROR, "Errors")])
        self.level.setFixedWidth(270)
        self.search = QLineEdit()
        self.search.setProperty("role", "search")
        self.search.setPlaceholderText("Search the log")
        self.search.addAction(icons.icon("search", T.TEXT_DIM, 16), QLineEdit.LeadingPosition)
        self.search.setFixedWidth(260)
        self.count = Pill("0 lines", T.TEXT_MUTED)
        copy = IconButton("copy", "Copy the visible lines")
        clear = Button("Clear", "trash", "ghost", "sm")
        folder = Button("Open logs folder", "folder", "secondary", "sm")
        card.add(hbox(self.level, self.search, self.count, None, copy, clear, folder, spacing=10))
        self.view = LogView(6000)
        card.add(self.view, 1)
        lay.addWidget(card)
        self.level.currentIndexChanged.connect(self._rebuild)
        self.search.textChanged.connect(self._rebuild)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.view.toPlainText()))
        clear.clicked.connect(self.clear)
        folder.clicked.connect(lambda: os.startfile(paths.LOGS))

    def _match(self, msg, level):
        q = self.search.text().strip().lower()
        return level >= self.level.currentData() and (not q or q in msg.lower())

    def append_log(self, msg, level):
        self.entries.append((msg, level))
        if self._match(msg, level):
            self.view.append(msg, level)
            self._count()

    def _rebuild(self, *_):
        self.view.setUpdatesEnabled(False)
        self.view.clear()
        for msg, level in self.entries:
            if self._match(msg, level):
                self.view.append(msg, level, follow=False)
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())
        self.view.setUpdatesEnabled(True)
        self._count()

    def _count(self):
        n = self.view.document().blockCount() if not self.view.document().isEmpty() else 0
        self.count.set(f"{n:,} lines")

    def clear(self):
        self.entries.clear()
        self.view.clear()
        self._count()

    def showEvent(self, e):
        self.seen.emit()
        super().showEvent(e)

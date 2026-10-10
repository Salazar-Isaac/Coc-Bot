"""Donate tab (settings for the Loot + Donate and Donate only modes)."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from gui.widgets import BigSpin


class DonateTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        note = QLabel("The donation modes are the next build step: the clan chat, donate window and "
                      "Clan Castle request screens still need to be mapped. These settings are saved now "
                      "and will be used by them.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a5a00; background:#fff4d6; padding:8px; border-radius:4px;")
        lay.addWidget(note)
        box = QGroupBox("Donation cycle")
        f = QFormLayout(box)
        self.min_keep = BigSpin(maximum=100_000_000, step=500_000)
        f.addRow("Main donates while its elixir is above:", self.min_keep)
        self.rounds = QSpinBox()
        self.rounds.setRange(0, 999)
        self.rounds.setSpecialValueText("until elixir runs low")
        f.addRow("Request / donate rounds:", self.rounds)
        self.remove_cc = QCheckBox("Feeders empty their Clan Castle before requesting")
        f.addRow(self.remove_cc)
        self.request_text = QLineEdit()
        self.request_text.setPlaceholderText("(optional) text sent with the request")
        f.addRow("Request message:", self.request_text)
        lay.addWidget(box)
        lay.addStretch(1)
        self.min_keep.valueChanged.connect(self.changed)
        self.rounds.valueChanged.connect(self.changed)
        self.remove_cc.toggled.connect(self.changed)
        self.request_text.textChanged.connect(self.changed)

    def load(self, settings, accounts):
        d = settings["donate"]
        self.min_keep.setValue(d.get("min_elixir_keep", 4_000_000))
        self.rounds.setValue(d.get("rounds", 0))
        self.remove_cc.setChecked(d.get("remove_cc_before_request", True))
        self.request_text.setText(d.get("request_text", ""))

    def apply(self, settings, accounts):
        d = settings["donate"]
        d["min_elixir_keep"] = self.min_keep.value()
        d["rounds"] = self.rounds.value()
        d["remove_cc_before_request"] = self.remove_cc.isChecked()
        d["request_text"] = self.request_text.text()

    def set_running(self, running):
        self.setEnabled(not running)

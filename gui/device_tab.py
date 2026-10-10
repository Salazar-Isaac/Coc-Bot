"""Device & Settings tab: where the game runs, screen profile, hotkeys."""

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget)

from bot import paths
from bot.core.devices import EMULATOR_PORTS, find_adb, list_adb_devices
from bot.core.profile import Profile


class DeviceTab(QWidget):
    changed = Signal()
    test_requested = Signal()
    new_profile_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        right = QVBoxLayout()
        root.addLayout(left, 1)
        root.addLayout(right, 1)

        dev_box = QGroupBox("Where does Clash of Clans run?")
        dl = QVBoxLayout(dev_box)
        self.pc_radio = QRadioButton("Google Play Games on this PC")
        self.adb_radio = QRadioButton("Android over ADB (BlueStacks, LDPlayer, MuMu, Nox or a phone)")
        dl.addWidget(self.pc_radio)
        dl.addWidget(self.adb_radio)
        self.pc_radio.toggled.connect(self._type_changed)

        self.pc_box = QGroupBox("Google Play Games")
        pf = QFormLayout(self.pc_box)
        self.shortcut = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_shortcut)
        r = QHBoxLayout()
        r.addWidget(self.shortcut, 1)
        r.addWidget(browse)
        pf.addRow("Game shortcut (.lnk):", r)
        self.window_title = QLineEdit()
        pf.addRow("Window title starts with:", self.window_title)
        dl.addWidget(self.pc_box)

        self.adb_box = QGroupBox("ADB")
        af = QFormLayout(self.adb_box)
        self.adb_path = QLineEdit()
        self.adb_path.setPlaceholderText("auto (C:\\platform-tools\\adb.exe, C:\\scrcpy\\adb.exe, PATH)")
        af.addRow("adb.exe:", self.adb_path)
        self.serial = QComboBox()
        self.serial.setEditable(True)
        detect = QPushButton("Detect")
        detect.clicked.connect(self._detect)
        r2 = QHBoxLayout()
        r2.addWidget(self.serial, 1)
        r2.addWidget(detect)
        af.addRow("Device:", r2)
        self.scrcpy_dir = QLineEdit()
        af.addRow("scrcpy folder (for zoom-out):", self.scrcpy_dir)
        self.adb_info = QLabel("Emulator tip: set the emulator to 1920x1080 so it can share the PC templates.")
        self.adb_info.setWordWrap(True)
        self.adb_info.setStyleSheet("font-style:italic;")
        af.addRow(self.adb_info)
        dl.addWidget(self.adb_box)

        self.test_btn = QPushButton("Test connection (take a screenshot)")
        self.test_btn.clicked.connect(self.test_requested)
        dl.addWidget(self.test_btn)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        dl.addWidget(self.test_result)
        left.addWidget(dev_box)
        left.addStretch(1)

        prof_box = QGroupBox("Screen profile (templates, digits and click points)")
        pl = QFormLayout(prof_box)
        self.profile = QComboBox()
        new_prof = QPushButton("New profile from the device…")
        new_prof.clicked.connect(self.new_profile_requested)
        r3 = QHBoxLayout()
        r3.addWidget(self.profile, 1)
        r3.addWidget(new_prof)
        pl.addRow("Profile:", r3)
        right.addWidget(prof_box)

        hk_box = QGroupBox("Hotkeys (work while the game is in front)")
        hf = QFormLayout(hk_box)
        self.hotkeys = {}
        for k, label in (("continue", "Continue"), ("pause", "Pause / resume"), ("stop", "Stop")):
            e = QLineEdit()
            e.setMaximumWidth(80)
            self.hotkeys[k] = e
            hf.addRow(label + ":", e)
        right.addWidget(hk_box)

        misc = QGroupBox("Other")
        ml = QVBoxLayout(misc)
        self.minimize = QCheckBox("Minimize this window when the bot starts")
        self.error_shots = QCheckBox("Save a screenshot when something goes wrong (logs/errors)")
        ml.addWidget(self.minimize)
        ml.addWidget(self.error_shots)
        open_logs = QPushButton("Open logs folder")
        open_logs.clicked.connect(lambda: os.startfile(paths.LOGS))
        ml.addWidget(open_logs)
        right.addWidget(misc)
        right.addStretch(1)

        for w in (self.shortcut, self.window_title, self.adb_path, self.scrcpy_dir, *self.hotkeys.values()):
            w.textChanged.connect(self.changed)
        self.serial.editTextChanged.connect(self.changed)
        self.profile.currentIndexChanged.connect(self.changed)
        self.minimize.toggled.connect(self.changed)
        self.error_shots.toggled.connect(self.changed)

    def _type_changed(self, *_):
        pc = self.pc_radio.isChecked()
        self.pc_box.setVisible(pc)
        self.adb_box.setVisible(not pc)
        self.changed.emit()

    def _browse_shortcut(self):
        path, _ = QFileDialog.getOpenFileName(self, "Clash of Clans shortcut", os.path.dirname(self.shortcut.text()),
                                              "Shortcuts (*.lnk);;All files (*)")
        if path:
            self.shortcut.setText(path)

    def _detect(self):
        adb = find_adb(self.adb_path.text().strip())
        if not adb:
            self.test_result.setText("adb.exe not found")
            return
        found = list_adb_devices(adb)
        current = self.serial.currentText()
        self.serial.clear()
        self.serial.addItems(found)
        for name, addr in EMULATOR_PORTS.items():
            if addr not in found:
                self.serial.addItem(addr)
                self.serial.setItemData(self.serial.count() - 1, name)
        self.serial.setCurrentText(found[0] if found else current)
        self.test_result.setText(f"Connected now: {', '.join(found) if found else 'none'}. "
                                 "Emulator addresses added to the list.")

    def load(self, settings, accounts):
        d = settings["device"]
        (self.adb_radio if d["type"] == "adb" else self.pc_radio).setChecked(True)
        self.shortcut.setText(d.get("shortcut_path", ""))
        self.window_title.setText(d.get("window_title", "Clash of Clans"))
        self.adb_path.setText(d.get("adb_path", ""))
        self.serial.setCurrentText(d.get("adb_serial", ""))
        self.scrcpy_dir.setText(d.get("scrcpy_dir", ""))
        self.reload_profiles(settings.get("profile"))
        for k, e in self.hotkeys.items():
            e.setText(settings["hotkeys"].get(k, ""))
        self.minimize.setChecked(settings.get("minimize_on_start", True))
        self.error_shots.setChecked(settings.get("save_error_screenshots", True))
        self._type_changed()

    def reload_profiles(self, selected=None):
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItems(Profile.available())
        if selected:
            self.profile.setCurrentText(selected)
        self.profile.blockSignals(False)

    def apply(self, settings, accounts):
        d = settings["device"]
        d["type"] = "adb" if self.adb_radio.isChecked() else "pc"
        d["shortcut_path"] = self.shortcut.text().strip()
        d["window_title"] = self.window_title.text().strip() or "Clash of Clans"
        d["adb_path"] = self.adb_path.text().strip()
        d["adb_serial"] = self.serial.currentText().strip()
        d["scrcpy_dir"] = self.scrcpy_dir.text().strip()
        settings["profile"] = self.profile.currentText() or settings.get("profile")
        settings["hotkeys"] = {k: e.text().strip().lower() for k, e in self.hotkeys.items()}
        settings["minimize_on_start"] = self.minimize.isChecked()
        settings["save_error_screenshots"] = self.error_shots.isChecked()

    def set_running(self, running):
        self.setEnabled(not running)

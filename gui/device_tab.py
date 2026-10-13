"""Device & hotkeys: where the game runs, screen profile, hotkeys and behaviour."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFileDialog, QLineEdit, QVBoxLayout, QWidget

from bot import paths
from bot.core.devices import EMULATOR_PORTS, find_adb, adb_devices
from bot.core.profile import Profile
from gui import icons
from gui import theme as T
from gui.components import Banner, Button, Card, ChoiceCard, Columns, SettingRow, Toggle, divider, field, hbox, label
from gui.widgets import Combo


class DeviceTab(QWidget):
    changed = Signal()
    test_requested = Signal()
    new_profile_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        cols = Columns()
        root.addWidget(cols)

        # --- device ---
        dev = Card("Where does Clash of Clans run?", icon="plug")
        self.pc_card = ChoiceCard("Google Play Games", "On this PC: the bot clicks in the game window", "monitor",
                                  T.GOLD, lines=2)
        self.adb_card = ChoiceCard("Android over ADB", "BlueStacks, LDPlayer, MuMu, Nox or a phone", "phone",
                                   "#5cc8ff", lines=2)
        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        self.type_group.addButton(self.pc_card)
        self.type_group.addButton(self.adb_card)
        dev.add(hbox(self.pc_card, self.adb_card, spacing=12))
        self.pc_card.toggled.connect(self._type_changed)

        self.pc_box = QWidget()
        pl = QVBoxLayout(self.pc_box)
        pl.setContentsMargins(0, 4, 0, 0)
        pl.setSpacing(12)
        self.shortcut = QLineEdit()
        browse = Button("Browse…", "folder", "secondary")
        browse.clicked.connect(self._browse_shortcut)
        pl.addWidget(field("Game shortcut (.lnk)", hbox(self.shortcut, browse, spacing=8),
                           "Used to start the game when it is not running."))
        self.window_title = QLineEdit()
        pl.addWidget(field("Window title starts with", self.window_title))
        dev.add(self.pc_box)

        self.adb_box = QWidget()
        al = QVBoxLayout(self.adb_box)
        al.setContentsMargins(0, 4, 0, 0)
        al.setSpacing(12)
        self.adb_path = QLineEdit()
        self.adb_path.setPlaceholderText("auto (C:\\platform-tools\\adb.exe, C:\\scrcpy\\adb.exe, PATH)")
        al.addWidget(field("adb.exe", self.adb_path))
        self.serial = Combo(editable=True)
        self.serial.lineEdit().setPlaceholderText("auto: the emulator that is running")
        detect = Button("Detect", "search", "secondary")
        detect.clicked.connect(self._detect)
        al.addWidget(field("Device", hbox(self.serial, detect, spacing=8),
                           "Empty = the one connected device is used."))
        al.addWidget(Banner("Emulator: set it to 1920×1080 and switch on ADB in its settings. Only adb is used "
                            "(screenshots + taps): nothing is mirrored or recorded and your PC's mouse stays free.",
                            "info"))
        dev.add(self.adb_box)

        dev.add(divider())
        self.test_btn = Button("Test connection", "camera", "outline")
        self.test_btn.setToolTip("Connects to the device and takes a screenshot")
        self.test_btn.clicked.connect(self.test_requested)
        self.test_icon = label()
        self.test_icon.setFixedSize(18, 18)
        self.test_result = label("Takes one screenshot to check that the bot can see the game.", "rowDesc", wrap=True)
        dev.add(hbox(self.test_btn, 6, self.test_icon, self.test_result, spacing=8))
        self.test_icon.hide()
        cols.add(dev, 0)

        # --- profile ---
        prof = Card("Screen profile", "Templates, digits and click points for one screen size.", icon="layers",
                    color=T.ELIXIR_HI)
        self.profile = Combo()
        new_prof = Button("New from device…", "plus", "secondary", "sm")
        new_prof.setToolTip("Creates an empty profile with the size of the device screen")
        new_prof.clicked.connect(self.new_profile_requested)
        prof.add(hbox(self.profile, new_prof, spacing=8))
        cols.add(prof, 0)

        # --- hotkeys ---
        hk = Card("Hotkeys", "Work while the game is in front.", icon="keyboard", color="#5cc8ff")
        self.hotkeys = {}
        for i, (k, title, desc) in enumerate((("continue", "Continue", "After “Wait for me”"),
                                              ("pause", "Pause / resume", "Use the game, then resume"),
                                              ("stop", "Stop", "Ends the run"))):
            e = QLineEdit()
            e.setProperty("role", "key")
            e.setFixedWidth(84)
            e.setMaxLength(12)
            self.hotkeys[k] = e
            if i:
                hk.add(divider())
            hk.add(SettingRow(title, desc, e))
        cols.add(hk, 1)

        # --- behaviour ---
        misc = Card("Behaviour", icon="sliders", color=T.GREEN)
        self.minimize = Toggle()
        self.error_shots = Toggle()
        misc.add(SettingRow("Minimize this window on start", "Only with Google Play Games on this PC",
                            self.minimize))
        misc.add(divider())
        misc.add(SettingRow("Save a screenshot when something goes wrong", "Stored in logs/errors",
                            self.error_shots))
        misc.add(divider())
        open_logs = Button("Open logs folder", "folder", "secondary", "sm")
        open_logs.clicked.connect(lambda: os.startfile(paths.LOGS))
        misc.add(SettingRow("Logs", "bot.log and error screenshots", open_logs))
        cols.add(misc, 1)

        for w in (self.shortcut, self.window_title, self.adb_path, *self.hotkeys.values()):
            w.textChanged.connect(self.changed)
        self.serial.editTextChanged.connect(self.changed)
        self.profile.currentIndexChanged.connect(self.changed)
        self.minimize.toggled.connect(self.changed)
        self.error_shots.toggled.connect(self.changed)

    def _type_changed(self, *_):
        pc = self.pc_card.isChecked()
        self.pc_box.setVisible(pc)
        self.adb_box.setVisible(not pc)
        self.changed.emit()

    def _browse_shortcut(self):
        path, _ = QFileDialog.getOpenFileName(self, "Clash of Clans shortcut", os.path.dirname(self.shortcut.text()),
                                              "Shortcuts (*.lnk);;All files (*)")
        if path:
            self.shortcut.setText(path)

    def set_result(self, text, ok=True):
        """Show the outcome of 'Test connection' (or another device check)."""
        icon, color = ("check-circle", T.GREEN) if ok else ("x-circle", T.RED)
        self.test_icon.setPixmap(icons.pixmap(icon, color, 18))
        self.test_icon.show()
        self.test_result.setText(text)
        self.test_result.setStyleSheet(f"color: {T.mix(color, T.TEXT, 0.5).name()};")

    def _detect(self):
        adb = find_adb(self.adb_path.text().strip())
        if not adb:
            self.set_result("adb.exe not found", ok=False)
            return
        devices = adb_devices(adb)
        found = [s for s, st, _ in devices if st == "device"]
        current = self.serial.currentText()
        self.serial.clear()
        for s, st, model in devices:
            self.serial.addItem(s)
            self.serial.setItemData(self.serial.count() - 1, f"{model or 'device'} ({st})", Qt.ToolTipRole)
        for name, addr in EMULATOR_PORTS.items():
            if addr not in found:
                self.serial.addItem(addr)
                self.serial.setItemData(self.serial.count() - 1, name, Qt.ToolTipRole)
        self.serial.setCurrentText(found[0] if len(found) == 1 else current)
        unauthorized = [s for s, st, _ in devices if st == "unauthorized"]
        if found:
            text = "Connected: " + ", ".join(f"{m or '?'} ({s})" for s, st, m in devices if st == "device")
        elif unauthorized:
            text = "A device has not allowed this PC yet (Allow USB debugging?)"
        else:
            text = "No emulator found (is it running with ADB switched on?)"
        self.set_result(text, ok=bool(found))

    def load(self, settings, accounts):
        d = settings["device"]
        (self.adb_card if d.get("type") == "adb" else self.pc_card).setChecked(True)
        self.shortcut.setText(d.get("shortcut_path", ""))
        self.shortcut.setCursorPosition(0)
        self.shortcut.setToolTip(self.shortcut.text())
        self.window_title.setText(d.get("window_title", "Clash of Clans"))
        self.adb_path.setText(d.get("adb_path", ""))
        self.serial.setCurrentText(d.get("adb_serial", ""))
        self.reload_profiles(settings.get("profile"))
        for k, e in self.hotkeys.items():
            e.setText(settings.get("hotkeys", {}).get(k, "").upper())
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
        d["type"] = "adb" if self.adb_card.isChecked() else "pc"
        d["shortcut_path"] = self.shortcut.text().strip()
        d["window_title"] = self.window_title.text().strip() or "Clash of Clans"
        d["adb_path"] = self.adb_path.text().strip()
        d["adb_serial"] = self.serial.currentText().strip()
        settings["profile"] = self.profile.currentText() or settings.get("profile")
        settings["hotkeys"] = {k: e.text().strip().lower() for k, e in self.hotkeys.items()}
        settings["minimize_on_start"] = self.minimize.isChecked()
        settings["save_error_screenshots"] = self.error_shots.isChecked()

    def set_running(self, running):
        self.setEnabled(not running)

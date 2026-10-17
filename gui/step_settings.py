"""The settings of each function of the flow (bot/flow.py STEPS), "Base choice per Town Hall" and "General".

Each class follows the page pattern of the window: load(settings, accounts) / apply(settings, accounts) /
changed / set_running. apply() only writes the keys it shows, so unknown keys in settings are kept."""

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from bot import config
from bot.flow import (BB_BUILDINGS, BB_RESEARCH, DEFAULT_HOME_BUILDINGS, DEFAULT_MIN_LOOT_TH, DEFAULT_STEPS,
                      HOME_BUILDINGS, HOME_RESEARCH)
from gui import icons
from gui import theme as T
from gui.components import (Banner, Card, ChipToggle, Columns, FoldCard, ResourceIcon, Segmented,
                            SettingRow, Toggle, divider, hbox, label)
from gui.fields import AccountsField, OrderList, PlanPicker, block
from gui.widgets import BigSpin, Combo, Spin

NIGHT = "#8c9bff"          # accent of the Builder Base
STEP_COLORS = {"attack_all": T.GOLD, "loot_current": "#5cc8ff", "donate": T.ELIXIR_HI, "bb_attack": NIGHT,
               "home_upgrade": T.GOLD_HI, "walls": T.ELIXIR_HI, "bb_upgrade": NIGHT, "raid": "#ff9f43", "home_research": T.GREEN, "bb_research": NIGHT}
NAMES = T.RESOURCE_NAME
TH_LEVELS = [str(t) for t in range(19, 10, -1)]
LOOT_DEFAULTS = config.DEFAULT_SETTINGS["loot"]
BUILDER_DEFAULTS = config.DEFAULT_SETTINGS["builder"]
DEFAULT_MARGIN = dict(getattr(config, "DEFAULT_MARGIN", LOOT_DEFAULTS.get("full_margin", {})))

WHEN_FULL = [("switch", "Switch account", "Go on with the next account in the list"),
             ("wait", "Wait for me", "Stay on the full account: spend the resources yourself, then press Continue"),
             ("stop", "Stop the run", "End the run as soon as an account is full")]
WHEN_DONE = [("nothing", "Do nothing", "Leave the game open"),
             ("close_game", "Close the game", "Close Clash of Clans when the run ends"),
             ("shutdown", "Shut down the PC", "Shut down 60 seconds after the run (can be cancelled)"),
             ("sleep", "Put the PC to sleep", "Sleep when the run ends")]
BB_ARMIES = [("auto", "Auto: P.E.K.K.A, else Sneaky Archer",
              "Best unlocked: P.E.K.K.A when the Builder Base has it, otherwise Sneaky Archers"),
             ("keep", "Keep each account's army", "Never change the Builder Base army"),
             ("pekka", "P.E.K.K.A"), ("night_witch", "Night Witch"), ("archer", "Sneaky Archer"),
             ("barbarian", "Raged Barbarian"), ("boxer_giant", "Boxer Giant"), ("bomber", "Bomber"),
             ("cannon_cart", "Cannon Cart"), ("drop_ship", "Drop Ship"), ("hog_glider", "Hog Glider"),
             ("beta_minion", "Beta Minion"), ("baby_dragon", "Baby Dragon"),
             ("electrofire_wizard", "Electrofire Wizard")]


def crore(v):
    """3 crore storage -> '2.95' style numbers for the margin example (1 crore = 10,000,000)."""
    return f"{v / 10_000_000:.4f}".rstrip("0").rstrip(".")


def step_cfg(settings, key):
    """settings["steps"][key] over its defaults (a copy, for reading)."""
    out = copy.deepcopy(DEFAULT_STEPS.get(key, {}))
    out.update(copy.deepcopy((settings.get("steps") or {}).get(key) or {}))
    return out


def step_out(settings, key):
    """settings["steps"][key] to write into (created when missing; other keys in it are kept)."""
    steps = settings.setdefault("steps", {})
    if not isinstance(steps.get(key), dict):
        steps[key] = {}
    return steps[key]


def recipe_edit():
    e = QLineEdit()
    e.setPlaceholderText("e.g. loot (a Saved Army Recipe in the game)")
    e.setMaxLength(40)
    e.setClearButtonEnabled(True)
    return e


class StepSettings(QWidget):
    """Base: a Columns body; subclasses add their cards. Accounts fields update when the list changes."""

    changed = Signal()
    key = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.accounts_field = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        self.cols = Columns()
        lay.addWidget(self.cols)

    def _connect(self, *widgets):
        for w in widgets:
            for sig in ("valueChanged", "toggled", "textChanged", "changed"):
                s = getattr(w, sig, None)
                if s is not None and hasattr(s, "connect"):
                    s.connect(self.changed)
                    break
            else:
                if hasattr(w, "currentIndexChanged"):
                    w.currentIndexChanged.connect(self.changed)

    def set_accounts(self, accounts):
        if self.accounts_field is not None:
            self.accounts_field.set_accounts(accounts)

    def detail(self):
        """Short text for this step's row in the flow ("!" first = a warning)."""
        f = self.accounts_field
        if f is None:
            return "once"
        if not f.is_valid():
            return "!check accounts"
        n = len(f.picked())
        return f"{n} account{'s' if n != 1 else ''}" if n else "!no accounts"

    def set_running(self, running):
        self.setEnabled(not running)


# ----------------------------------------------------------------------------- Attack all bases
class AttackAllSettings(StepSettings):
    key = "attack_all"
    watch_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # --- accounts + army + plan
        atk = Card("Accounts and army", "Each account attacks until its storages are full, then the next one "
                   "goes.", icon="swords", color=T.GOLD)
        self.accounts_field = AccountsField()
        self.accounts_field.step = self.key
        atk.add(self.accounts_field)
        atk.add(divider())
        self.battle_seconds = Spin(20, 180, suffix=" s")
        atk.add(SettingRow("Max attack time", "From the start of deploying until the bot surrenders",
                           self.battle_seconds, 110))
        atk.add(divider())
        self.recipe = recipe_edit()
        atk.add(block("Army recipe", "The name of a Saved Army Recipe in the game, set before an account's first "
                      "attack. Empty = keep each account's army.", self.recipe))
        self.must_edrag = Toggle()
        self.must_clone = Toggle()
        atk.add(SettingRow("Army must have E-Dragons", "Checked after the recipe; the log says which account's "
                           "recipe is missing them", self.must_edrag))
        atk.add(SettingRow("Army must have Clone spells", "Checked after the recipe", self.must_clone))
        atk.add(divider())
        self.plan = PlanPicker()
        atk.add(self.plan)
        self.cols.add(atk, 0)

        # --- when is an account full
        full = Card("When is an account full?", "Pick the storages to watch. Only Elixir = fill elixir, then the "
                    "next account.", icon="coins", color=T.ELIXIR_HI)
        self.watch = {}
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for r in config.RESOURCES:
            chip = ChipToggle(NAMES[r], T.RESOURCE_COLOR[r], resource=r)
            self.watch[r] = chip
            chips.addWidget(chip)
        chips.addStretch(1)
        full.add(chips)
        self.full_rule = Segmented([("any", "Any is full"), ("all", "All are full")])
        full.add(SettingRow("Full when", "Of the watched storages", self.full_rule))
        full.add(divider())
        self.full_mode = Segmented([("capacity", "Capacity − margin"), ("table", "Town Hall table")])
        self.full_mode_row = SettingRow("When is a storage full", " ")
        mode_box = QWidget()
        mb = QVBoxLayout(mode_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.setSpacing(8)
        mb.addWidget(self.full_mode_row)
        mb.addWidget(self.full_mode)
        full.add(mode_box)
        self.margin_box = QWidget()
        mg = QVBoxLayout(self.margin_box)
        mg.setContentsMargins(0, 6, 0, 0)
        mg.setSpacing(4)
        self.margin_head = SettingRow("Stop this close to full", " ")
        mg.addWidget(self.margin_head)
        self.margin = {}
        for r in config.RESOURCES:
            sp = BigSpin(maximum=10_000_000, step=100_000 if r != "dark" else 1_000)
            sp.setSpecialValueText("No margin")
            sp.setFixedWidth(170)
            self.margin[r] = sp
            row = SettingRow(NAMES[r], control=sp)
            row.layout().insertWidget(0, ResourceIcon(r, 22), 0, Qt.AlignVCenter)
            mg.addWidget(row)
        full.add(self.margin_box)
        self.cols.add(full, 1)

        # --- Town Hall "full at" table
        self.th_card = FoldCard("Town Hall table", " ", icon="layers")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(label("TOWN HALL", "caption"), 0, 0)
        for i, r in enumerate(config.RESOURCES):
            grid.addLayout(hbox(ResourceIcon(r, 16), label(NAMES[r].upper(), "caption"), None, spacing=6), 0, i + 1)
        self.full_at = {}
        for row_i, lvl in enumerate(TH_LEVELS, start=1):
            tl = label(f"TH {lvl}")
            tl.setFont(T.font(9.5, QFont.DemiBold))
            grid.addWidget(tl, row_i, 0)
            for i, r in enumerate(config.RESOURCES):
                sp = BigSpin(maximum=100_000_000, step=500_000 if r != "dark" else 10_000)
                sp.setMinimumWidth(110)
                self.full_at[(lvl, r)] = sp
                grid.addWidget(sp, row_i, i + 1)
        for c in (1, 2, 3):
            grid.setColumnStretch(c, 1)
        self.th_card.add(grid)
        self.cols.add(self.th_card, 1)

        # --- more
        more = FoldCard("More", "Search limits and how the troops are deployed.", icon="sliders",
                        color=T.TEXT_MUTED)
        self.max_searches = Spin(5, 2000)
        self.max_attacks = Spin(0, 999, special="No limit")
        self.stuck = Spin(1, 10, suffix=" attacks")
        self.stuck.setToolTip("If storages do not grow after this many attacks, the account counts as full")
        more.add(SettingRow("Max searches per attack", "Give up after this many “Next” and retry",
                            self.max_searches, 110))
        more.add(SettingRow("Max attacks per account", "Then go on to the next account", self.max_attacks, 110))
        more.add(SettingRow("Full if storages stop growing", "No growth after this many attacks", self.stuck, 110))
        more.add(divider())
        self.smart_deploy = Toggle()
        self.count_troops = Toggle()
        self.zoom = Toggle()
        more.add(SettingRow("Detect the deploy zone (red area)",
                            "Finds the red no-deploy border and drops troops just outside it", self.smart_deploy))
        more.add(SettingRow("Deploy exactly the troops I have (no extra taps)",
                            "Reads each troop count and taps exactly that many times", self.count_troops))
        more.add(SettingRow("Zoom out before searching", "Shows the whole base before deploying", self.zoom))
        self.cols.add(more, 0)

        self._connect(self.accounts_field, self.battle_seconds, self.recipe, self.must_edrag, self.must_clone,
                      self.plan, *self.watch.values(), self.full_rule, self.full_mode, *self.margin.values(),
                      *self.full_at.values(), self.max_searches, self.max_attacks, self.stuck, self.smart_deploy,
                      self.count_troops, self.zoom)
        for chip in self.watch.values():
            chip.toggled.connect(self.watch_changed)
        self.full_mode.currentIndexChanged.connect(self._full_mode_changed)
        self.margin["gold"].valueChanged.connect(self._margin_example)
        self._full_mode_changed()
        self._margin_example()

    def watched(self):
        return {r: c.isChecked() for r, c in self.watch.items()}

    def _margin_example(self, *_):
        m = self.margin["gold"].value()
        self.margin_head.desc.setText(f"e.g. 3 crore storage → loots until {crore(30_000_000 - m)} crore"
                                      if m < 30_000_000 else "Room left in each storage when the account is full")

    def _full_mode_changed(self, *_):
        """Capacity: margins shown, the Town Hall table folded away (only a fallback). Table mode: the table."""
        capacity = self.full_mode.currentData() == "capacity"
        self.full_mode_row.desc.setText(
            "The bot measures each account's real storage size from the resource bar, so accounts with low "
            "storages are handled too." if capacity else "Fixed amounts per Town Hall level, from the table.")
        self.margin_box.setVisible(capacity)
        self.th_card.title_label.setText("Town Hall table" + (" (fallback)" if capacity else ""))
        self.th_card.subtitle_label.setText(
            "Storage “full at” by Town Hall. Used only until the bot has measured an account's storages; an "
            "account's own “full at” (Accounts) always wins." if capacity else
            "Storage “full at” by Town Hall. Set it slightly below your real capacity; an account's own “full at” "
            "(Accounts) wins over this table.")
        self.th_card.tile.set_icon("layers", T.TEXT_DIM if capacity else T.GOLD)
        if not capacity:
            self.th_card.set_open(True)

    def load(self, settings, accounts):
        st = step_cfg(settings, self.key)
        lo = settings.get("loot") or {}
        d = LOOT_DEFAULTS
        self.accounts_field.set_text(st.get("accounts", ""))
        self.battle_seconds.setValue(int(lo.get("battle_seconds", 60) or 60))
        self.recipe.setText(str(lo.get("army_recipe", d.get("army_recipe", "")) or ""))
        must = lo.get("army_must_have", d.get("army_must_have", ["edrag", "clone"])) or []
        self.must_edrag.setChecked("edrag" in must)
        self.must_clone.setChecked("clone" in must)
        self.plan.reload(lo.get("attack_plan", "edrag_spread"))
        for r in config.RESOURCES:
            self.watch[r].setChecked(bool((lo.get("watch") or {}).get(r)))
            margin = lo.get("full_margin") or {}
            self.margin[r].setValue(int(margin.get(r, DEFAULT_MARGIN.get(r, 0)) or 0))
        self.full_rule.setCurrentIndex(max(0, self.full_rule.findData(lo.get("full_rule", "any"))))
        self.full_mode.setCurrentIndex(max(0, self.full_mode.findData(lo.get("full_mode", "capacity"))))
        table = settings.get("full_at") or config.DEFAULT_FULL_AT
        for (lvl, r), sp in self.full_at.items():
            sp.setValue(int((table.get(lvl) or config.DEFAULT_FULL_AT.get(lvl, {})).get(r, 0) or 0))
        self.max_searches.setValue(int(lo.get("max_searches", 150) or 150))
        self.max_attacks.setValue(int(lo.get("max_attacks_per_account", 0) or 0))
        self.stuck.setValue(int(lo.get("stuck_attacks", 2) or 2))
        self.smart_deploy.setChecked(bool(lo.get("smart_deploy", True)))
        self.count_troops.setChecked(bool(lo.get("count_troops", True)))
        self.zoom.setChecked(bool(lo.get("zoom_out", True)))
        self.set_accounts(accounts)
        self._full_mode_changed()
        self._margin_example()

    def apply(self, settings, accounts):
        step_out(settings, self.key)["accounts"] = self.accounts_field.text()
        lo = settings.setdefault("loot", {})
        lo["battle_seconds"] = self.battle_seconds.value()
        lo["army_recipe"] = self.recipe.text().strip()
        lo["army_must_have"] = [k for t, k in ((self.must_edrag, "edrag"), (self.must_clone, "clone"))
                                if t.isChecked()]
        lo["attack_plan"] = self.plan.plan()
        lo["watch"] = self.watched()
        lo["full_rule"] = self.full_rule.currentData()
        lo["full_mode"] = self.full_mode.currentData()
        lo["full_margin"] = {r: self.margin[r].value() for r in config.RESOURCES}
        lo["max_searches"] = self.max_searches.value()
        lo["max_attacks_per_account"] = self.max_attacks.value()
        lo["stuck_attacks"] = self.stuck.value()
        lo["smart_deploy"] = self.smart_deploy.isChecked()
        lo["count_troops"] = self.count_troops.isChecked()
        lo["zoom_out"] = self.zoom.isChecked()
        table = {}
        for (lvl, r), sp in self.full_at.items():
            table.setdefault(lvl, {})[r] = sp.value()
        settings["full_at"] = table


# ----------------------------------------------------------------------------- Base choice per Town Hall
class BaseChoiceSettings(StepSettings):
    key = "base_choice"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._watched = {"gold": False, "elixir": True, "dark": False}
        card = Card("Minimum loot", "", icon="target", color=T.GOLD)
        self.mode = Segmented([("th", "By Town Hall"), ("fixed", "Same for all")])
        self.explain = label("", "rowDesc", wrap=True)
        card.add(SettingRow("Minimum loot", control=self.mode))
        card.add(self.explain)

        self.th_box = QWidget()
        grid = QGridLayout(self.th_box)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(label("TOWN HALL", "caption"), 0, 0)
        self.heads = {}
        for i, r in enumerate(config.RESOURCES):
            head = QWidget()
            head.setLayout(hbox(ResourceIcon(r, 16), label(NAMES[r].upper(), "caption"), None, spacing=6))
            self.heads[r] = head
            grid.addWidget(head, 0, i + 1)
        self.min_th = {}
        for row_i, lvl in enumerate(TH_LEVELS, start=1):
            tl = label(f"TH {lvl}")
            tl.setFont(T.font(9.5, QFont.DemiBold))
            grid.addWidget(tl, row_i, 0)
            for i, r in enumerate(config.RESOURCES):
                sp = BigSpin(maximum=20_000_000, step=100_000 if r != "dark" else 1_000)
                sp.setSpecialValueText("Any")
                sp.setMinimumWidth(110)
                self.min_th[(lvl, r)] = sp
                grid.addWidget(sp, row_i, i + 1)
        for c in (1, 2, 3):
            grid.setColumnStretch(c, 1)
        card.add(self.th_box)

        self.fixed_box = QWidget()
        fl = QVBoxLayout(self.fixed_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(4)
        self.min_loot = {}
        self.fixed_rows = {}
        for r in config.RESOURCES:
            sp = BigSpin(maximum=20_000_000, step=100_000 if r != "dark" else 1_000)
            sp.setSpecialValueText("Any")
            sp.setFixedWidth(170)
            self.min_loot[r] = sp
            row = SettingRow(f"Minimum {NAMES[r].lower()}", control=sp)
            row.layout().insertWidget(0, ResourceIcon(r, 22), 0, Qt.AlignVCenter)
            self.fixed_rows[r] = row
            fl.addWidget(row)
        fl.addWidget(divider())
        self.min_rule = Segmented([("any", "Any is met"), ("all", "All are met")])
        fl.addWidget(SettingRow("Attack when", "Of the watched minimums", self.min_rule))
        card.add(self.fixed_box)
        self.watch_note = label("", "small", wrap=True)
        card.add(self.watch_note)
        self.cols.add(card, 0)

        self._connect(self.mode, *self.min_th.values(), *self.min_loot.values(), self.min_rule)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def set_watched(self, watched):
        """Dim the resources that are not watched (they do not count)."""
        self._watched = dict(watched)
        for (lvl, r), sp in self.min_th.items():
            sp.setEnabled(bool(watched.get(r)))
        for r, head in self.heads.items():
            head.setEnabled(bool(watched.get(r)))
        for r, row in self.fixed_rows.items():
            row.setEnabled(bool(watched.get(r)))
        names = [NAMES[r] for r in config.RESOURCES if watched.get(r)]
        self.watch_note.setText(("Watched now: " + ", ".join(names) if names else "No storage is watched")
                                + " (Attack all bases → When is an account full?).")

    def _mode_changed(self, *_):
        th = self.mode.currentData() == "th"
        self.th_box.setVisible(th)
        self.fixed_box.setVisible(not th)
        self.explain.setText(
            "Attack a base only when it has at least this much (by the attacking account's Town Hall). Only the "
            "resources you watch count. “Any” = not checked." if th else
            "Attack a base only when it has at least this much, whatever the account's Town Hall. Only the "
            "resources you watch count. “Any” = not checked.")

    def load(self, settings, accounts):
        lo = settings.get("loot") or {}
        self.mode.setCurrentIndex(max(0, self.mode.findData(lo.get("min_loot_mode", "th"))))
        table = lo.get("min_loot_th") or {}
        for (lvl, r), sp in self.min_th.items():
            row = table.get(lvl) or DEFAULT_MIN_LOOT_TH.get(lvl, {})
            sp.setValue(int(row.get(r, DEFAULT_MIN_LOOT_TH.get(lvl, {}).get(r, 0)) or 0))
        for r in config.RESOURCES:
            self.min_loot[r].setValue(int((lo.get("min_loot") or {}).get(r, 0) or 0))
        self.min_rule.setCurrentIndex(max(0, self.min_rule.findData(lo.get("min_loot_rule", "any"))))
        self.set_watched(lo.get("watch") or self._watched)
        self._mode_changed()

    def apply(self, settings, accounts):
        lo = settings.setdefault("loot", {})
        lo["min_loot_mode"] = self.mode.currentData()
        table = copy.deepcopy(lo.get("min_loot_th") or {})
        for (lvl, r), sp in self.min_th.items():
            if not isinstance(table.get(lvl), dict):
                table[lvl] = {}
            table[lvl][r] = sp.value()
        lo["min_loot_th"] = table
        lo["min_loot"] = {r: self.min_loot[r].value() for r in config.RESOURCES}
        lo["min_loot_rule"] = self.min_rule.currentData()


# ----------------------------------------------------------------------------- Loot current
class LootCurrentSettings(StepSettings):
    key = "loot_current"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name = ""
        acc = Card("Account", "One account, attacked again and again.", icon="crosshair",
                   color=STEP_COLORS["loot_current"])
        self.account = Combo()
        self.account.setMinimumWidth(190)
        acc.add(SettingRow("Account", "Switches to it first, unless it is open already", self.account))
        self.max_attacks = Spin(0, 999, special="Until you stop it")
        self.max_attacks.setFixedWidth(170)
        acc.add(SettingRow("Attacks", "Then the flow goes on with its next step", self.max_attacks))
        note = Banner("Keeps attacking even when the storages are full.", "info")
        note.icon.setPixmap(icons.pixmap("crosshair", T.BLUE, 18))
        acc.add(note)
        self.cols.add(acc, 0)

        army = Card("Army and attack", icon="swords", color=T.GOLD)
        self.battle_seconds = Spin(20, 180, suffix=" s")
        army.add(SettingRow("Max attack time", "From the start of deploying until the bot surrenders",
                            self.battle_seconds, 110))
        army.add(divider())
        self.recipe = recipe_edit()
        army.add(block("Army recipe", "Set before the first attack. Empty = keep the account's army.", self.recipe))
        army.add(divider())
        self.plan = PlanPicker()
        army.add(self.plan)
        self.cols.add(army, 1)
        self._connect(self.account, self.max_attacks, self.battle_seconds, self.recipe, self.plan)
        self.account.currentIndexChanged.connect(self._remember)

    def _remember(self, *_):
        self._name = self.account.currentData() or ""

    def set_accounts(self, accounts):
        names = [a.get("name", "") for a in accounts if a.get("name")]
        want = self._name
        self.account.blockSignals(True)
        self.account.clear()
        self.account.addItem("The account open now", "")
        for n in names:
            self.account.addItem(n, n)
        if want and want not in names:
            self.account.addItem(f"{want} (not in the list)", want)
        self.account.select(want)
        self.account.blockSignals(False)

    def detail(self):
        return self._name or "open account"

    def load(self, settings, accounts):
        st = step_cfg(settings, self.key)
        self._name = str(st.get("account", "") or "")
        self.set_accounts(accounts)
        self.max_attacks.setValue(int(st.get("max_attacks", 0) or 0))
        self.battle_seconds.setValue(int(st.get("battle_seconds", 60) or 60))
        self.recipe.setText(str(st.get("army_recipe", "") or ""))
        self.plan.reload(st.get("attack_plan") or "edrag_spread")

    def apply(self, settings, accounts):
        st = step_out(settings, self.key)
        st["account"] = self.account.currentData() or ""
        st["battle_seconds"] = self.battle_seconds.value()
        st["army_recipe"] = self.recipe.text().strip()
        st["attack_plan"] = self.plan.plan()
        st["max_attacks"] = self.max_attacks.value()


# ----------------------------------------------------------------------------- Builder Base attack
class BBAttackSettings(StepSettings):
    key = "bb_attack"

    def __init__(self, parent=None):
        super().__init__(parent)
        who = Card("Accounts and army", "Accounts without a Builder Base yet are skipped automatically.",
                   icon="boat", color=NIGHT)
        self.accounts_field = AccountsField()
        self.accounts_field.step = self.key
        who.add(self.accounts_field)
        who.add(divider())
        self.army = Combo(BB_ARMIES)
        self.army.setMinimumWidth(200)
        who.add(block("Army", "Battle Machine + this unit in every slot (rebuilt only when it differs). Units the "
                      "account has not unlocked fall back to the next best.", self.army))
        who.add(divider())
        self.collect = Toggle()
        who.add(SettingRow("Collect resources", "On arrival: the Gold Mine and the Elixir Collector", self.collect))
        self.zoom = Toggle()
        who.add(SettingRow("Zoom out before attacking", "Shows the whole base before deploying", self.zoom))
        self.cols.add(who, 0)

        atk = Card("Attacks", "Two-stage battles, up to 6 stars each. The daily Star Bonus pays extra loot.",
                   icon="swords", color=NIGHT)
        self.after_bonus = Toggle()
        atk.add(SettingRow("Keep attacking after the daily Star Bonus is complete",
                           "Off: stop once the Star Bonus is done (e.g. 8/8 stars).", self.after_bonus))
        atk.add(divider())
        self.max_attacks = Spin(0, 100, special="No limit")
        atk.add(SettingRow("Max attacks per visit", "Then sail back and go on", self.max_attacks, 130))
        self.battle_seconds = Spin(0, 180, " s", special="Until it ends")
        atk.add(SettingRow("End each attack after", "The bot surrenders when this time is up", self.battle_seconds,
                           130))
        self.stuck = Spin(1, 10, suffix=" attacks")
        self.stuck.setToolTip("If the storages do not grow after this many attacks, they count as full")
        atk.add(SettingRow("Full if storages stop growing after", "For storages smaller than the Builder Hall "
                           "suggests", self.stuck, 130))
        self.full_margin = BigSpin(maximum=5_000_000, step=10_000)
        self.full_margin.setSpecialValueText("Only when full")
        atk.add(SettingRow("Storages count as full within", "Gold and elixir: the measured storage size minus "
                           "this", self.full_margin, 150))
        self.cols.add(atk, 1)
        self._connect(self.accounts_field, self.army, self.collect, self.zoom, self.after_bonus, self.max_attacks,
                      self.battle_seconds, self.stuck, self.full_margin)

    def load(self, settings, accounts):
        self.accounts_field.set_text(step_cfg(settings, self.key).get("accounts", ""))
        b = copy.deepcopy(BUILDER_DEFAULTS)
        b.update(settings.get("builder") or {})
        self.army.blockSignals(True)
        self.army.select(b.get("army", "auto"))
        self.army.blockSignals(False)
        self.collect.setChecked(bool(b.get("collect", True)))
        self.zoom.setChecked(bool(b.get("zoom_out", True)))
        self.after_bonus.setChecked(bool(b.get("after_bonus", False)))
        self.max_attacks.setValue(int(b.get("max_attacks", 20) or 0))
        self.battle_seconds.setValue(int(b.get("battle_seconds", 60) or 0))
        self.stuck.setValue(int(b.get("stuck_attacks", 3) or 3))
        self.full_margin.setValue(int(b.get("full_margin", 50000) or 0))
        self.set_accounts(accounts)

    def apply(self, settings, accounts):
        step_out(settings, self.key)["accounts"] = self.accounts_field.text()
        b = settings.setdefault("builder", {})          # after_main, upgrade, research, ... are kept as they are
        b["army"] = self.army.currentData() or "auto"
        b["collect"] = self.collect.isChecked()
        b["zoom_out"] = self.zoom.isChecked()
        b["after_bonus"] = self.after_bonus.isChecked()
        b["max_attacks"] = self.max_attacks.value()
        b["battle_seconds"] = self.battle_seconds.value()
        b["stuck_attacks"] = self.stuck.value()
        b["full_margin"] = self.full_margin.value()


# ----------------------------------------------------------------------------- upgrades and research
class _ListStep(StepSettings):
    """Accounts + an ordered name list (buildings or research)."""

    list_key = "buildings"

    def __init__(self, who_title, who_icon, order_title, order_text, suggestions, placeholder, empty, defaults,
                 color, parent=None):
        super().__init__(parent)
        self.who = Card(who_title, icon=who_icon, color=color)
        self.accounts_field = AccountsField()
        self.accounts_field.step = self.key
        self.who.add(self.accounts_field)
        self.cols.add(self.who, 0)
        self.order_card = Card(order_title, order_text, icon="list", color=color)
        self.order = OrderList(suggestions, placeholder, empty, defaults)
        self.order_card.add(self.order)
        self.cols.add(self.order_card, 1)
        self._connect(self.accounts_field, self.order)

    def load(self, settings, accounts):
        st = step_cfg(settings, self.key)
        self.accounts_field.set_text(st.get("accounts", ""))
        self.order.set_values(st.get(self.list_key) or [])
        self.set_accounts(accounts)

    def apply(self, settings, accounts):
        st = step_out(settings, self.key)
        st["accounts"] = self.accounts_field.text()
        st[self.list_key] = self.order.values()


def gems_note():
    b = Banner("<b>Never with gems.</b> Only upgrades priced in gold, elixir or dark elixir that the account can "
               "afford, confirmed with the Confirm button that shows a resource price. Prices are read from the "
               "game every time, so price changes and sales are handled.", "success")
    b.icon.setPixmap(icons.pixmap("shield", T.GREEN, 18))
    return b


class HomeUpgradeSettings(_ListStep):
    key = "home_upgrade"

    def __init__(self, parent=None):
        super().__init__("Accounts and builders", "hammer", "Building order",
                         "Free builders take the first building in this order that can be upgraded with the "
                         "resources the account has. Never with gems.",
                         HOME_BUILDINGS, "Add a building…", "Nothing in the list: no upgrades are started.",
                         DEFAULT_HOME_BUILDINGS, STEP_COLORS["home_upgrade"], parent)
        self.max_per_visit = Spin(1, 10)
        self.keep_gold = BigSpin(maximum=5_000_000, step=50_000)
        self.who.add(divider())
        self.who.add(SettingRow("Upgrades per visit", "One per free builder, up to this many", self.max_per_visit,
                                110))
        self.who.add(SettingRow("Keep gold for searching", "Never spent on upgrades: finding a base to loot costs "
                                "gold", self.keep_gold, 150))
        self.who.add(gems_note())
        self._connect(self.max_per_visit, self.keep_gold)

    def load(self, settings, accounts):
        super().load(settings, accounts)
        self.max_per_visit.setValue(int(step_cfg(settings, self.key).get("max_per_visit", 5) or 5))
        self.keep_gold.setValue(int(step_cfg(settings, self.key).get("keep_gold", 300000) or 0))

    def apply(self, settings, accounts):
        super().apply(settings, accounts)
        step_out(settings, self.key)["max_per_visit"] = self.max_per_visit.value()
        step_out(settings, self.key)["keep_gold"] = self.keep_gold.value()


class WallsSettings(StepSettings):
    key = "walls"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.who = Card("Accounts and resources", "The cheapest walls first, as many at once as the storages pay "
                        "for (the game's Upgrade More): a batch with gold, a batch with elixir, then the next "
                        "level. Walls take no builder.", icon="blocks", color=STEP_COLORS["walls"])
        self.accounts_field = AccountsField()
        self.accounts_field.step = self.key
        self.who.add(self.accounts_field)
        self.keep_gold = BigSpin(maximum=5_000_000, step=50_000)
        self.keep_elixir = BigSpin(maximum=20_000_000, step=100_000)
        self.who.add(divider())
        self.who.add(SettingRow("Keep gold for searching", "Never spent on walls: finding a base to loot costs gold",
                                self.keep_gold, 150))
        self.who.add(SettingRow("Keep elixir", "Never spent on walls (0 = all of it may go into walls)",
                                self.keep_elixir, 150))
        b = Banner("<b>Never with gems.</b> Before Okay the total on the Upgrade button and the amount the game "
                   "asks for are both checked against what may be spent.", "success")
        b.icon.setPixmap(icons.pixmap("shield", T.GREEN, 18))
        self.who.add(b)
        self.cols.add(self.who, 0)
        self._connect(self.accounts_field, self.keep_gold, self.keep_elixir)

    def load(self, settings, accounts):
        st = step_cfg(settings, self.key)
        self.accounts_field.set_text(st.get("accounts", ""))
        self.keep_gold.setValue(int(st.get("keep_gold", 300000) or 0))
        self.keep_elixir.setValue(int(st.get("keep_elixir", 0) or 0))
        self.set_accounts(accounts)

    def apply(self, settings, accounts):
        st = step_out(settings, self.key)
        st["accounts"] = self.accounts_field.text()
        st["keep_gold"] = self.keep_gold.value()
        st["keep_elixir"] = self.keep_elixir.value()


class RaidSettings(StepSettings):
    key = "raid"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.who = Card("Accounts", "Raid Weekend (Friday 12:30 to Monday 12:30, India time): each account opens the "
                        "Clan Capital, starts a raid attack without placing troops, and the game is closed and opened "
                        "again - that ends the attack at once. Again until its raid attacks are used. Outside the "
                        "Raid Weekend the bot waits for the next one.", icon="castle", color=STEP_COLORS["raid"])
        self.accounts_field = AccountsField()
        self.accounts_field.step = self.key
        self.who.add(self.accounts_field)
        self.attacks = Spin(1, 6)
        self.with_donate = Toggle()
        self.who.add(divider())
        self.who.add(SettingRow("Raid attacks per account", "Each account has 5 (6 with the bonus attack)",
                                self.attacks, 110))
        self.who.add(SettingRow("Also with Loot + Donate", "On Raid Weekend, Loot + Donate (and Upgrade, loot, "
                                "donate) do the raid attacks first, then donate", self.with_donate))
        self.cols.add(self.who, 0)
        self._connect(self.accounts_field, self.attacks, self.with_donate)

    def load(self, settings, accounts):
        st = step_cfg(settings, self.key)
        self.accounts_field.set_text(st.get("accounts", ""))
        self.attacks.setValue(int(st.get("attacks", 6) or 6))
        self.with_donate.setChecked(bool(st.get("with_donate", True)))
        self.set_accounts(accounts)

    def apply(self, settings, accounts):
        st = step_out(settings, self.key)
        st["accounts"] = self.accounts_field.text()
        st["attacks"] = self.attacks.value()
        st["with_donate"] = self.with_donate.isChecked()


class BBUpgradeSettings(_ListStep):
    key = "bb_upgrade"

    def __init__(self, parent=None):
        super().__init__("Accounts and builders", "hammer", "Building order",
                         "The Builder Hall is upgraded when nothing on the list can be upgraded any more.",
                         BB_BUILDINGS, "Add a Builder Base building…", "Nothing in the list: only new buildings "
                         "and the Builder Hall.", DEFAULT_STEPS["bb_upgrade"].get("buildings"), NIGHT, parent)
        self.new_first = Toggle()
        self.who.add(divider())
        self.who.add(SettingRow("Build new buildings first", "Buildings the Builder Hall unlocked are built before "
                                "the list", self.new_first))
        self.who.add(gems_note())
        self._connect(self.new_first)

    def load(self, settings, accounts):
        super().load(settings, accounts)
        self.new_first.setChecked(bool(step_cfg(settings, self.key).get("new_first", True)))

    def apply(self, settings, accounts):
        super().apply(settings, accounts)
        step_out(settings, self.key)["new_first"] = self.new_first.isChecked()


class HomeResearchSettings(_ListStep):
    key = "home_research"
    list_key = "research"

    def __init__(self, parent=None):
        super().__init__("Accounts", "flask", "Research order",
                         "When the Laboratory is free, the first unit in this order that can be researched with the "
                         "account's resources is started.", HOME_RESEARCH, "Add a troop, spell or siege machine…",
                         "Nothing in the list yet: add troops, spells or siege machines below.", None,
                         STEP_COLORS["home_research"], parent)


class BBResearchSettings(_ListStep):
    key = "bb_research"
    list_key = "research"

    def __init__(self, parent=None):
        super().__init__("Accounts", "flask", "Research order",
                         "When the Star Laboratory is free, the first unit in this order that can be researched "
                         "with the account's resources is started.", BB_RESEARCH, "Add a Builder Base troop…",
                         "Nothing in the list yet: add Builder Base troops below.", None, NIGHT, parent)


# ----------------------------------------------------------------------------- General
class GeneralSettings(StepSettings):
    key = "general"

    def __init__(self, parent=None):
        super().__init__(parent)
        card = Card("Run", "What happens when an account is full and when the run ends.", icon="bolt",
                    color=T.GOLD)
        self.when_full = Combo(WHEN_FULL)
        self.when_done = Combo(WHEN_DONE)
        self.rounds = Spin(0, 999, special="Forever")
        card.add(SettingRow("When an account is full", control=self.when_full, control_width=190))
        card.add(SettingRow("When the run ends", control=self.when_done, control_width=190))
        card.add(SettingRow("Rounds over the flow", "0 = Forever", self.rounds, 120))
        self.cols.add(card, 0)
        self._connect(self.when_full, self.when_done, self.rounds)

    def detail(self):
        return ""

    def load(self, settings, accounts):
        self.when_full.select(settings.get("when_full", "switch"))
        self.when_done.select(settings.get("when_done", "nothing"))
        self.rounds.setValue(int(settings.get("repeat_rounds", 1) or 0))

    def apply(self, settings, accounts):
        settings["when_full"] = self.when_full.currentData()
        settings["when_done"] = self.when_done.currentData()
        settings["repeat_rounds"] = self.rounds.value()


BODIES = {"attack_all": AttackAllSettings, "base_choice": BaseChoiceSettings, "loot_current": LootCurrentSettings,
          "bb_attack": BBAttackSettings, "home_upgrade": HomeUpgradeSettings, "walls": WallsSettings,
          "bb_upgrade": BBUpgradeSettings, "raid": RaidSettings,
          "home_research": HomeResearchSettings, "bb_research": BBResearchSettings, "general": GeneralSettings}

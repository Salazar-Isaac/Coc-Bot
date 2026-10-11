"""Settings and account list, stored as JSON in config/ and edited from the window."""

import copy
import json
import os
import threading

from . import paths

SETTINGS_PATH = os.path.join(paths.CONFIG, "settings.json")
ACCOUNTS_PATH = os.path.join(paths.CONFIG, "accounts.json")
STATE_PATH = os.path.join(paths.CONFIG, "state.json")

RESOURCES = ("gold", "elixir", "dark")

# Storage "full at" values per Town Hall (from the old bot; edit in Loot Settings).
DEFAULT_FULL_AT = {
    "19": {"gold": 40500000, "elixir": 40500000, "dark": 500000},
    "18": {"gold": 30500000, "elixir": 30500000, "dark": 480000},
    "17": {"gold": 27500000, "elixir": 27500000, "dark": 440000},
    "16": {"gold": 25500000, "elixir": 25500000, "dark": 400000},
    "15": {"gold": 22500000, "elixir": 22500000, "dark": 380000},
    "14": {"gold": 20500000, "elixir": 20500000, "dark": 360000},
    "13": {"gold": 17500000, "elixir": 17500000, "dark": 340000},
    "12": {"gold": 14000000, "elixir": 14000000, "dark": 300000},
    "11": {"gold": 8000000, "elixir": 8000000, "dark": 200000},
}

# "Full" = measured storage capacity minus this much room (5 lakh for gold/elixir).
DEFAULT_MARGIN = {"gold": 500000, "elixir": 500000, "dark": 5000}

DEFAULT_SETTINGS = {
    "device": {
        "type": "pc",                       # "pc" (Google Play Games) or "adb"
        "shortcut_path": r"C:\Users\Amigo\AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
                         r"\Google Play Games\Clash of Clans.lnk",
        "window_title": "Clash of Clans",
        "adb_path": "",
        "adb_serial": "127.0.0.1:5555",
        "scrcpy_dir": r"C:\scrcpy",
    },
    "profile": "pc-1920x1080",
    "mode": "loot_all",
    "loot": {
        "watch": {"gold": False, "elixir": True, "dark": False},
        "full_rule": "any",                 # account is full when "any" / "all" watched resources are full
        "min_loot": {"gold": 0, "elixir": 1200000, "dark": 0},
        "min_loot_rule": "any",             # attack when "any" / "all" watched resources reach the minimum
        "max_searches": 150,                # give up searching after this many "Next" (then retry)
        "max_attacks_per_account": 0,       # 0 = no limit
        "battle_seconds": 60,               # max battle time: end the battle after this many seconds
        "smart_deploy": True,               # find the red no-deploy area and drop troops just outside it
        "count_troops": True,               # read each troop count and tap exactly that many times
        "attack_plan": "edrag_spread",
        "zoom_out": True,
        "stuck_attacks": 2,                 # resource did not grow after this many attacks -> treat as full
        "roles": {"main": True, "loot": True, "both": True, "feeder": False},   # who "Loot all accounts" loots
        "full_mode": "capacity",            # "capacity": measured storage size - margin; "table": TH table
        "army_recipe": "",                  # Saved Recipe to use before looting on every account (e.g. "loot")
        "army_must_have": ["edrag", "clone"],   # units checked after applying the recipe
        "full_margin": {"gold": 500000, "elixir": 500000, "dark": 5000},
    },
    "full_at": DEFAULT_FULL_AT,
    "when_full": "switch",                  # "switch" / "wait" / "stop"
    "when_done": "nothing",                 # "nothing" / "close_game" / "shutdown" / "sleep"
    "repeat_rounds": 1,                     # 0 = loop forever over the accounts
    "donate": {
        "min_elixir_keep": 4000000,         # main account donates while elixir is above this
        "rounds": 0,                        # 0 = until elixir drops below min_elixir_keep
        "remove_cc_before_request": True,
        "request_text": "",
        "loot_before_donate": True,         # Loot + Donate: main and loot-only accounts loot until full first
        "clan_tag": "",                     # the Main's clan; accounts without a clan join it (e.g. "#2RPLP89CY")
        "auto_join": True,
        # what the main account donates, in priority order (icons captured as templates "donate/<name>")
        "items": [],
    },
    "village": {
        "collect": True,                    # collectors + loot cart when arriving on an account
        "upgrade_buildings": False,         # spend resources on builder upgrades before leaving
        "research": False,                  # start laboratory research before leaving
        "max_upgrades": 2,                  # building upgrades started per visit
        "include_other": True,              # also consider "Other upgrades", not only "Suggested"
        "upgrade_skip": ["Wall", "Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion",
                         "Minion Prince", "Dragon Duke"],   # heroes stay usable for attacks
        "research_skip": [],
        "reserve": {"gold": 0, "elixir": 0, "dark": 0},     # never spend below these
        "on_roles": ["main", "loot", "both", "feeder"],      # which accounts get chores
    },
    "builder": {
        "after_main": False,                # loot modes: after an account's home village is full, loot its Builder Base
        "after_bonus": False,               # keep attacking after the daily Star Bonus is complete
        "army": "auto",                     # "auto" (P.E.K.K.A if unlocked, else Sneaky Archer), "keep" or a unit name
        "max_attacks": 20,                  # safety limit per visit (0 = none)
        "stuck_attacks": 3,                 # storages not growing after this many attacks = full
        "full_margin": 50000,               # Builder Base storages count as full this close to capacity
        "collect": True,
        "upgrade": False,                   # use free Builder Base builders
        "gear_up": True,                    # Builder Hall first, then new buildings, Cannon/Archer Tower/Mortar
        "max_upgrades": 1,
        "research": False,                  # Star Laboratory
        "upgrade_skip": [],
        "research_skip": [],
        "zoom_out": True,
        "on_roles": ["main", "loot", "both", "feeder"],
    },
    "hotkeys": {"continue": "f8", "pause": "f9", "stop": "f10"},
    "minimize_on_start": True,
    "save_error_screenshots": True,
}

# role: "main" (loots + donates), "loot" (loot only), "both" (loots in Loot all + requests),
#       "feeder" (only requests), "skip"
DEFAULT_ACCOUNTS = []


def _merge(defaults, data):
    out = copy.deepcopy(defaults)
    for k, v in (data or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "full_at":
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


_lock = threading.Lock()


def load_settings():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return _merge(DEFAULT_SETTINGS, json.load(f))
    return copy.deepcopy(DEFAULT_SETTINGS)


def save_settings(settings):
    with _lock, open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def new_account(name, role="loot", th=0):
    return {"name": name, "role": role, "enabled": True, "th": th,
            "full_at": {"gold": 0, "elixir": 0, "dark": 0}}   # 0 = use the Town Hall table


def load_accounts():
    if os.path.exists(ACCOUNTS_PATH):
        with open(ACCOUNTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return [_merge(new_account(a.get("name", "")), a) for a in data]
    return copy.deepcopy(DEFAULT_ACCOUNTS)


def save_accounts(accounts):
    clean = [{k: v for k, v in a.items() if not k.startswith("_")} for a in accounts]   # _x = this run only
    with _lock, open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)


def full_at(settings, account, resource):
    """The amount at which `resource` counts as full for this account:
    1. the account's own "full at" (Accounts page), else
    2. its measured storage capacity minus the margin (Loot page, default 5 lakh), else
    3. the Town Hall table."""
    own = (account.get("full_at") or {}).get(resource, 0)
    if own:
        return own
    lo = settings.get("loot", {})
    cap = (account.get("capacity") or {}).get(resource)
    if cap and lo.get("full_mode", "capacity") == "capacity":
        margin = (lo.get("full_margin") or {}).get(resource, DEFAULT_MARGIN[resource])
        return max(1, cap - margin)
    table = settings.get("full_at", DEFAULT_FULL_AT)
    th = str(account.get("th") or "")
    if th in table:
        return table[th][resource]
    return 0   # unknown -> never "full" by value (the stuck-attack rule still applies)


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


def save_state(state):
    with _lock, open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

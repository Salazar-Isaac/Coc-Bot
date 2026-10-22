"""Settings and account list, stored as JSON in config/ and edited from the window."""

import copy
import json
import os
import threading

from . import paths
from .flow import DEFAULT_MIN_LOOT_TH, DEFAULT_STEPS

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
        "background_input": True,
        "adb_path": "",
        "adb_serial": "127.0.0.1:5555",
    },
    "profile": "pc-1920x1080",
    "mode": "flow",
    # the functions in the order they run (keys of bot/flow.py STEPS; a key may appear more than once,
    # e.g. upgrade before and after looting) and each function's own settings
    "flow": ["attack_all"],
    "option": "loot_all",                   # the option chosen in the window (bot/flow.py OPTIONS) -> "flow"
    "start_from": 1,                        # account # the run starts with (follows the run: where it stopped)
    "research_too": {"home": False, "builder": False},   # upgrade options: also start lab research
    "steps": DEFAULT_STEPS,
    "loot": {
        "watch": {"gold": False, "elixir": True, "dark": False},
        "full_rule": "any",                 # account is full when "any" / "all" watched resources are full
        "min_loot": {"gold": 0, "elixir": 1200000, "dark": 0},
        "min_loot_rule": "any",             # attack when "any" / "all" watched resources reach the minimum
        "min_loot_mode": "th",              # "th": the minimum by the account's Town Hall (table below); "fixed": min_loot
        "min_loot_th": DEFAULT_MIN_LOOT_TH,
        "max_searches": 150,                # give up searching after this many "Next" (then retry)
        "max_attacks_per_account": 0,       # 0 = no limit
        "battle_seconds": 60,               # max battle time: end the battle after this many seconds
        "smart_deploy": True,               # find the red no-deploy area and drop troops just outside it
        "count_troops": True,               # read each troop count and tap exactly that many times
        "attack_plan": "edrag_spread",
        "earthquake_method": "curve",
        "event_lavaloons": False,            # deploy every unit from the event's x50 troop card
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
        "min_elixir_keep": 4000000,         # a round starts if Main's elixir > this + one round's cost (learned)
        "rounds": 0,                        # 0 = until elixir drops below min_elixir_keep
        "round_accounts": 0,                # accounts per request round; 0 = auto (fits the request cooldown)
        "remove_cc_before_request": True,
        "request_text": "",
        "loot_before_donate": False,        # Loot + Donate: loot to full before the first round (XpIncrease: no)
        "method": "fast",                   # "fast": XpIncrease-style bursts of taps; "careful": verify each unit
        "special_template": "donate/super_wizard",   # in colour = big request -> items marked "big"
        # what the main account donates, in priority order (icons captured as templates "donate/<name>")
        "items": [],
    },
    "upgrades": {
        "enabled": True,                    # the upgrade plan on accounts ticked "Upgrade" (Accounts page)
        "max_per_visit": 5,                 # upgrades started per visit (one per free builder)
        "from": 1,                          # Loot + Upgrade: accounts #from-#to of the Accounts page
        "to": 15,
        "extra": [],                        # more buildings for the plan (before the Town Hall)
        "bb_plan": ["Cannon", "Archer Tower", "Mortar"],   # Builder Base: these, then the Builder Hall
    },
    "builder": {
        "after_main": False,                # loot modes: after an account's home village is full, loot its Builder Base
        "after_bonus": False,               # keep attacking after the daily Star Bonus is complete
        "army": "auto",                     # "auto" (P.E.K.K.A if unlocked, else Sneaky Archer), "keep" or a unit name
        "max_attacks": 20,                  # safety limit per visit (0 = none)
        "battle_seconds": 60,               # each Builder Base attack is ended after this many seconds
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
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("full_at", "min_loot_th"):
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
    return {"name": name, "role": role, "enabled": True, "th": th, "upgrade": False,
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

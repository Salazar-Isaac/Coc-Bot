"""The flow: the bot's functions, chained in the order you arrange them in the window.

Steps that work on one account at a time ("per account") run account by account: account 1 does
every such step of the flow in order, then account 2, and so on. Each step has its own accounts
("1-15", "3,5,9-12"; empty = all), so a step is skipped on accounts it does not list.
"Donate" and "Loot current" are run once where they stand in the flow (they are not per account).

This module only describes the steps (titles, defaults, name lists for the pickers) and reads the
account lists, so the window can use it too; bot/modes/flow.py runs a flow.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    icon: str            # icon name in gui/icons.py
    description: str
    per_account: bool    # runs on each of its accounts (False: once, where it stands in the flow)
    village: str         # "home", "builder" or "" (not tied to a village)


STEPS = [
    Step("attack_all", "Attack all bases", "swords",
         "Loot each of its accounts until the storages are full", True, "home"),
    Step("loot_current", "Loot current", "crosshair",
         "Keep attacking on one account, even when its storages are full", False, "home"),
    Step("donate", "Donate", "gift",
         "Main donates; the requesting accounts empty their Clan Castle and request", False, ""),
    Step("bb_attack", "Builder Base attack", "boat",
         "Attack on the Builder Base only (Star Bonus, then until full)", True, "builder"),
    Step("home_upgrade", "Home village upgrade", "hammer",
         "Put free builders on the buildings you choose, in your order", True, "home"),
    Step("bb_upgrade", "Builder Base upgrade", "hammer",
         "New buildings first, then your list, then the Builder Hall", True, "builder"),
    Step("home_research", "Home research", "flask",
         "Start Laboratory research from your list when the lab is free", True, "home"),
    Step("bb_research", "Builder Base research", "flask",
         "Start Star Laboratory research from your list when it is free", True, "builder"),
]
BY_KEY = {s.key: s for s in STEPS}

# Upgrading and researching never happens on the Main or the Looters (Buggu01, Omi ji): those
# accounts loot and donate, they keep their resources for that.
LOOTERS = ("main", "loot", "both")
UPGRADERS = ("both", "feeder")
NO_UPGRADE_ROLES = ("main", "loot")
UPGRADE_STEPS = ("home_upgrade", "bb_upgrade", "home_research", "bb_research")


@dataclass(frozen=True)
class Option:
    key: str
    group: str            # "Loot", "Donate", "Upgrade"
    title: str
    description: str
    icon: str
    steps: tuple          # the flow it runs
    roles: dict           # which accounts each step gets (by role on the Accounts list), set when chosen


_UP = ("both",)           # default accounts for upgrades: the "Loot + request" ones (3-15 here)
OPTIONS = [
    Option("loot_all", "Loot", "Loot all accounts", "Each account until its storages are full, then the next",
           "swords", ("attack_all",), {"attack_all": LOOTERS}),
    Option("loot_current", "Loot", "Loot current account", "Keeps attacking on one account, even when it is full",
           "crosshair", ("loot_current",), {}),
    Option("bb_loot", "Loot", "Builder Base loot", "Builder Base attacks on each account, no home attacks",
           "boat", ("bb_attack",), {"bb_attack": LOOTERS}),
    Option("home_bb_loot", "Loot", "Home + Builder loot", "Each account loots its village, then its Builder Base",
           "swords", ("attack_all", "bb_attack"), {"attack_all": LOOTERS, "bb_attack": LOOTERS}),
    Option("donate_only", "Donate", "Donate only", "The others request, the Main donates while it has elixir",
           "gift", ("donate",), {}),
    Option("loot_donate", "Donate", "Loot + Donate", "Main and Looters loot; the others request; the Main donates",
           "gift", ("donate", "attack_all"), {"attack_all": ("main", "loot")}),
    Option("home_upgrade", "Upgrade", "Home loot + upgrade", "Upgrade, loot until full, upgrade again (village)",
           "hammer", ("home_upgrade", "attack_all", "home_upgrade"), {"attack_all": LOOTERS, "home_upgrade": _UP}),
    Option("bb_upgrade", "Upgrade", "Builder loot + upgrade", "Upgrade, loot, upgrade again on the Builder Base",
           "hammer", ("bb_upgrade", "bb_attack", "bb_upgrade"), {"bb_attack": LOOTERS, "bb_upgrade": _UP}),
    Option("all_upgrade", "Upgrade", "Both loot + upgrade", "Village and Builder Base: upgrade, loot, upgrade",
           "hammer", ("home_upgrade", "attack_all", "home_upgrade", "bb_upgrade", "bb_attack", "bb_upgrade"),
           {"attack_all": LOOTERS, "home_upgrade": _UP, "bb_attack": LOOTERS, "bb_upgrade": _UP}),
    Option("upgrade_only", "Upgrade", "Upgrade only", "Free builders to work in both villages, no attacks",
           "hammer", ("home_upgrade", "bb_upgrade"), {"home_upgrade": _UP, "bb_upgrade": _UP}),
]
OPTION = {o.key: o for o in OPTIONS}
DEFAULT_OPTION = "loot_all"


def option_flow(key, research=None):
    """The steps an option runs; research={"home": True, "builder": True} adds Laboratory / Star
    Laboratory research after that village's last upgrade step."""
    opt = OPTION.get(key) or OPTION[DEFAULT_OPTION]
    steps = list(opt.steps)
    research = research or {}
    for up, rs, village in (("bb_upgrade", "bb_research", "builder"), ("home_upgrade", "home_research", "home")):
        if research.get(village) and up in steps:
            last = len(steps) - 1 - steps[::-1].index(up)
            steps.insert(last + 1, rs)
    return steps


def positions_spec(positions):
    """[1, 2, 3, 7, 9, 10] -> "1-3, 7, 9-10"."""
    out, run = [], []
    for p in sorted(set(positions)):
        if run and p == run[-1] + 1:
            run.append(p)
            continue
        if run:
            out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [p]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


PRESETS = [(o.title, list(o.steps), o.roles) for o in OPTIONS]


def preset_accounts(roles_by_step, accounts):
    """{step: "1-2"}: the positions of the accounts with those roles (Use on)."""
    return {key: positions_spec([i + 1 for i, a in enumerate(accounts)
                                 if a.get("enabled", True) and a.get("role") in roles])
            for key, roles in roles_by_step.items()}


# names for the pickers (a building/research name can also be typed; part of a name is enough)
HOME_BUILDINGS = ["Gold Storage", "Elixir Storage", "Dark Elixir Storage", "Army Camp", "Barracks", "Dark Barracks",
                  "Spell Factory", "Dark Spell Factory", "Workshop", "Blacksmith", "Hero Hall", "Laboratory",
                  "Pet House", "Clan Castle", "Archer Tower", "Cannon", "Mortar", "Air Defense", "Wizard Tower",
                  "Air Sweeper", "Hidden Tesla", "Bomb Tower", "X-Bow", "Inferno Tower", "Eagle Artillery",
                  "Scattershot", "Spell Tower", "Monolith", "Multi-Archer Tower", "Ricochet Cannon",
                  "Multi-Gear Tower", "Firespitter", "Gold Mine", "Elixir Collector", "Dark Elixir Drill",
                  "Builder's Hut", "Bomb", "Spring Trap", "Giant Bomb", "Air Bomb", "Seeking Air Mine",
                  "Skeleton Trap", "Tornado Trap", "Giga Bomb", "Wall", "Town Hall"]
BB_BUILDINGS = ["Cannon", "Archer Tower", "Mortar", "Double Cannon", "Multi Mortar", "Firecrackers", "Crusher",
                "Guard Post", "Air Bombs", "Roaster", "Giant Cannon", "Mega Tesla", "Lava Launcher", "Hidden Tesla",
                "Builder Barracks", "Clock Tower", "Star Laboratory", "Gem Mine", "Gold Storage", "Elixir Storage",
                "Gold Mine", "Elixir Collector", "Healing Hut", "Reinforcement Camp", "Army Camp", "O.T.T.O's Outpost",
                "Push Trap", "Spring Trap", "Mine", "Mega Mine", "Wall", "Builder Hall"]
HOME_RESEARCH = ["Barbarian", "Archer", "Giant", "Goblin", "Wall Breaker", "Balloon", "Wizard", "Healer", "Dragon",
                 "P.E.K.K.A", "Baby Dragon", "Miner", "Electro Dragon", "Yeti", "Dragon Rider", "Electro Titan",
                 "Root Rider", "Thrower", "Minion", "Hog Rider", "Valkyrie", "Golem", "Witch", "Lava Hound", "Bowler",
                 "Ice Golem", "Headhunter", "Apprentice Warden", "Druid", "Furnace",
                 "Lightning Spell", "Healing Spell", "Rage Spell", "Jump Spell", "Freeze Spell", "Clone Spell",
                 "Invisibility Spell", "Recall Spell", "Revive Spell", "Poison Spell", "Earthquake Spell",
                 "Haste Spell", "Skeleton Spell", "Bat Spell", "Overgrowth Spell", "Ice Block Spell",
                 "Wall Wrecker", "Battle Blimp", "Stone Slammer", "Siege Barracks", "Log Launcher", "Flame Flinger",
                 "Battle Drill", "Troop Launcher"]
BB_RESEARCH = ["Raged Barbarian", "Sneaky Archer", "Boxer Giant", "Beta Minion", "Bomber", "Baby Dragon",
               "Cannon Cart", "Night Witch", "Drop Ship", "Power P.E.K.K.A", "Hog Glider", "Electrofire Wizard"]

DEFAULT_HOME_BUILDINGS = ["Gold Storage", "Elixir Storage", "Dark Elixir Storage", "Army Camp", "Barracks",
                          "Dark Barracks", "Spell Factory", "Dark Spell Factory", "Blacksmith", "Hero Hall",
                          "Laboratory", "Pet House", "Archer Tower", "Cannon", "Town Hall"]

# Base choice per Town Hall (from completeid.py): attack a base with at least this much loot
DEFAULT_MIN_LOOT_TH = {
    "19": {"gold": 0, "elixir": 1200000, "dark": 0},
    "18": {"gold": 0, "elixir": 1200000, "dark": 0},
    "17": {"gold": 0, "elixir": 1000000, "dark": 0},
    "16": {"gold": 0, "elixir": 800000, "dark": 0},
    "15": {"gold": 0, "elixir": 800000, "dark": 0},
    "14": {"gold": 0, "elixir": 800000, "dark": 0},
    "13": {"gold": 0, "elixir": 800000, "dark": 0},
    "12": {"gold": 0, "elixir": 800000, "dark": 0},
    "11": {"gold": 0, "elixir": 500000, "dark": 0},
}

DEFAULT_STEPS = {
    "attack_all": {"accounts": "1-15"},       # army, attack plan, max attack time: settings["loot"]
    "loot_current": {"account": "", "battle_seconds": 60, "army_recipe": "", "attack_plan": "edrag_spread",
                     "max_attacks": 0},       # account "" = the one open now; max_attacks 0 = until stopped
    "donate": {},                             # settings["donate"] and the roles on the Accounts list
    "bb_attack": {"accounts": "1-15"},        # army, battle time, limits: settings["builder"]
    "home_upgrade": {"accounts": "3-15", "buildings": list(DEFAULT_HOME_BUILDINGS), "max_per_visit": 5},
    "bb_upgrade": {"accounts": "3-15", "buildings": ["Cannon", "Archer Tower", "Mortar"], "new_first": True},
    "home_research": {"accounts": "3-15", "research": []},
    "bb_research": {"accounts": "3-15", "research": []},
}


def parse_positions(spec, count):
    """Account positions (1-based) from "1-15", "3, 5, 9-12" or "" / "all" (= every account).
    Returns them sorted, without repeats; numbers outside 1..count are left out."""
    spec = (spec or "").strip().lower()
    if not spec or spec == "all":
        return list(range(1, count + 1))
    out = set()
    for part in re.split(r"[,\s;]+", spec):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part) or re.fullmatch(r"(\d+)", part)
        if not m:
            continue
        a = int(m.group(1))
        b = int(m.group(2)) if m.lastindex == 2 else a
        out.update(range(min(a, b), max(a, b) + 1))
    return sorted(p for p in out if 1 <= p <= count)


def spec_ok(spec):
    """True if the text is a valid account list ("" = all)."""
    spec = (spec or "").strip().lower()
    return not spec or spec == "all" or all(re.fullmatch(r"\d+(\s*-\s*\d+)?", p.strip())
                                            for p in re.split(r"[,;]+", spec) if p.strip())


def step_accounts(spec, accounts, step=None):
    """The accounts a step works on: the positions in `spec`, in list order, skipping accounts whose
    "Use" is off or whose role is Skip - and for upgrades / research the Main and the Looters,
    always. Returns [(position, account)]."""
    skip = ("skip",) + (NO_UPGRADE_ROLES if step in UPGRADE_STEPS else ())
    return [(p, accounts[p - 1]) for p in parse_positions(spec, len(accounts))
            if accounts[p - 1].get("enabled", True) and accounts[p - 1].get("role") not in skip]


def describe_accounts(spec, accounts, limit=4, step=None):
    """Short text for the window: "Buggu01, Omishrisha, Buggu02 … Buggu7 (15 accounts)"."""
    picked = step_accounts(spec, accounts, step)
    if not picked:
        return "No accounts" if accounts else "No accounts yet (add them in Accounts)"
    names = [a["name"] for _, a in picked]
    text = ", ".join(names) if len(names) <= limit else ", ".join(names[:limit - 1]) + " … " + names[-1]
    return f"{text} ({len(names)} account{'s' if len(names) != 1 else ''})"


def segments(flow):
    """Split the flow into parts: runs of per-account steps (done account by account) and single
    steps that run once. Returns [("accounts", [keys]) | ("once", key)]."""
    out = []
    for key in flow:
        step = BY_KEY.get(key)
        if step is None:
            continue
        if step.per_account:
            if out and out[-1][0] == "accounts":
                out[-1][1].append(key)
            else:
                out.append(("accounts", [key]))
        else:
            out.append(("once", key))
    return out

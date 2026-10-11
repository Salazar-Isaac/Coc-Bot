"""Housing space and request keywords of donatable units (used to fill requests exactly).

Values are the game's housing space. Unknown names count as 1; the Donate page
lets you set any item's space by hand.
"""

import re

SPACE = {
    # troops
    "barbarian": 1, "archer": 1, "giant": 5, "goblin": 1, "wall breaker": 2, "balloon": 5,
    "wizard": 4, "healer": 14, "dragon": 20, "pekka": 25, "baby dragon": 10, "miner": 6,
    "electro dragon": 30, "yeti": 18, "dragon rider": 25, "electro titan": 32, "root rider": 20,
    "thrower": 16, "minion": 2, "hog rider": 5, "valkyrie": 8, "golem": 30, "witch": 12,
    "lava hound": 30, "bowler": 6, "ice golem": 15, "headhunter": 6, "apprentice warden": 20,
    "druid": 16, "furnace": 18,
    "super barbarian": 5, "super archer": 12, "super giant": 10, "sneaky goblin": 3,
    "super wall breaker": 8, "rocket balloon": 8, "super wizard": 10, "super dragon": 40,
    "inferno dragon": 15, "super minion": 12, "super valkyrie": 20, "super witch": 40,
    "ice hound": 40, "super bowler": 30, "super miner": 24, "super hog rider": 12,
    # spells
    "lightning": 1, "healing": 2, "heal": 2, "rage": 2, "jump": 2, "freeze": 1, "clone": 3,
    "invisibility": 1, "recall": 2, "revive": 2, "poison": 1, "earthquake": 1, "haste": 1,
    "skeleton": 1, "bat": 1, "overgrowth": 2, "ice block": 1,
}

SPELLS = {"lightning", "healing", "heal", "rage", "jump", "freeze", "clone", "invisibility", "recall",
          "revive", "poison", "earthquake", "haste", "skeleton", "bat", "overgrowth", "ice block"}
SIEGES = {"wall wrecker", "battle blimp", "stone slammer", "siege barracks", "log launcher",
          "flame flinger", "battle drill", "troop launcher"}

# extra words people type in requests
ALIASES = {
    "balloon": ["loon", "loons", "balloons"], "archer": ["archers", "arch"], "barbarian": ["barbs", "barb"],
    "wizard": ["wiz", "wizards"], "electro dragon": ["edrag", "edrags"],
    "dragon": ["drag", "drags", "dragons"], "baby dragon": ["baby drag", "bd"], "pekka": ["peka", "pekkas"],
    "hog rider": ["hog", "hogs"], "lava hound": ["lava", "hound"], "golem": ["golems"],
    "super archer": ["super archers"], "minion": ["minions"], "valkyrie": ["valk", "valks"],
    "healing": ["heal", "heals"], "lightning": ["zap"], "freeze": ["freezes"],
}


def norm(name):
    return re.sub(r"[^a-z ]", "", (name or "").lower().replace(".", "")).strip()


def category(name):
    n = norm(name)
    if any(s in n for s in SIEGES):
        return "siege"
    if n.replace(" spell", "") in SPELLS or n.endswith("spell"):
        return "spell"
    return "troop"


def space_of(name):
    return SPACE.get(norm(name).replace(" spell", ""), 1)


def keywords(name, extra=""):
    n = norm(name).replace(" spell", "")
    words = {n, n + "s"} | set(ALIASES.get(n, []))
    words |= {w.strip().lower() for w in (extra or "").split(",") if w.strip()}
    return {w for w in words if w}


def wants(message, item):
    """Does a request message ask for this item?"""
    text = " " + re.sub(r"[^a-z0-9 ]", " ", (message or "").lower()) + " "
    return any(f" {k} " in text for k in keywords(item.get("name", ""), item.get("keywords", "")))

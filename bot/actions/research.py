"""Laboratory research (home village) and Star Laboratory research (Builder Base).

The lab counter at the top ("1/2" free) opens the research list, like the builder menu. When a
lab is free, the first unit of your list that is listed with an affordable price is started
(an empty list: the first affordable one the game lists). Only gold / elixir / dark elixir
prices, confirmed on the window's Confirm button - never gems.
"""

import logging
import re

from ..core import vision
from . import timers, village

log = logging.getLogger("bot")

# like upgrades.MAIN / upgrades.BB: the menu button, its counter and an empty spot to tap
HOME = {"counter": "top.lab", "menu": "top.lab_menu", "tab": "build.tab_lab", "safe": "home.safe",
        "label": "Laboratory"}
BUILDER = {"counter": "bb.lab", "menu": "bb.lab_menu", "tab": "bb.build_tab_lab", "safe": "bb.safe",
           "label": "Star Laboratory"}


def _norm(name):
    return re.sub(r"[^a-z]", "", (name or "").lower().replace("spell", ""))


def rank(row_name, wanted):
    """Position of the row in your list (part of a name is enough), or None if it is not on it."""
    n = _norm(row_name)
    for i, w in enumerate(wanted):
        w = _norm(w)
        if w and (w in n or n in w):
            return i
    return None


def run(bot, account, wanted, builder=False):
    """Start one research on this account's lab if it is free. Returns True if one started.
    When the lab is (or becomes) fully busy, the time it is free again is remembered (timers)."""
    from . import upgrades
    from .builder_base import go_home_bb, status
    from .loot import home_resources
    from ..states import go_home
    where = BUILDER if builder else HOME
    kind = "builder_lab" if builder else "lab"
    home = go_home_bb if builder else go_home
    if not home(bot, 15):
        return False
    if upgrades.refuse(bot, account, "research"):
        return False
    counter = vision.digits.read_fraction(bot.shot(), bot.layout.region(where["counter"]))
    if not counter or counter[0] <= 0:
        log.info("%s: %s busy%s", account["name"], where["label"], f" ({counter[0]}/{counter[1]})" if counter else "")
        if counter:
            timers.note_busy(bot, account, kind, where)
        return False
    have = status(bot) if builder else home_resources(bot)

    def first_found(rows):                             # the first unit of your list, affordable: stop here
        return bool(wanted) and any(upgrades._affordable(r, have) and rank(r["name"], wanted) == 0 for r in rows)

    rows = upgrades.scan(bot, where, enough=first_found)   # the research list (scrolls through it)
    ok = [r for r in rows if upgrades._affordable(r, have)]
    if wanted:
        ranked = [(rank(r["name"], wanted), r) for r in ok]
        ok = [r for i, r in sorted((x for x in ranked if x[0] is not None), key=lambda x: x[0])]
    if not ok:
        log.info("%s: no research %sis affordable now (%d listed)", account["name"],
                 "from your list " if wanted else "", len(rows))
        village.close_menu(bot, where["safe"])
        timers.clear(bot, account, kind)
        return False
    item = ok[0]
    log.info("%s: researching %s for %s %s", account["name"], item["name"], f"{item['cost']:,}", item["res"])
    if item.get("last"):
        bot.tap(*item["tap"], jitter=2)                # still on screen: tap it
    elif not upgrades._open_row(bot, item, where, home):
        log.info("Could not find %s in the research list again", item["name"])
        village.close_menu(bot, where["safe"])
        return False
    bot.sleep(1.5)
    started = village._confirm(bot, dict(item, have=have.get(item["res"])), "lab",
                               home=go_home_bb if builder else None)
    home(bot, 20)
    if started:
        bot.stats["research"] = bot.stats.get("research", 0) + 1
        now = vision.digits.read_fraction(bot.shot(), bot.layout.region(where["counter"]))
        if now and now[0] <= 0:
            timers.note_busy(bot, account, kind, where)
    return started

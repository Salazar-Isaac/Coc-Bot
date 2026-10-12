"""Upgrade plans, used by the "Loot + Upgrade" and "Builder Base upgrades" modes on the accounts
ticked "Upgrade" on the Accounts page (your other accounts: not the Main or the Omi account).

Main village, in this order (the first step with an affordable upgrade wins, so a builder never
waits for an expensive item; walls, heroes, traps and other buildings are never touched):

  1. Gold Storage, Elixir Storage, Dark Elixir Storage
  2. Army Camp
  3. Barracks, Dark Barracks, Spell Factory, Dark Spell Factory   (unlock troops and spells)
  4. Blacksmith
  5. Hero Hall
  6. Laboratory, Pet House
  7. Archer Tower, Cannon
  8. the buildings you add on the Upgrades page ("Also upgrade")
  9. Town Hall - only when nothing of 1-8 can be upgraded any more at this Town Hall level.
     From Town Hall 16 on the Town Hall's weapon gets all its levels (5 stars) before the next
     Town Hall.

Builder Base (gear up): new buildings unlocked by the Builder Hall are built first, then the
buildings on your list (default Cannon, Archer Tower, Mortar), and the Builder Hall when none of
those can be upgraded any more - which unlocks more buildings and levels, and so on.

Prices are always read from the game (they change with updates and sales): a row is found again by
its name, and before confirming the price on the Confirm button is checked against what the account
has. Gems are never spent: only gold / elixir / dark elixir, and only the Confirm button that shows a
resource price is pressed (see village._confirm).
"""

import difflib
import logging
import re
import time

import cv2
import numpy as np

from ..core import vision
from ..core.control import control
from ..core.space import space
from .. import states
from ..states import go_home
from . import loot, village

log = logging.getLogger("bot")

PLAN = [
    ("storages", ["Gold Storage", "Elixir Storage", "Dark Elixir Storage"]),
    ("army camp", ["Army Camp"]),
    ("troops and spells", ["Barracks", "Dark Barracks", "Spell Factory", "Dark Spell Factory"]),
    ("blacksmith", ["Blacksmith"]),
    ("hero hall", ["Hero Hall"]),
    ("laboratory and pets", ["Laboratory", "Pet House"]),
    ("defences", ["Archer Tower", "Cannon"]),
]
TOWN_HALL = "Town Hall"
BB_DEFAULT = ["Cannon", "Archer Tower", "Mortar"]
BUILDER_HALL = "Builder Hall"
# the Town Hall's weapon is listed under its own name (Giga Tesla, Giga Inferno, ...)
WEAPON_WORDS = ("giga", "weapon")
MENU = (430, 118, 860, 590)          # builder menu panel around its counter: half width, top, width, height

# where each village keeps its builder menu, its builder counter and an empty spot to tap
MAIN = {"menu": "top.builders_menu", "counter": "top.builders", "safe": "home.safe"}
BB = {"menu": "bb.builders_menu", "counter": "bb.builders", "safe": "bb.safe"}


# every building name the menus can show: a name read with a slip ("ArchereTower") is matched to the
# closest of these, so the plan still finds it (and "Elixir Storage" never becomes "Dark Elixir Storage")
KNOWN = ["Gold Storage", "Elixir Storage", "Dark Elixir Storage", "Army Camp", "Barracks", "Dark Barracks",
         "Spell Factory", "Dark Spell Factory", "Blacksmith", "Hero Hall", "Laboratory", "Pet House", "Archer Tower",
         "Cannon", "Town Hall", "Workshop", "Clan Castle", "Builder's Hut", "Gold Mine", "Elixir Collector",
         "Dark Elixir Drill", "Mortar", "Air Defense", "Wizard Tower", "Air Sweeper", "Hidden Tesla", "Bomb Tower",
         "X-Bow", "Inferno Tower", "Eagle Artillery", "Scattershot", "Spell Tower", "Monolith", "Multi-Archer Tower",
         "Ricochet Cannon", "Multi-Gear Tower", "Firespitter", "Wall", "Bomb", "Spring Trap", "Giant Bomb", "Air Bomb",
         "Seeking Air Mine", "Skeleton Trap", "Tornado Trap", "Giga Bomb", "Barbarian King", "Archer Queen",
         "Grand Warden", "Royal Champion", "Minion Prince", "Dragon Duke",
         # Builder Base
         "Builder Hall", "Double Cannon", "Multi Mortar", "Firecrackers", "Crusher", "Guard Post", "Air Bombs",
         "Roaster", "Giant Cannon", "Mega Tesla", "Lava Launcher", "Builder Barracks", "Clock Tower",
         "Star Laboratory", "Gem Mine", "Healing Hut", "Reinforcement Camp", "O.T.T.O's Outpost", "Push Trap",
         "Mine", "Mega Mine", "Battle Machine", "Battle Copter"]


def _norm(name):
    n = re.sub(r"[^a-z0-9]", "", name.lower())
    return re.sub(r"x\d+$", "", n)


_KNOWN = {_norm(n) for n in KNOWN}


def _base(name):
    """The building a menu row is about: 'Elixir Collector x6' / 'ElixirCollectorx6' -> 'elixircollector';
    a name with a reading slip becomes the closest known building ('archeretower' -> 'archertower')."""
    n = _norm(name)
    if not n or n in _KNOWN:
        return n
    best = max(_KNOWN, key=lambda k: difflib.SequenceMatcher(None, n, k).ratio())
    if difflib.SequenceMatcher(None, n, best).ratio() >= 0.82:
        return best
    words = name.split()
    if len(words) > 1:                                # a label of the village behind the menu ("Research")
        return _base(" ".join(words[:-1]))
    return n


def plan_groups(settings):
    """The main village plan: the fixed steps, then the buildings you added ("Also upgrade")."""
    groups = [(title, [_base(n) for n in names]) for title, names in PLAN]
    extra = [_base(n) + "*" for n in settings.get("upgrades", {}).get("extra", []) if _base(n)]
    if extra:
        groups.append(("your extra buildings", extra))
    return groups


def _matches(row_base, wanted):
    """A plan entry matches its building exactly ("Elixir Storage" is not "Dark Elixir Storage");
    an entry you typed yourself may also be the start of a name ("Wizard" = Wizard Tower)."""
    if wanted.endswith("*"):
        return row_base.startswith(wanted[:-1])
    return row_base == wanted


def _is_weapon(row):
    low = row["name"].lower()
    return any(w in low for w in WEAPON_WORDS) and not any(t in low for t in ("bomb", "tower", "mine"))


# --- reading the builder menu ------------------------------------------------------------------

def _panel(bot, where):
    cx = bot.layout.point(where["menu"])[0]
    half, top, w, h = MENU
    return (max(0, cx - space.s(half)), space.point(0, top)[1], space.s(w), space.s(h)), cx


def _is_cost(text):
    return len(re.sub(r"\D", "", text)) >= 4 and not re.search(r"[A-Za-z]{3,}", text)


def _read_page(frame, region, cols, section):
    """Rows with a price on one page of the open builder menu.
    cols: [name column x, price column right edge] learned from a page that shows a header
    (updated in place); section: the section the page starts in. Returns (rows, section at the end)."""
    lines = sorted(vision.text_reader.read(frame, region), key=lambda t: (t[2][1], t[2][0]))
    for t, c, b in lines:
        if t.lower().replace(" ", "").rstrip(":").endswith(("progress", "upgrades")):
            cols[0] = b[0] if cols[0] is None else min(cols[0], b[0])
    if cols[0] is None:
        return [], section
    costs = [b for t, c, b in lines if _is_cost(t) and b[0] > cols[0] + space.s(150)]
    if costs:
        cols[1] = max(b[0] + b[2] for b in costs)
    if cols[1] is None:
        return [], section
    left, right = cols
    names, prices = [], []
    for text, conf, box in lines:
        low = text.lower().replace(" ", "")
        x, y, w, h = box
        if abs(x - left) < space.s(25) and low.rstrip(":").endswith(("progress", "upgrades")):
            section = "progress" if "progress" in low else ("suggested" if "suggested" in low else "other")
            continue
        if _is_cost(text) and abs(x + w - right) < space.s(40):
            exact = vision.digits.read(frame, (x - 4, y - 2, w + 8, h + 4))
            digits = re.sub(r"\D", "", text)
            cost = exact if exact and len(str(exact)) >= len(digits) else int(digits)
            if cost >= 100 and section in ("suggested", "other"):
                prices.append({"cost": cost, "box": box, "section": section})
        elif conf > 0.5 and section in ("suggested", "other") and left - 10 <= x < right - space.s(120):
            names.append((text, box, conf))
    rows = []
    for p in prices:
        cy = p["box"][1] + p["box"][3] / 2
        parts = sorted((n for n in names if abs(n[1][1] + n[1][3] / 2 - cy) < space.s(16) and n[1][0] < p["box"][0]),
                       key=lambda n: n[1][0])
        if not parts or p["box"][1] + p["box"][3] > region[1] + region[3] - space.s(30):
            continue                                  # no name, or cut off at the bottom
        if min(c for _, _, c in parts) < 0.8:
            continue                                  # unsure what it is: never upgrade a guess
        raw = " ".join(t for t, _, _ in parts)
        is_new = bool(re.match(r"^\s*New\b", raw))
        name = re.sub(r"^New\s*:?\s*", "", raw).strip()
        nbox = parts[0][1]
        rows.append({"name": name, "base": _base(name), "cost": p["cost"], "new": is_new,
                     "res": village._icon_resource(frame, p["box"]), "red": village._is_red(frame, p["box"]),
                     "section": p["section"], "tap": (nbox[0] + min(nbox[2], space.s(160)) // 2, nbox[1] + nbox[3] // 2)})
    return rows, section


def _scroll(bot, region, cx):
    """About half a page down: every row is seen on two pages, so none is missed at a page edge."""
    x, y, w, h = region
    bot.swipe((cx, y + h - space.s(80)), (cx, y + h - space.s(80) - space.s(300)), 600)
    bot.sleep(0.7)


def scan(bot, where=MAIN, max_pages=14):
    """Open a builder menu and read every upgradable item (scrolling through the list).
    Each row gets the page it is on. The menu is left open, scrolled to the end."""
    village.close_menu(bot, where["safe"])           # a menu left open: tapping its button would close it
    bot.tap_point(where["menu"])
    bot.sleep(1.0)
    region, cx = _panel(bot, where)
    cols, section = [None, None], "progress"
    seen, out = set(), []
    last = None
    for page in range(max_pages):
        rows, section = _read_page(bot.shot(), region, cols, section)
        sig = tuple((r["base"], r["cost"]) for r in rows)
        if page and sig == last:
            break                                     # the list did not move: end reached
        last = sig
        for r in rows:
            key = (r["base"], r["cost"])
            if key not in seen:
                seen.add(key)
                out.append(dict(r, page=page))
        _scroll(bot, region, cx)
    return out


def _open_row(bot, item, where=MAIN, home=None):
    """Re-open the menu, scroll to the item and tap it. The row is found by its name (its price
    may have changed since the list was read, e.g. a sale); with several rows of that name the
    one with the closest price. True if tapped."""
    village.close_menu(bot, where["safe"])
    (home or go_home)(bot, 15)
    bot.tap_point(where["menu"])
    bot.sleep(1.0)
    region, cx = _panel(bot, where)
    cols, section = [None, None], "progress"
    for page in range(item["page"] + 4):
        rows, section = _read_page(bot.shot(), region, cols, section)
        same = [r for r in rows if r["base"] == item["base"] and r.get("new") == item.get("new")
                and not r["red"]]
        if same:
            hit = min(same, key=lambda r: abs(r["cost"] - item["cost"]))
            if hit["cost"] != item["cost"]:
                log.info("%s: price changed from %s to %s", item["name"], f"{item['cost']:,}", f"{hit['cost']:,}")
                item["cost"] = hit["cost"]
            bot.tap(*hit["tap"], jitter=2)
            return True
        _scroll(bot, region, cx)
    return False


def _affordable(r, have):
    """The game draws a price it cannot pay in red - that is the reliable sign (a price read off the
    see-through menu can lose a digit). The amount read is only a second check: the real price on the
    Confirm button is compared with what the account has before anything is confirmed."""
    return (r["res"] in ("gold", "elixir", "dark") and not r["red"] and have.get(r["res"]) is not None
            and have[r["res"]] >= r["cost"])


# --- main village ----------------------------------------------------------------------------------

def choose(rows, have, groups=None):
    """The upgrade to start (or None): the first group of the plan with an affordable item;
    the Town Hall (weapon first) only when no plan building is listed any more."""
    groups = groups or plan_groups({})
    listed = False
    for title, bases in groups:
        group = [r for r in rows if not r.get("new") and any(_matches(r["base"], b) for b in bases)]
        listed = listed or bool(group)
        for base in bases:                            # the plan's own order inside a group
            ok = [r for r in group if _matches(r["base"], base) and _affordable(r, have)]
            if ok:
                return dict(min(ok, key=lambda r: r["cost"]), group=title)
    if listed:
        return None                                   # plan buildings not maxed yet: no Town Hall
    weapon = [r for r in rows if _is_weapon(r)]
    if weapon:                                        # Town Hall 16+: all weapon levels first
        ok = [r for r in weapon if _affordable(r, have)]
        return dict(ok[0], group="town hall weapon") if ok else None
    th_rows = [r for r in rows if r["base"] == _base(TOWN_HALL)]
    ok = [r for r in th_rows if _affordable(r, have)]
    return dict(ok[0], group="town hall") if ok else None


def _start(bot, item, where, home):
    """Tap the item in the menu and confirm its upgrade. True if it started."""
    if not _open_row(bot, item, where, home):
        log.info("Could not find %s in the menu again", item["name"])
        village.close_menu(bot, where["safe"])
        return False
    bot.sleep(1.2)
    up = bot.wait("building/upgrade_button", 4)
    if not up:
        log.info("%s: no Upgrade button", item["name"])
        village.close_menu(bot, where["safe"])
        return False
    bot.tap_match(up)
    bot.sleep(1.2)
    ok = village._confirm(bot, item, "builders", home=None if home is go_home else home)
    village.close_menu(bot, where["safe"])
    return ok


def run(bot, account, when="", max_count=None):
    """Use the free builders on the main village plan. Returns the number of upgrades started.
    The menu is read once; the builders are then given one item after another (what is left to
    spend goes down with each one), and the list is only read again if something did not work."""
    cfg = bot.settings.get("upgrades", {})
    if not cfg.get("enabled", True) or not account.get("upgrade"):
        return 0
    max_count = max_count if max_count is not None else cfg.get("max_per_visit", 5)
    groups = plan_groups(bot.settings)
    started, rows, have, fails = 0, None, None, 0
    refused = set()                                   # not accepted this visit: not tried again
    while started < max_count and fails < 2:
        control.checkpoint()
        if not go_home(bot):
            break
        counter = village.read_counter(bot, "builders")
        if not counter or counter[0] <= 0:
            if started == 0:
                log.info("%s: no free builder%s", account["name"], f" ({counter[0]}/{counter[1]})" if counter else "")
            break
        have = loot.home_resources(bot)               # fresh after each upgrade (never a guessed amount)
        if rows is None:
            rows = scan(bot, MAIN)
        item = choose([r for r in rows if r["base"] not in refused], have, groups)
        if not item:
            log.info("%s: nothing in the upgrade plan is affordable now (%d upgradable items listed)",
                     account["name"], len(rows))
            village.close_menu(bot)
            break
        log.info("%s%s: upgrading %s (%s) for %s %s", account["name"], f" {when}" if when else "", item["name"],
                 item["group"], f"{item['cost']:,}", item["res"])
        item["have"] = have.get(item["res"])
        item["free_before"] = counter[0]
        listed = (item["base"], item["cost"])        # as read in the list (the price may be corrected)
        if _start(bot, item, MAIN, go_home):
            started += 1
            bot.stats["upgrades"] = bot.stats.get("upgrades", 0) + 1
            rows = [r for r in rows if (r["base"], r["cost"]) != listed]
        else:
            fails += 1
            refused.add(item["base"])
            rows = None                               # read the menu again
    go_home(bot)
    return started


# --- Builder Base (gear up) ---------------------------------------------------------------------------

def choose_bb(rows, have, plan):
    """New buildings first, then your list in its order, then the Builder Hall once nothing on the
    list can be upgraded any more (it unlocks new buildings and levels)."""
    new = [r for r in rows if r.get("new") and _affordable(r, have)]
    if new:
        return dict(min(new, key=lambda r: r["cost"]), group="new building")
    wanted = [_base(n) + "*" for n in plan if _base(n)]
    listed = False
    for w in wanted:
        group = [r for r in rows if not r.get("new") and _matches(r["base"], w)]
        listed = listed or bool(group)
        ok = [r for r in group if _affordable(r, have)]
        if ok:
            return dict(min(ok, key=lambda r: r["cost"]), group="your list")
    if listed:
        return None                                   # your list is not maxed yet: no Builder Hall
    bh = [r for r in rows if r["base"] == _base(BUILDER_HALL) and _affordable(r, have)]
    return dict(bh[0], group="builder hall") if bh else None


def _build_new(bot, item, home):
    """A new building from the builder menu: the game opens the Shop with an arrow pointing at its
    card; tap the card, and the game puts the building on a free spot - confirm it with the green
    tick (a spot that is not free leaves the building there: then cancel with the red X).
    Only rows with a gold / elixir price get here (gem prices, e.g. B.O.T.O's Shack, never).
    True if it was placed."""
    if not _open_row(bot, item, BB, home):
        log.info("Could not find %s in the menu again", item["name"])
        village.close_menu(bot, BB["safe"])
        return False
    bot.sleep(1.5)
    # the arrow's tip (it can be half off the screen for a card at the right edge) sits on the
    # card's top-right corner: the card is just below-left of it
    tip = bot.wait("shop/new_arrow_tip", 6)
    if not tip:
        log.info("%s: the Shop did not point at it", item["name"])
        bot.save_error("bb-new-arrow")
        home(bot, 20)
        return False
    bot.tap(tip.box[0] - space.s(40), tip.box[1] + tip.box[3] + space.s(52), jitter=3)
    tick = None
    end = time.monotonic() + 6
    last = None
    while time.monotonic() < end:                     # wait for the tick, with the camera standing still
        control.sleep(0.4)
        f = bot.shot()
        small = cv2.resize(f, (480, 270)).astype(np.int16)
        still = last is not None and np.abs(small - last).mean() < 1.5
        last = small
        tick, _ = states.placement(f)
        if tick and still:
            break
    if not tick:
        log.info("%s: it was not put on the village (no free spot, or not affordable)", item["name"])
        bot.save_error("bb-new-building")
        states.cancel_placement(bot)
        home(bot, 20)
        return False
    from .builder_base import status
    gold = status(bot).get(item["res"]) if item["res"] in ("gold", "elixir") else None
    placed = 0
    for _ in range(8):                                 # traps come several at a time ("Mine x2")
        bot.tap_match(tick, jitter=1)
        bot.sleep(1.5)
        tick, _ = states.placement(bot.shot())
        now = status(bot).get(item["res"]) if gold is not None else None
        paid = gold is None or (now is not None and now < gold)
        if paid:
            placed += 1
            gold = now
        if not tick:
            break                                      # placed and done
        if not paid:                                   # the tick did nothing: not a free spot
            log.info("%s: no free spot for it; cancelled", item["name"])
            states.cancel_placement(bot)
            break
        bot.sleep(0.5)                                 # the next copy is waiting: place it too
    home(bot, 20)
    if not placed:
        return False
    log.info("Built a new %s for %s %s", item["name"], f"{item['cost']:,}", item["res"])
    return True


def run_bb(bot, account, when="", max_count=None):
    """Builder Base plan (you must be in the Builder Base). Returns the number started."""
    from .builder_base import go_home_bb, status
    cfg = bot.settings.get("upgrades", {})
    if not cfg.get("enabled", True) or not account.get("upgrade"):
        return 0
    max_count = max_count if max_count is not None else cfg.get("max_per_visit", 5)
    plan = cfg.get("bb_plan", BB_DEFAULT)
    started, rows, have, fails = 0, None, None, 0
    skipped = set()                                   # new buildings that could not be placed this visit
    while started < max_count and fails < 3:
        control.checkpoint()
        if not go_home_bb(bot, 20):
            break
        counter = vision.digits.read_fraction(bot.shot(), bot.layout.region(BB["counter"]))
        if not counter or counter[0] <= 0:
            if started == 0:
                log.info("%s Builder Base: no free builder", account["name"])
            break
        st = status(bot)
        have = {"gold": st.get("gold"), "elixir": st.get("elixir")}
        if rows is None:
            rows = scan(bot, BB)
        item = choose_bb([r for r in rows if not (r.get("new") and r["base"] in skipped)], have, plan)
        if not item:
            log.info("%s Builder Base: nothing in the plan is affordable now (%d items listed)",
                     account["name"], len(rows))
            village.close_menu(bot, BB["safe"])
            break
        log.info("%s Builder Base%s: %s %s (%s) for %s %s", account["name"], f" {when}" if when else "",
                 "building" if item.get("new") else "upgrading", item["name"], item["group"],
                 f"{item['cost']:,}", item["res"])
        item["have"] = have.get(item["res"])
        item["free_before"] = counter[0]
        listed = (item["base"], item["cost"])
        ok = _build_new(bot, item, go_home_bb) if item.get("new") else _start(bot, item, BB, go_home_bb)
        if ok:
            started += 1
            bot.stats["upgrades"] = bot.stats.get("upgrades", 0) + 1
            rows = [r for r in rows if (r["base"], r["cost"]) != listed]
        else:
            fails += 1
            rows = None
            if item.get("new"):
                skipped.add(item["base"])             # go on with the rest of the plan
    go_home_bb(bot, 20)
    return started

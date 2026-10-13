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
MAIN = {"menu": "top.builders_menu", "tab": "build.tab_builders", "counter": "top.builders", "safe": "home.safe"}
BB = {"menu": "bb.builders_menu", "tab": "bb.build_tab_builders", "counter": "bb.builders", "safe": "bb.safe"}


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
# Since the 2026-10 UI the builder and laboratory menus are one side panel on the right (the Build
# button, bottom right), with tabs at its bottom. A row: name on the first line, the time on the
# right of it, the price under the time (right-aligned, its resource icon RIGHT of it); "New" under
# the name for a building not built yet. Upgrades in progress come first (no header), then
# "Suggested upgrades" and "Other upgrades". Tapping a row opens its upgrade window directly.

PANEL = (1410, 70, 505, 890)          # the list part of the side panel (above its tabs)
NAME_X = (1475, 1530)                 # names start here (after the picture)
PRICE_RIGHT = 1880                    # prices end here (their resource icon is right of them)


def open_menu(bot, where):
    """Open the side panel on this menu's tab. True if it is open."""
    if bot.exists("build/close"):
        bot.tap_point("build.close")                  # start from the top of the list
        bot.sleep(0.6)
    bot.tap_point(where["menu"])
    if not bot.wait("build/close", 4, interval=0.2):
        return False
    bot.tap_point(where["tab"])
    bot.sleep(0.9)
    return True


def _panel(bot, where):
    return space.region(*PANEL), space.point(PANEL[0] + PANEL[2] // 2, 0)[0]


def _is_cost(text):
    return len(re.sub(r"\D", "", text)) >= 3 and not re.search(r"[A-Za-z]", text)


def _resource_right(frame, box):
    """The resource icon right of a price: gold / elixir / dark / gems (the panel itself is brown,
    so its colour is not counted: only the icons' own colours)."""
    x, y, w, h = box
    patch = frame[max(0, y - 2):y + h + 2, x + w:x + w + space.s(30)]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    hue, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    counts = {"elixir": ((hue >= 125) & (hue <= 170) & (sat > 80) & (val > 80)).sum(),
              "gold": ((hue >= 20) & (hue <= 35) & (sat > 150) & (val > 180)).sum(),
              "gems": ((hue >= 40) & (hue <= 95) & (sat > 100) & (val > 100)).sum() * 2.5}
    best = max(counts, key=counts.get)
    if counts[best] > 100:
        return best
    return "dark" if (val < 60).sum() > 150 else None


def _moved(a, b):
    """Did the list move between two pictures of it? (a scroll changes far more of it than the
    small animations of the panel do)"""
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
    return float((d > 60).mean()) > 0.09


def _read_page(frame, region, cols, section):
    """Rows with a price on one page of the open panel (cols: kept for the callers, unused);
    section: the section the page starts in. Returns (rows, section at the end)."""
    lines = sorted(vision.text_reader.read(frame, region), key=lambda t: (t[2][1], t[2][0]))
    sx = space.s(100) / 100
    lo, hi = space.point(NAME_X[0], 0)[0], space.point(NAME_X[1], 0)[0]
    right = space.point(PRICE_RIGHT, 0)[0]
    names, prices, news, heads = [], [], [], []
    for text, conf, box in lines:
        x, y, w, h = box
        low = re.sub(r"[^a-z]", "", text.lower())
        if low.endswith("upgrades") and ("suggested" in low or "other" in low):
            heads.append((y, "suggested" if "suggested" in low else "other"))
        elif _is_cost(text) and abs(x + w - right) < 30 * sx:
            exact = vision.digits.read(frame, (x - 4, y - 2, w + 8, h + 4))
            digits = re.sub(r"\D", "", text)
            cost = exact if exact and len(str(exact)) >= len(digits) else int(digits)
            prices.append({"cost": cost, "box": box})
        elif low == "new" and lo - 20 * sx <= x <= hi:
            news.append(box)
        elif conf > 0.5 and lo <= x <= hi:
            names.append((text, box, conf))

    def section_at(y):
        sec = section
        for hy, name in heads:
            if hy < y:
                sec = name
        return sec

    rows = []
    for p in prices:
        px, py, pw, ph = p["box"]
        sec = section_at(py)
        if sec not in ("suggested", "other"):
            continue
        if py + ph > region[1] + region[3] - 10 * sx:
            continue                                  # cut off at the bottom
        above = [n for n in names if py - 50 * sx <= n[1][1] < py - 5 * sx]
        if not above:
            continue                                  # its name is cut off at the top
        text, nbox, conf = max(above, key=lambda n: n[1][1])
        if conf < 0.8:
            continue                                  # unsure what it is: never upgrade a guess
        is_new = any(abs(b[1] - py) < 25 * sx for b in news)
        rows.append({"name": text.strip(), "base": _base(text), "cost": p["cost"], "new": is_new,
                     "res": _resource_right(frame, p["box"]), "red": village._is_red(frame, p["box"]),
                     "section": sec,
                     "tap": (nbox[0] + min(nbox[2], space.s(160)) // 2, nbox[1] + nbox[3] // 2)})
    if heads:
        section = heads[-1][1]
    return rows, section


def _scroll(bot, region, cx):
    """About half a page down: every row is seen on two pages, so none is missed at a page edge.
    Returns False if the list did not move (its end) - a swipe that did not take is tried again."""
    x, y, w, h = region
    before = bot.shot()[y:y + h, x:x + w]
    for _ in range(2):
        bot.swipe((cx, y + h - space.s(80)), (cx, y + h - space.s(80) - space.s(300)), 600)
        bot.sleep(0.7)
        if _moved(before, bot.shot()[y:y + h, x:x + w]):
            return True
    return False


def scan(bot, where=MAIN, max_pages=14, enough=None):
    """Open a builder menu and read every upgradable item (scrolling through the list).
    Each row gets the page it is on. The menu is left open, scrolled to the end - or, when
    enough(rows) says so after a page, left on that page (its rows can be tapped right away)."""
    if not open_menu(bot, where):
        return []
    region, cx = _panel(bot, where)
    cols, section = [None, None], "progress"
    seen, out = set(), []
    for page in range(max_pages):
        rows, section = _read_page(bot.shot(), region, cols, section)
        for r in rows:
            key = (r["base"], r["cost"])
            if key not in seen:
                seen.add(key)
                out.append(dict(r, page=page, last=True))
        if enough is not None and enough(out):
            for r in out:
                r["last"] = r["page"] == page            # on screen now
            return out
        if not _scroll(bot, region, cx):
            break                                     # the list did not move: end reached
    for r in out:
        r["last"] = False
    return out


def _open_row(bot, item, where=MAIN, home=None):
    """Re-open the menu, scroll to the item and tap it. The row is found by its name (its price
    may have changed since the list was read, e.g. a sale); with several rows of that name the
    one with the closest price. True if tapped."""
    village.close_menu(bot, where["safe"])
    (home or go_home)(bot, 15)
    if not open_menu(bot, where):
        return False
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
        if not _scroll(bot, region, cx):
            break                                     # end of the list
    return False


def _affordable(r, have):
    """The game draws a price it cannot pay in red - that is the reliable sign (a price read off the
    see-through menu can lose a digit). The amount read is only a second check: the real price on the
    Confirm button is compared with what the account has before anything is confirmed."""
    return (r["res"] in ("gold", "elixir", "dark") and not r["red"] and have.get(r["res"]) is not None
            and have[r["res"]] >= r["cost"])


# --- main village ----------------------------------------------------------------------------------

def list_groups(buildings):
    """The flow's own building list as plan groups (one building each, in its order) and whether
    the Town Hall is on it."""
    th = _base(TOWN_HALL)
    groups = [(b, [_base(b) if _base(b) in _KNOWN else _base(b) + "*"])   # a name not known: its start
              for b in buildings if b.strip() and _base(b) != th]
    return groups, any(b.strip() and _base(b) == th for b in buildings)


def choose(rows, have, groups=None, town_hall=True):
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
    if listed or not town_hall:
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
    # the 2026-10 UI opens the upgrade window straight from the row; the older one first selected
    # the building and showed an Upgrade button
    key, m = bot.wait_any(["upgrade/confirm", "upgrade/close", "building/upgrade_button"], 5)
    if key == "building/upgrade_button":
        bot.tap_match(m)
        bot.sleep(1.2)
    elif key is None:
        log.info("%s: its upgrade window did not open", item["name"])
        village.close_menu(bot, where["safe"])
        return False
    ok = village._confirm(bot, item, "builders", home=None if home is go_home else home)
    village.close_menu(bot, where["safe"])
    return ok


def run(bot, account, when="", max_count=None, buildings=None):
    """Use the free builders on the main village plan. Returns the number of upgrades started.
    The menu is read once; the builders are then given one item after another (what is left to
    spend goes down with each one), and the list is only read again if something did not work.
    buildings: the flow's own list (in order; the Town Hall only if it is on it). When all
    builders end up busy, the time the first one is free again is remembered (timers)."""
    from . import timers
    cfg = bot.settings.get("upgrades", {})
    if buildings is None and (not cfg.get("enabled", True) or not account.get("upgrade")):
        return 0
    max_count = max_count if max_count is not None else cfg.get("max_per_visit", 5)
    if buildings is None:
        groups, town_hall = plan_groups(bot.settings), True
    else:
        groups, town_hall = list_groups(buildings)
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
            if counter:
                timers.note_busy(bot, account, "builders", MAIN)
            break
        have = loot.home_resources(bot)               # fresh after each upgrade (never a guessed amount)
        if rows is None:
            rows = scan(bot, MAIN)
        item = choose([r for r in rows if r["base"] not in refused], have, groups, town_hall)
        if not item:
            log.info("%s: nothing in the upgrade plan is affordable now (%d upgradable items listed)",
                     account["name"], len(rows))
            village.close_menu(bot)
            timers.clear(bot, account, "builders")
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
            if item.get("builders_busy"):             # only the Goblin Builder (gems) was "free"
                timers.note_busy(bot, account, "builders", MAIN)
                break
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
    # older UI: the Shop opens with an arrow at the card; the arrow's tip (it can be half off the
    # screen for a card at the right edge) sits on the card's top-right corner. The 2026-10 UI may
    # put the building on the village straight away: then there is no Shop step.
    tip, end = None, time.monotonic() + 6
    while time.monotonic() < end:
        f = bot.shot()
        if states.placement(f)[0]:
            break                                      # already waiting to be placed
        tip = vision.find(f, "shop/new_arrow_tip") if vision.templates.has("shop/new_arrow_tip") else None
        if tip:
            break
        control.sleep(0.4)
    if tip:
        bot.tap(tip.box[0] - space.s(40), tip.box[1] + tip.box[3] + space.s(52), jitter=3)
    elif not states.placement(bot.shot())[0]:
        log.info("%s: neither the Shop nor the building to place showed up", item["name"])
        bot.save_error("bb-new-building")
        home(bot, 20)
        return False
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


def run_bb(bot, account, when="", max_count=None, plan=None, new_first=True):
    """Builder Base plan (you must be in the Builder Base). Returns the number started.
    plan: the flow's own list (new buildings first when new_first, then the list, then the
    Builder Hall)."""
    from .builder_base import go_home_bb, status
    cfg = bot.settings.get("upgrades", {})
    if plan is None and (not cfg.get("enabled", True) or not account.get("upgrade")):
        return 0
    max_count = max_count if max_count is not None else cfg.get("max_per_visit", 5)
    plan = plan if plan is not None else cfg.get("bb_plan", BB_DEFAULT)
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
        item = choose_bb([r for r in rows if not (r.get("new") and (r["base"] in skipped or not new_first))],
                         have, plan)
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

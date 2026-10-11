"""Upgrade plan for the accounts ticked "Upgrade" on the Accounts page (your other accounts:
not the Main or the Omi account).

When the bot visits such an account to loot, it first puts free builders to work if there are
resources for it, loots, and after looting it uses the builders again. Upgrades are started in
this order; within the order the first group that has an affordable upgrade wins, so a builder
is never left idle because the top item is too expensive. Walls, heroes, traps and every other
building are never touched.

  1. Gold Storage, Elixir Storage, Dark Elixir Storage
  2. Army Camp
  3. Barracks, Dark Barracks, Spell Factory, Dark Spell Factory   (unlock troops and spells)
  4. Blacksmith
  5. Hero Hall
  6. Laboratory, Pet House
  7. Archer Tower, Cannon
  8. Town Hall - only when nothing of 1-7 can be upgraded any more at this Town Hall level.
     From Town Hall 16 on the Town Hall's weapon gets all its levels (5 stars) before the next
     Town Hall.

Gems are never spent: only items priced in gold / elixir / dark elixir that you can afford, and
only the Confirm button that shows a resource price is pressed (see village._confirm).
"""

import logging
import re

from ..core import vision
from ..core.control import control
from ..core.space import space
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
# the Town Hall's weapon is listed under its own name (Giga Tesla, Giga Inferno, ...)
WEAPON_WORDS = ("giga", "weapon")
MENU = (430, 118, 860, 590)          # builder menu panel around its counter: half width, top, width, height


def _base(name):
    """'Elixir Collector x6' / 'ElixirCollectorx6' -> 'elixircollector'."""
    n = re.sub(r"[^a-z0-9]", "", name.lower())
    return re.sub(r"x\d+$", "", n)


PLAN_BASES = [(title, [_base(n) for n in names]) for title, names in PLAN]


def _is_weapon(row):
    low = row["name"].lower()
    return any(w in low for w in WEAPON_WORDS) and not any(t in low for t in ("bomb", "tower", "mine"))


def _panel(bot):
    cx = bot.layout.point("top.builders_menu")[0]
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
        name = re.sub(r"^New\s*", "", raw).strip()
        nbox = parts[0][1]
        rows.append({"name": name, "base": _base(name), "cost": p["cost"],
                     "res": village._icon_resource(frame, p["box"]), "red": village._is_red(frame, p["box"]),
                     "section": p["section"], "tap": (nbox[0] + min(nbox[2], space.s(160)) // 2, nbox[1] + nbox[3] // 2)})
    return rows, section


def _scroll(bot, region, cx):
    x, y, w, h = region
    bot.swipe((cx, y + h - space.s(60)), (cx, y + space.s(90)), 600)
    bot.sleep(0.8)


def scan(bot, max_pages=8):
    """Open the builder menu and read every upgradable item (scrolling through the list).
    Each row gets the page it is on. The menu is left open, scrolled to the end."""
    bot.tap_point("top.builders_menu")
    bot.sleep(1.0)
    region, cx = _panel(bot)
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


def choose(rows, have, th=0):
    """The upgrade to start (or None): the first group of the plan with an affordable item;
    the Town Hall (weapon first) only when no plan building is listed any more."""
    def affordable(r):
        return (r["res"] in ("gold", "elixir", "dark") and not r["red"] and have.get(r["res"]) is not None
                and have[r["res"]] >= r["cost"])

    listed = False
    for title, bases in PLAN_BASES:
        group = [r for r in rows if r["base"] in bases]
        listed = listed or bool(group)
        for base in bases:                            # the plan's own order inside a group
            ok = [r for r in group if r["base"] == base and affordable(r)]
            if ok:
                return dict(min(ok, key=lambda r: r["cost"]), group=title)
    if listed:
        return None                                   # plan buildings not maxed yet: no Town Hall
    weapon = [r for r in rows if _is_weapon(r)]
    if weapon:                                        # Town Hall 16+: all weapon levels first
        ok = [r for r in weapon if affordable(r)]
        return dict(ok[0], group="town hall weapon") if ok else None
    th_rows = [r for r in rows if r["base"] == _base(TOWN_HALL)]
    ok = [r for r in th_rows if affordable(r)]
    return dict(ok[0], group="town hall") if ok else None


def _open_row(bot, item):
    """Re-open the menu, scroll to the item's page and tap it. True if tapped."""
    village.close_menu(bot)
    go_home(bot, 15)
    bot.tap_point("top.builders_menu")
    bot.sleep(1.0)
    region, cx = _panel(bot)
    cols, section = [None, None], "progress"
    for page in range(item["page"] + 2):
        rows, section = _read_page(bot.shot(), region, cols, section)
        hit = next((r for r in rows if r["base"] == item["base"] and r["cost"] == item["cost"]), None)
        if hit:
            bot.tap(*hit["tap"], jitter=2)
            return True
        _scroll(bot, region, cx)
    return False


def run(bot, account, when="", max_count=None):
    """Use the free builders on the plan. Returns the number of upgrades started."""
    cfg = bot.settings.get("upgrades", {})
    if not cfg.get("enabled", True) or not account.get("upgrade"):
        return 0
    max_count = max_count if max_count is not None else cfg.get("max_per_visit", 5)
    started = 0
    while started < max_count:
        control.checkpoint()
        if not go_home(bot):
            break
        counter = village.read_counter(bot, "builders")
        if not counter or counter[0] <= 0:
            if started == 0:
                log.info("%s: no free builder%s", account["name"], f" ({counter[0]}/{counter[1]})" if counter else "")
            break
        have = loot.home_resources(bot)
        rows = scan(bot)
        item = choose(rows, have, account.get("th", 0))
        if not item:
            log.info("%s: nothing in the upgrade plan is affordable now (%d upgradable items listed)",
                     account["name"], len(rows))
            village.close_menu(bot)
            break
        log.info("%s%s: upgrading %s (%s) for %s %s", account["name"], f" {when}" if when else "", item["name"],
                 item["group"], f"{item['cost']:,}", item["res"])
        item["have"] = have.get(item["res"])
        if not _open_row(bot, item):
            log.info("%s: could not find %s in the menu again", account["name"], item["name"])
            village.close_menu(bot)
            break
        bot.sleep(1.2)
        up = bot.wait("building/upgrade_button", 4)
        if not up:
            log.info("%s: no Upgrade button", item["name"])
            village.close_menu(bot)
            break
        bot.tap_match(up)
        bot.sleep(1.2)
        ok = village._confirm(bot, item, "builders")
        village.close_menu(bot)
        if not ok:
            break
        started += 1
        bot.stats["upgrades"] = bot.stats.get("upgrades", 0) + 1
    go_home(bot)
    return started

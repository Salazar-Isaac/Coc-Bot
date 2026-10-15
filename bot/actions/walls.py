"""Wall upgrades: many walls at once, paid with gold and with elixir.

The Build panel (sorted "Cost Min") lists the walls per level, priced per wall and without a time
("Wall x 216 - 20,000": walls are upgraded at once and take no builder). Tapping that row selects a
wall of that level (the camera goes to it) and shows its buttons left of the panel. "Upgrade More"
turns them into Remove Wall (-1) / Add Wall (+10) / Add Wall (+1) / Upgrade (gold) / Upgrade (elixir),
the Upgrade buttons showing the total price of the walls selected. Then the game asks "Upgrade
Walls - Do you really want to upgrade the selected Walls for 40000 Gold?" - Okay.

So as many walls of the cheapest level as the gold allows (above the gold kept for searching bases)
go in one batch paid with gold, as many as the elixir allows in one paid with elixir; then the next
level, until neither pays for one more wall. Before Okay the total on the button and the amount in
the game's question are both checked against what may be spent. Gems are never involved.
"""

import logging
import re
import time

from ..core import vision
from ..core.control import control
from ..core.space import space
from ..states import go_home
from . import loot, panel, upgrades, village

log = logging.getLogger("bot")

MAIN = upgrades.MAIN
TITLE = (440, 745, 540, 55)            # "Wall (Level 4) x 11" over the wall's buttons (Build panel open)
DIALOG_LINE = (680, 494, 560, 44)      # "... Walls for 40000 Gold?" (2nd line of the question, centred)
RESOURCES = ("gold", "elixir")         # walls are never paid with dark elixir (or gems)
MAX_BATCHES = 12                       # per visit (one batch per level and resource)
TAP_GAP = 0.18                         # between two "Add Wall" taps (faster ones get lost)
REMOVE_LEFT = 314                      # "Remove Wall" (-1) is this far left of the "+1" wall


def cfg(bot):
    return bot.settings.get("steps", {}).get("walls") or {}


def budget(bot, have):
    """What may be spent on walls: the gold above what is kept for searching bases, the elixir above
    what is kept (0 by default)."""
    c = cfg(bot)
    keep = {"gold": int(c.get("keep_gold", upgrades.KEEP_GOLD) or 0), "elixir": int(c.get("keep_elixir", 0) or 0)}
    return {r: max(0, have[r] - keep[r]) if have.get(r) is not None else 0 for r in RESOURCES}


def _count(name):
    """'Wall x 216' -> 216 (walls of that level), None if not read."""
    m = re.search(r"x\s*(\d+)\s*$", name or "", re.I)
    return int(m.group(1)) if m else None


def _level(title):
    m = re.search(r"lev\w*\W*(\d+)", (title or "").lower())
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------------------- the panel row
def cheapest_row(bot, money, account, start_page=0):
    """The panel's cheapest wall row that one of the resources can pay (or None). Reads the list
    sorted cheapest first only as far as needed: names only for price-only rows (walls) within
    reach, and it stops at the first wall row, or once prices are past what can be spent."""
    top = max(money.values())
    red = set()

    def want(r):
        return r.get("timeless") and not r["red"] and r["cost"] and r["cost"] <= top

    def stop(rows):
        for r in rows:
            if r.get("base") == "wall" and r["cost"] and r["cost"] <= top:
                return True
            if r["cost"] and r["cost"] > top:
                return True                            # sorted: every later price is higher
            if r["red"] and r["res"] in RESOURCES:
                red.add(r["res"])
        return red >= set(RESOURCES)                   # later rows cost more than both resources have

    data = panel.scan(bot, MAIN, {}, need=(), account=account, stop_when=stop, start_page=start_page, want=want)
    walls = [r for r in data["rows"] if r.get("base") == "wall" and r["cost"] and r["cost"] <= top]
    return (min(walls, key=lambda r: r["cost"]) if walls else None), data


# ----------------------------------------------------------------------------- the wall buttons
def _prices(frame, key):
    """The Upgrade buttons of the selected walls: [(match, total price, resource)]."""
    out = []
    for m in vision.find_all(frame, key):
        x, y, w, h = m.box
        total = vision.digits.read(frame, (x - space.s(14), y - space.s(28), w + space.s(28), space.s(30)))
        out.append((m, total, _resource(frame, (x - space.s(14), y - space.s(28), w + space.s(28), space.s(28)))))
    return out


def _resource(frame, box):
    """Gold coin or elixir drop next to a price on a wall button (the button itself is beige)."""
    import cv2
    x, y, w, h = [int(v) for v in box]
    patch = frame[max(0, y):y + h, max(0, x):x + w]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    hue, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    gold = ((hue >= 18) & (hue <= 35) & (sat > 150) & (val > 170)).sum()
    elixir = ((hue >= 125) & (hue <= 170) & (sat > 80) & (val > 80)).sum()
    if max(gold, elixir) < 25:
        return None
    return "gold" if gold > elixir else "elixir"


def _total(bot, res, key="wall/upgrade"):
    for m, total, r in _prices(bot.shot(), key):
        if r == res:
            return m, total
    return None, None


def _okay(bot, res, total, money):
    """The game's "Upgrade Walls ... for 40000 Gold?" is open: Okay only if it names this resource and
    exactly this total, within what may be spent. True if the walls were paid."""
    if not bot.wait("wall/dialog_title", 4, interval=0.2):
        return False
    text, _ = vision.text_reader.read_line(bot.frame, space.region(*DIALOG_LINE))
    low = text.lower().replace(" ", "")
    m = re.search(r"for([\d,.]+)([a-z]+)", low)
    asked = int(re.sub(r"\D", "", m.group(1)) or 0) if m else None
    named = m and ("gold" if m.group(2).startswith("gol") else "elixir" if m.group(2).startswith("eli") else None)
    if not m or named != res or asked != total or asked > money:
        log.warning("Walls: the game asks '%s' - not what was chosen (%s %s): cancelled", text.strip(),
                    f"{total:,}" if total else "?", res)
        bot.tap_point("dialog.cancel")
        bot.sleep(0.6)
        return False
    bot.tap_point("dialog.okay")
    bot.sleep(1.2)
    if vision.find(bot.shot(), "wall/dialog_title"):
        bot.tap_point("dialog.cancel")                 # did not take: never leave it open
        bot.sleep(0.6)
        return False
    if not vision.find(bot.frame, "build/close"):      # something else popped up (never a gem offer: close it)
        bot.save_error("walls-after-okay")
        village._close_offer(bot)
        return False
    return True


def _single(bot, row, res, money):
    """Only one wall of that level selected and no Upgrade More: its own Upgrade button."""
    m, total = _total(bot, res, "wall/upgrade_one")
    if m is None or not total or total > money:
        return 0
    bot.tap_match(m, jitter=2)
    key, _ = bot.wait_any(["wall/dialog_title", "upgrade/confirm"], 4)
    if key == "wall/dialog_title":
        return 1 if _okay(bot, res, total, money) else 0
    if key == "upgrade/confirm":                        # an upgrade window: its priced Confirm, never gems
        c, price = village._priced_confirm(bot, bot.shot())
        if c is None or price != total or price > money:
            village._close_offer(bot)
            return 0
        bot.tap_match(c)
        bot.sleep(1.5)
        return 1 if not vision.find(bot.shot(), "upgrade/confirm") else 0
    return 0


def batch(bot, row, res, want, money):
    """Select `want` walls of the row's level and pay them with `res` (at most `money`). The panel
    must be open with the row's page on screen (or it is found again). Returns how many were upgraded."""
    if not panel.goto_row(bot, MAIN, row):
        log.info("Walls: the %s row is not in the list any more", row.get("name") or "wall")
        return 0
    if not bot.wait("wall/upgrade_more", 4, interval=0.2) and not bot.exists("wall/upgrade_one"):
        log.info("Walls: no wall buttons after tapping %s", row.get("name") or "the wall row")
        bot.save_error("walls-no-buttons")
        return 0
    bot.sleep(0.3)                                     # the buttons slide in: let the title settle
    title, _ = vision.text_reader.read_line(bot.shot(), space.region(*TITLE))
    if "wall" not in title.lower().replace(" ", ""):
        log.warning("Walls: '%s' was selected, not a wall: nothing done", title.strip())
        return 0
    level = _level(title)
    more = vision.find(bot.frame, "wall/upgrade_more")
    if more is None:
        return _single(bot, row, res, money)
    bot.tap_match(more, jitter=2)
    if not bot.wait("wall/add1", 3, interval=0.2):
        log.info("Walls: Upgrade More did not open")
        return 0
    f = bot.shot()
    add1 = vision.find(f, "wall/add1")
    add10 = vision.find(f, "wall/add10")
    m, per = _total(bot, res)
    if m is None or not per:
        log.info("Walls (level %s): no %s price to pay them with", level or "?", res)
        return 0
    if per != row["cost"]:
        log.info("Walls (level %s): %s each now (the list said %s)", level or "?", f"{per:,}", f"{row['cost']:,}")
    want = min(want, money // per)
    if want < 1:
        return 0
    tens, ones = divmod(want - 1, 10)
    if tens and add10 is not None:
        bot.tap(add10.x, add10.y, jitter=2, times=tens, interval=TAP_GAP)
    elif tens:
        ones += 10 * tens
    if ones:
        bot.tap(add1.x, add1.y, jitter=2, times=ones, interval=TAP_GAP)
    # check the count by the total on the button (taps can get lost; there may be fewer walls)
    remove = (add1.x - space.s(REMOVE_LEFT), add1.y)
    got, last = None, None
    for _ in range(4):
        bot.sleep(0.5)
        _, total = _total(bot, res)
        if not total:
            break
        got = total // per
        if got == want or got == last and got < want:
            break                                       # done - or no more walls of this level to add
        last = got
        if got < want:
            bot.tap(add1.x, add1.y, jitter=2, times=want - got, interval=TAP_GAP)
        else:
            bot.tap(*remove, jitter=2, times=got - want, interval=TAP_GAP)
    m, total = _total(bot, res)
    if m is None or not total or total > money or total % per:
        log.info("Walls (level %s): the total %s is not what was chosen - not upgrading", level or "?",
                 f"{total:,}" if total else "?")
        return 0
    got = total // per
    log.info("Walls (level %s): upgrading %d for %s %s (%s each)", level or "?", got, f"{total:,}", res, f"{per:,}")
    bot.tap_match(m, jitter=2)
    return got if _okay(bot, res, total, money) else 0


# ----------------------------------------------------------------------------- one visit
def run(bot, account, max_batches=MAX_BATCHES):
    """Put the account's gold and elixir (above what is kept) into walls, the cheapest level first,
    many walls per batch. Returns the number of walls upgraded."""
    if not go_home(bot):
        return 0
    if upgrades.refuse(bot, account, "wall upgrades"):
        return 0
    have = loot.home_resources(bot)
    money = budget(bot, have)
    if have.get("gold") is None and have.get("elixir") is None:
        log.info("%s: could not read the resources - no walls", account["name"])
        return 0
    t0 = time.monotonic()
    done, spent, failed, page = 0, {r: 0 for r in RESOURCES}, set(), 0
    for _ in range(max_batches):
        control.checkpoint()
        if max(money.values()) <= 0:
            break
        row, data = cheapest_row(bot, money, account, start_page=page)
        if row is None and page:
            row, data = cheapest_row(bot, money, account)      # not where it was: from the top
        if row is None:
            if not done:
                log.info("%s: no wall the account can pay (gold %s, elixir %s to spend)", account["name"],
                         f"{money['gold']:,}", f"{money['elixir']:,}")
            break
        page = max(0, row.get("page", 0) - 1)
        per = row["cost"]
        payers = sorted((r for r in RESOURCES if money[r] >= per and (per, r) not in failed),
                        key=lambda r: -money[r])          # the fuller one first: both get used
        if not payers:
            break
        res = payers[0]
        left = _count(row.get("name")) or 10_000
        n = batch(bot, row, res, min(left, money[res] // per), money[res])
        if n:
            done += n
            money[res] -= n * per
            spent[res] += n * per
            bot.stats["walls"] = bot.stats.get("walls", 0) + n
        else:
            failed.add((per, res))                     # not twice the same way this visit
            village.close_menu(bot, MAIN["safe"])
            go_home(bot, 15)
    village.close_menu(bot, MAIN["safe"])
    go_home(bot)
    if done:
        after = loot.home_resources(bot)
        log.info("%s: %d walls upgraded in %.0f s (%s) - gold %s, elixir %s left", account["name"], done,
                 time.monotonic() - t0, ", ".join(f"{v:,} {r}" for r, v in spent.items() if v),
                 f"{after['gold']:,}" if after.get("gold") is not None else "?",
                 f"{after['elixir']:,}" if after.get("elixir") is not None else "?")
    return done

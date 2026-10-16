"""Wall upgrades: many walls at once, paid with gold and with elixir - only while a builder is free.

The Build panel (sorted "Cost Min") lists the walls per level, priced per wall and without a time
("Wall x 216 - 20,000"). Tapping that row selects a wall of that level (the camera goes to it) and
shows its buttons under it: Info / Select Row / Upgrade More / Upgrade (gold) / Upgrade (elixir).
"Upgrade More" turns them into Remove Wall (-1) / Add Wall (+10) / Add Wall (+1) / Upgrade / Upgrade -
the same five places - and the Upgrade buttons then show the total price of the walls selected. The
game asks "Upgrade Walls - Do you really want to upgrade the selected Walls for 40000 Gold?" - Okay.

The buttons are see-through (the village shows through them), so they are found by their LABELS,
read once per visit ("Upgrade More", "Upgrade"); their prices with the game-font digit reader.

So as many walls of the cheapest level as the gold allows (above the gold kept for searching bases)
go in one batch paid with gold, as many as the elixir allows in one paid with elixir (the fuller one
first); then the next level, until neither pays for one more wall. Before Okay the total on the button
and the amount in the game's question are both checked against what may be spent. Gems never.
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
LABELS = (250, 860, 1150, 90)          # where the labels of a selected wall's buttons are (either bar size)
DIALOG_LINE = (680, 494, 560, 44)      # "... Walls for 40000 Gold?" (2nd line of the question, centred)
RESOURCES = ("gold", "elixir")         # walls are never paid with dark elixir (or gems)
MAX_BATCHES = 12                       # per visit (one batch per level and resource)
TAP_GAP = 0.18                         # between two "Add Wall" taps (faster ones get lost)


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


DIGIT_LIKE = str.maketrans("silo|zbg", "51101269")     # what the text reader makes of game-font digits


def _level(title):
    """'Wall (Level 16)' -> 16 (also from 'LeveI s' = 5, 'Leveli6' = 16)."""
    m = re.search(r"leve[l1i|]\W*([0-9silo|zbg]{1,2})", (title or "").lower())
    return int(m.group(1).translate(DIGIT_LIKE)) if m else None


def _multi(title):
    """True once Upgrade More took: 'Wall (Level 5)x 1' (read as 'x 1', "x'l", 'x l' ...)."""
    low = (title or "").lower()
    m = re.search(r"leve[l1i|]\W*[0-9silo|zbg]{1,2}", low)
    return bool(re.search(r"[x×]\s*\W?\s*[0-9li|]", low[m.end():] if m else low))


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
def read_bar(frame):
    """The selected wall's buttons, found by their labels: {"slots": [x of the 5 places], "y": tap y,
    "label_y", "more": x of Upgrade More or None, "ups": [x of the Upgrade buttons]} - or None."""
    region = space.region(*LABELS)
    found = []
    for b in panel._detect(frame, region):
        text = panel._line(frame, b).strip().lower()
        if len(re.sub(r"[^a-z]", "", text)) >= 2:          # (the +10 / +1 / hammer icons are no labels)
            found.append((b[0] + b[2] // 2, b[1], text))
    buttons = []
    for cx, y, text in sorted(found):
        if buttons and abs(buttons[-1]["x"] - cx) < space.s(45):
            buttons[-1]["text"] += " " + text                  # a two-line label ("Upgrade / More")
            buttons[-1]["y"] = min(buttons[-1]["y"], y)
        else:
            buttons.append({"x": cx, "y": y, "text": text})
    if len(buttons) < 3:
        return None
    more = next((b["x"] for b in buttons if "more" in b["text"]), None)
    up = [b for b in buttons if ("upgr" in b["text"] or "grade" in b["text"]) and "more" not in b["text"]]
    ups, up_y = [b["x"] for b in up], {b["x"]: b["y"] for b in up}
    label_y = min(b["y"] for b in buttons)
    return {"slots": [b["x"] for b in buttons], "texts": [b["text"] for b in buttons], "label_y": label_y,
            "y": label_y - space.s(24), "more": more, "ups": ups, "up_y": up_y,
            "title": (int(sum(b["x"] for b in buttons) / len(buttons)) - space.s(250), label_y - space.s(142),
                      space.s(500), space.s(50))}


def _title(bot, bar):
    text, _ = vision.text_reader.read_line(bot.shot(), bar["title"])
    return text.strip()


def _price(frame, bar, x):
    """The total on an Upgrade button (its price is above the hammer, 66 px over its label) and its resource."""
    box = (x - space.s(65), bar["up_y"].get(x, bar["label_y"]) - space.s(84), space.s(130), space.s(36))
    return vision.digits.read(frame, box), _resource(frame, box)


def _resource(frame, box):
    """Gold coin or elixir drop next to a price on a wall button."""
    import cv2
    x, y, w, h = [int(v) for v in box]
    patch = frame[max(0, y):y + h, max(0, x):x + w]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    hue, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    gold = ((hue >= 18) & (hue <= 35) & (sat > 150) & (val > 170)).sum()
    elixir = ((hue >= 125) & (hue <= 170) & (sat > 80) & (val > 80)).sum()
    if max(gold, elixir) < 25 or min(gold, elixir) > max(gold, elixir) * 0.6:
        return None                                       # unclear (the village shows through)
    return "gold" if gold > elixir else "elixir"


def _upgrade_buttons(frame, bar):
    """{resource: x} of the Upgrade buttons: with two, gold is the left one and elixir the right one."""
    ups = sorted(bar["ups"])
    if len(ups) >= 2:
        return {"gold": ups[0], "elixir": ups[1]}
    out = {}
    for x in ups:
        res = _price(frame, bar, x)[1]
        if res:
            out[res] = x
    return out


def _okay(bot, res, total, money):
    """The game's "Upgrade Walls ... for 40000 Gold?" is open: Okay only if it names this resource and
    exactly this total, within what may be spent. True if the walls were paid."""
    if not bot.wait("wall/dialog_title", 4, interval=0.2):
        log.info("Walls: the 'Upgrade Walls' question did not come")
        bot.save_error("walls-no-question")
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
        log.info("Walls: something else came up after Okay (kept as walls-after-okay)")
        bot.save_error("walls-after-okay")
        village._close_offer(bot)
        return False
    return True


def batch(bot, row, res, want, money, bars):
    """Select `want` walls of the row's level and pay them with `res` (at most `money`). The panel
    must be open with the row's page on screen (or it is found again). bars: the button places read
    this visit (filled on the first batch). Returns how many were upgraded."""
    if not panel.goto_row(bot, MAIN, row):
        log.info("Walls: the %s row is not in the list any more", row.get("name") or "wall")
        return 0
    bot.sleep(1.2)                                     # the camera moves to the wall, the buttons slide in
    bar = bars.get("normal")
    title = _title(bot, bar) if bar else ""
    if "wall" not in title.lower().replace(" ", ""):
        bar = None
        for _ in range(2):                             # read the buttons by their labels
            bar = read_bar(bot.shot())
            if bar and bar["more"]:
                break
            bot.sleep(0.8)
        if not bar or not bar["more"] or len(bar["slots"]) < 4:
            log.info("Walls: no 'Upgrade More' under the selected wall (labels read: %s)",
                     ", ".join(bar["texts"]) if bar else "none")
            bot.save_error("walls-no-buttons")
            return 0
        bars["normal"] = bar
        title = _title(bot, bar)
        log.debug("Wall buttons at %s (labels: %s), title '%s'", bar["slots"], ", ".join(bar["texts"]), title)
    if "wall" not in title.lower().replace(" ", ""):
        log.warning("Walls: '%s' was selected, not a wall: nothing done", title)
        bot.save_error("walls-not-a-wall")
        return 0
    level = _level(title)
    bot.tap(bar["more"], bar["y"], jitter=2)          # Upgrade More: the same 5 places get new buttons
    end = time.monotonic() + 3
    while time.monotonic() < end:                     # "Wall (Level 4) x 1" once it took
        bot.sleep(0.4)
        if _multi(_title(bot, bar)):
            break
    else:
        log.info("Walls (level %s): Upgrade More did not take", level or "?")
        bot.save_error("walls-no-multi")
        return 0
    slots = sorted(bar["slots"])
    i = slots.index(bar["more"])
    add1, add10 = bar["more"], slots[i - 1] if i >= 1 else None   # +10 where Select Row was, +1 where
    remove = slots[i - 2] if i >= 2 else None                     # Upgrade More was, Remove where Info was
    ups = _upgrade_buttons(bot.shot(), bar)
    if res not in ups:
        log.info("Walls (level %s): no Upgrade button priced in %s", level or "?", res)
        return 0
    x = ups[res]
    per, seen = _price(bot.frame, bar, x)
    if not per:
        log.info("Walls (level %s): the price on the %s button could not be read", level or "?", res)
        bot.save_error("walls-no-price")
        return 0
    if seen and seen != res:
        log.info("Walls (level %s): the %s button looks like %s - not upgrading", level or "?", res, seen)
        return 0
    if per != row["cost"]:
        log.info("Walls (level %s): %s each now (the list said %s)", level or "?", f"{per:,}", f"{row['cost']:,}")
    want = min(want, money // per)
    if want < 1:
        return 0
    tens, ones = divmod(want - 1, 10)
    if tens and add10 is not None:
        bot.tap(add10, bar["y"], jitter=2, times=tens, interval=TAP_GAP)
    elif tens:
        ones += 10 * tens
    if ones:
        bot.tap(add1, bar["y"], jitter=2, times=ones, interval=TAP_GAP)
    # check the count by the total on the button (taps can get lost; there may be fewer walls)
    got, last = None, None
    for _ in range(4):
        bot.sleep(0.5)
        total = _price(bot.shot(), bar, x)[0]
        if not total:
            break
        got = total // per
        if got == want or got == last and got < want:
            break                                       # done - or no more walls of this level to add
        last = got
        if got < want:
            bot.tap(add1, bar["y"], jitter=2, times=want - got, interval=TAP_GAP)
        elif remove is not None:
            bot.tap(remove, bar["y"], jitter=2, times=got - want, interval=TAP_GAP)
    total = _price(bot.shot(), bar, x)[0]
    if not total or total > money or total % per:
        log.info("Walls (level %s): the total %s is not what was chosen - not upgrading", level or "?",
                 f"{total:,}" if total else "?")
        bot.save_error("walls-total")
        return 0
    got = total // per
    log.info("Walls (level %s): upgrading %d for %s %s (%s each)", level or "?", got, f"{total:,}", res, f"{per:,}")
    bot.tap(x, bar["y"], jitter=2)
    return got if _okay(bot, res, total, money) else 0


# ----------------------------------------------------------------------------- one visit
def free_builder(bot, account):
    """Walls only while a builder is free: the builder counter (free / all) on the village."""
    counter = village.read_counter(bot, "builders")
    if not counter:
        bot.sleep(1.0)
        counter = village.read_counter(bot, "builders")
    if not counter:
        log.info("%s: the builders could not be read - no walls now", account["name"])
        return False
    if counter[0] <= 0:
        log.info("%s: no free builder (%d/%d) - no walls now", account["name"], *counter)
        return False
    return True


def run(bot, account, max_batches=MAX_BATCHES):
    """Put the account's gold and elixir (above what is kept) into walls, the cheapest level first,
    many walls per batch - only while a builder is free. Returns the number of walls upgraded."""
    if not go_home(bot):
        return 0
    if upgrades.refuse(bot, account, "wall upgrades"):
        return 0
    if not free_builder(bot, account):
        return 0
    have = loot.home_resources(bot)
    money = budget(bot, have)
    if have.get("gold") is None and have.get("elixir") is None:
        log.info("%s: could not read the resources - no walls", account["name"])
        return 0
    log.info("%s: walls with up to %s gold and %s elixir (has %s gold, %s elixir)", account["name"],
             f"{money['gold']:,}", f"{money['elixir']:,}", f"{have.get('gold') or 0:,}", f"{have.get('elixir') or 0:,}")
    t0 = time.monotonic()
    pages = (bot.state if bot.state is not None else {}).setdefault("wall_page", {})
    page = max(0, int(pages.get(account["name"], 0)) - 1)   # where the walls were on the list last time
    done, spent, failed, bars = 0, {r: 0 for r in RESOURCES}, set(), {}
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
        pages[account["name"]] = row.get("page", 0)
        page = max(0, row.get("page", 0) - 1)
        per = row["cost"]
        payers = sorted((r for r in RESOURCES if money[r] >= per and (per, r) not in failed),
                        key=lambda r: -money[r])          # the fuller one first: both get used
        if not payers:
            break
        res = payers[0]
        left = _count(row.get("name")) or 10_000
        n = batch(bot, row, res, min(left, money[res] // per), money[res], bars)
        if n:
            done += n
            money[res] -= n * per
            spent[res] += n * per
            bot.stats["walls"] = bot.stats.get("walls", 0) + n
        else:
            failed.add((per, res))                     # not twice the same way this visit
            bars.clear()                               # read the buttons afresh next time
            village.close_menu(bot, MAIN["safe"])
            go_home(bot, 15)
    village.close_menu(bot, MAIN["safe"])
    go_home(bot)
    if bot.state is not None:
        from .. import config
        config.save_state(bot.state)
    after = loot.home_resources(bot)
    log.info("%s: %d wall(s) upgraded in %.0f s%s - gold %s, elixir %s left", account["name"], done,
             time.monotonic() - t0, f" ({', '.join(f'{v:,} {r}' for r, v in spent.items() if v)})" if done else "",
             f"{after['gold']:,}" if after.get("gold") is not None else "?",
             f"{after['elixir']:,}" if after.get("elixir") is not None else "?")
    return done

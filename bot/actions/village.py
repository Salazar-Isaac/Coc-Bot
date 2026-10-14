"""Main village helpers for upgrades: the builder counter, the builder menu (names, prices,
which resource, affordable or not) and confirming an upgrade without ever spending gems.
The order of upgrades is in upgrades.py; the Builder Base uses the same helpers."""

import logging
import re

import cv2
import numpy as np

from ..core import vision
from ..core.space import space
from ..states import go_home
from . import loot

log = logging.getLogger("bot")

# --- top counters and menus ------------------------------------------------------------------

def _fraction(text):
    m = re.search(r"(\d+)\s*[/|lI1]\s*(\d+)\s*$", text.replace(" ", ""))
    if m:
        return int(m.group(1)), int(m.group(2))
    digits = re.sub(r"\D", "", text)
    if len(digits) == 2:                                  # slash not read
        return int(digits[0]), int(digits[1])
    return None


def read_counter(bot, which):
    """(free, total) builders or labs from the counters at the top of the village."""
    frame, region = bot.shot(), bot.layout.region(f"top.{which}")
    f = vision.digits.read_fraction(frame, region)
    if f:
        return f
    text, _ = vision.text_reader.read_line(frame, region)
    return _fraction(text)


def _icon_resource(frame, box):
    """Which resource icon is just left of a cost: gold / elixir / dark."""
    x, y, w, h = box
    patch = frame[max(0, y - 2):y + h + 2, max(0, x - space.s(30)):x]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    bright = hsv[(hsv[:, 1] > 90) & (hsv[:, 2] > 120)]
    if len(bright) < 15:
        return "dark"
    hue = float(np.median(bright[:, 0]))
    if 15 <= hue <= 35:
        return "gold"
    if 125 <= hue <= 170:
        return "elixir"
    if 40 <= hue <= 95:
        return "gems"                         # green gem price: never paid by the bot
    return "dark"


def _is_red(frame, box):
    """Costs you cannot pay are drawn in red."""
    x, y, w, h = box
    px = frame[y:y + h, x:x + w].reshape(-1, 3).astype(int)
    if len(px) == 0:
        return False
    b, g, r = px[:, 0], px[:, 1], px[:, 2]
    red = ((r > 170) & (g < 110) & (b < 110)).sum()
    white = ((r > 200) & (g > 200) & (b > 200)).sum()
    return red > max(12, white)


def read_menu(bot, which):
    """Open the builder/lab menu and return its rows:
    [{"name", "cost", "res", "red", "section", "tap"}] for items with a cost."""
    bot.tap_point(f"top.{which}_menu")
    bot.sleep(1.0)
    frame = bot.shot()
    cx = bot.layout.point(f"top.{which}_menu")[0]
    rows = parse_menu(frame, cx)
    return rows


def parse_menu(frame, cx):
    """Rows of an open builder/lab menu whose counter is at x=cx (see read_menu)."""
    region = (max(0, cx - space.s(430)), space.point(0, 118)[1], space.s(860), space.s(590))
    lines = sorted(vision.text_reader.read(frame, region), key=lambda t: (t[2][1], t[2][0]))
    # the panel is see-through: only trust text in its name column (starts at the section
    # headers' x) and its cost column (right-aligned like the other costs)
    headers = [b for t, c, b in lines if t.lower().replace(" ", "").rstrip(":").endswith(("progress", "upgrades"))]
    if not headers:
        return []
    left = min(b[0] for b in headers)
    costs = [(t, b) for t, c, b in lines if len(re.sub(r"\D", "", t)) >= 4 and not re.search(r"[A-Za-z]{3,}", t)]
    if not costs:
        return []
    right = max(b[0] + b[2] for _, b in costs if b[0] > left + 150) if any(b[0] > left + 150 for _, b in costs) else 0
    section, names, rows = None, [], []
    for text, conf, box in lines:
        low = text.lower().replace(" ", "")
        x, y, w, h = box
        if abs(x - left) < 25 and low.rstrip(":").endswith(("progress", "upgrades")):
            section = "progress" if "progress" in low else ("suggested" if "suggested" in low else "other")
            continue
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 4 and not re.search(r"[A-Za-z]{3,}", text) and abs(x + w - right) < 40:
            # prefer the game-font digit reader for the price; OCR drops leading digits on some rows
            exact = vision.digits.read(frame, (x - 4, y - 2, w + 8, h + 4))
            cost = exact if exact and len(str(exact)) >= len(digits) else int(digits)
            if cost >= 100:
                rows.append({"cost": cost, "box": box, "section": section})
        elif conf > 0.5 and section in ("suggested", "other") and left - 10 <= x < right - 120:
            names.append((text, box, conf))
    out = []
    for r in rows:
        if r["section"] not in ("suggested", "other"):
            continue
        cy = r["box"][1] + r["box"][3] / 2
        parts = sorted((n for n in names if abs(n[1][1] + n[1][3] / 2 - cy) < 16 and n[1][0] < r["box"][0]),
                       key=lambda n: n[1][0])
        if not parts or r["box"][1] + r["box"][3] > region[1] + region[3] - 30:
            continue                                 # no name, or the row is cut off at the bottom
        if min(c for _, _, c in parts) < 0.8:
            continue                                 # unsure what it is: never upgrade a guess
        raw_name = " ".join(t for t, _, _ in parts)
        is_new = bool(re.match(r"^\s*New", raw_name))
        name = re.sub(r"^New\s*", "", raw_name).strip()
        if not name:
            continue
        nbox = parts[0][1]
        out.append({"name": name, "new": is_new, "cost": r["cost"], "res": _icon_resource(frame, r["box"]),
                    "red": _is_red(frame, r["box"]), "section": r["section"],
                    "tap": (nbox[0] + min(nbox[2], 160) // 2, nbox[1] + nbox[3] // 2)})
    return out


def close_menu(bot, point="home.safe"):
    """Close the builder / laboratory side panel (its X) - or tap an empty spot when it is not open
    (the panel covers the right side: a tap there would hit one of its rows)."""
    from ..states import dismiss_tutorial
    for _ in range(3):
        if not bot.exists("build/close"):
            break
        if dismiss_tutorial(bot):
            continue
        bot.tap_point("build.close")
        bot.sleep(0.6)
    bot.sleep(0.3)
    # (no tap on an "empty" spot when the panel is closed: on some villages that spot is a wall,
    # and a selected building does not get in the way of anything the bot does next)


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _skipped(name, skip):
    n = _norm(name)
    return any(_norm(s) and _norm(s) in n for s in skip)


# --- confirming an upgrade / research ----------------------------------------------------------

TIME_BOX = (1500, 930, 260, 80)      # "Upgrade time 9d" (under its title) at the bottom right of the window


def upgrade_time(frame):
    """Seconds an upgrade / research takes, read from its window (None if unreadable)."""
    from . import panel, timers
    for b in panel._detect(frame, space.region(*TIME_BOX)):
        text, _ = vision.text_reader.read_line(frame, (b[0] - 8, b[1] - 6, b[2] + 16, b[3] + 12))
        secs = timers.parse_time(text)
        if secs:
            return secs
    return None


BUSY_POPUP = (900, 260, 730, 330)    # "Hey Chief! ... all your Builders are busy" (Goblin Builder for gems)


def builders_busy(frame):
    """The game's "all your Builders are busy - the Goblin Builder can do it for gems" offer: the
    builder counter still counts the Goblin Builder as free, but he only works for gems."""
    text = "".join(t for t, _, _ in vision.text_reader.read(frame, space.region(*BUSY_POPUP)))
    low = re.sub(r"[^a-z]", "", text.lower())
    return "buildersarebusy" in low or "goblinbuilder" in low


def _close_offer(bot):
    """Close any 'buy with gems' or leftover window without accepting it."""
    for key in ("upgrade/close", "lab/close", "popup/close_x"):
        m = bot.find(key)
        if m:
            bot.tap_match(m, jitter=1)
            bot.sleep(0.6)
            return True
    return False


def _priced_confirm(bot, frame):
    """The Confirm button that has a resource price under it (never the one that spends a
    magic item such as a Hammer, which has no price). Returns (match, price) or (None, None)."""
    bottom = space.region(0, 820, 1920, 220)
    for m in vision.find_all(frame, "upgrade/confirm", region=bottom):
        x, y, w, h = m.box
        price = vision.digits.read(frame, (x - 70, y + h + 4, w + 140, 50))
        if not price:   # on sale: the new price is bright green, the old one crossed out below it
            price = vision.digits.read(frame, (x - 70, y + h + 2, w + 140, 40), color="sale")
        if price:
            return m, price
    return None, None


def _confirm(bot, item, which, home=None):
    """The upgrade/research window is open: check its price, then press the resource Confirm."""
    if not bot.wait("upgrade/confirm", 5):
        log.info("%s: no Confirm button (maybe needs gems or is locked)", item["name"])
        _close_offer(bot)
        return False
    m, cost = _priced_confirm(bot, bot.shot())
    if not m:
        log.info("%s: could not read the price; not confirming", item["name"])
        _close_offer(bot)
        return False
    have = item.get("have")
    if have is not None and cost > have:
        log.info("%s costs %s %s but you have %s: not upgrading", item["name"], f"{cost:,}", item["res"],
                 f"{have:,}")
        _close_offer(bot)
        return False
    item["duration"] = upgrade_time(bot.frame)
    bot.tap_match(m)
    bot.sleep(1.5)
    tapped = bot.shot()                           # what the game showed after Confirm (kept if refused)
    (home or go_home)(bot, 10)
    if home is not None:                          # Builder Base: read its own resource bar
        from . import builder_base
        after = builder_base.status(bot).get(item["res"])
    else:
        after = loot.home_resources(bot).get(item["res"])
    paid = after is None or have is None or after < have
    if not paid and item.get("free_before") is not None:
        # the amount can be misread: a builder that went to work also means it started
        region = bot.layout.region("bb.builders" if home is not None else "top.builders")
        now = vision.digits.read_fraction(bot.shot(), region)
        paid = bool(now) and now[0] < item["free_before"]
    if bot.exists("upgrade/confirm") or not paid:
        # still open, or nothing was paid: a gem offer or an error popup -> back out
        _close_offer(bot)
        (home or go_home)(bot, 30)
        if which == "builders" and builders_busy(tapped):
            item["builders_busy"] = True
            log.info("%s: all builders are busy (the free one is the Goblin Builder, who wants gems)", item["name"])
            return False
        log.info("%s: the game did not accept the upgrade", item["name"])
        bot.save_error("upgrade-refused", tapped)
        return False
    log.info("%s %s started for %s %s", "Research" if which == "lab" else "Upgrade", item["name"],
             f"{cost:,}", item["res"])
    return True

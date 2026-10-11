"""Village chores: collect resources, upgrade buildings, start research.

Upgrades use the game's own menus at the top of the village:
  * the builder counter ("1/5") opens a list of upgrades in progress, suggested
    upgrades and other upgrades, each with its cost;
  * the laboratory counter ("1/1") opens the same kind of list for research.
The bot reads that list with OCR, picks the first affordable item that is not
on the skip list (and leaves the reserve you set untouched), taps it, presses
Upgrade / Research and Confirm. It never taps anything that costs gems
(Boost, Finish Now) and closes any "buy with gems" offer.
"""

import logging
import re

import cv2
import numpy as np

from .. import config
from ..core import vision
from ..core.context import BotError
from ..core.control import control
from ..core.space import space
from ..states import detect, go_home
from . import loot

log = logging.getLogger("bot")

BUBBLES = {"gold": "village/bubble_gold", "elixir": "village/bubble_elixir", "dark": "village/bubble_dark"}


# --- collecting ----------------------------------------------------------------------------

def collect(bot):
    """Tap one full-collector bubble per resource (one tap collects all of that kind) and the
    loot cart. Returns {resource: amount gained}."""
    if not go_home(bot):
        raise BotError("Not on the home village")
    before = loot.home_resources(bot)
    full = (0, 0, *bot.shot().shape[1::-1])
    tapped = []
    for res, key in BUBBLES.items():
        if not vision.templates.has(key):
            continue
        ms = vision.find_all(bot.shot(), key, region=full)
        if ms:
            bot.tap_match(ms[0], jitter=2)
            tapped.append(res)
            bot.sleep(0.8)
    if vision.templates.has("village/loot_cart_label"):
        m = vision.find(bot.shot(), "village/loot_cart_label", region=full)
        if m:
            bot.tap(m.x + 10, m.y + 45, jitter=3)          # the cart sits under its label
            if bot.tap_template("village/collect_button", timeout=3, after=1.0):
                tapped.append("loot cart")
            bot.tap_point("home.safe", jitter=5)
            bot.sleep(0.5)
    after = loot.home_resources(bot)
    gained = {r: (after.get(r) or 0) - (before.get(r) or 0) for r in config.RESOURCES
              if after.get(r) is not None and before.get(r) is not None}
    if tapped:
        log.info("Collected (%s): %s", ", ".join(tapped),
                 ", ".join(f"+{v:,} {r}" for r, v in gained.items() if v > 0) or "storages full")
    return gained


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
    patch = frame[max(0, y - 2):y + h + 2, max(0, x - 30):x]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    bright = hsv[(hsv[:, 1] > 90) & (hsv[:, 2] > 120)]
    if len(bright) < 15:
        return "dark"
    hue = float(np.median(bright[:, 0]))
    if 15 <= hue <= 35:
        return "gold"
    if 130 <= hue <= 170:
        return "elixir"
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
    region = (max(0, cx - 430), space.point(0, 118)[1], 860, 590)
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
            rows.append({"cost": int(digits), "box": box, "section": section})
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
        name = re.sub(r"^New\s*", "", " ".join(t for t, _, _ in parts)).strip()
        if not name:
            continue
        nbox = parts[0][1]
        out.append({"name": name, "cost": r["cost"], "res": _icon_resource(frame, r["box"]),
                    "red": _is_red(frame, r["box"]), "section": r["section"],
                    "tap": (nbox[0] + min(nbox[2], 160) // 2, nbox[1] + nbox[3] // 2)})
    return out


def close_menu(bot):
    bot.tap_point("home.safe", jitter=5)
    bot.sleep(0.5)


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _skipped(name, skip):
    n = _norm(name)
    return any(_norm(s) and _norm(s) in n for s in skip)


def _pick(bot, rows, which):
    """First affordable item (suggested before other) that leaves the reserve."""
    v = bot.settings.get("village", {})
    skip = v.get("upgrade_skip" if which == "builders" else "research_skip", [])
    reserve = v.get("reserve", {})
    res_now = loot.home_resources(bot)
    order = sorted(rows, key=lambda r: r["section"] != "suggested")   # keeps the game's own order
    if not v.get("include_other", True):
        order = [r for r in order if r["section"] == "suggested"]
    for r in order:
        have = res_now.get(r["res"])
        if r["red"] or have is None:
            continue
        if _skipped(r["name"], skip):
            log.debug("Skip %s (on the skip list)", r["name"])
            continue
        if have - r["cost"] < reserve.get(r["res"], 0):
            log.debug("Skip %s: would go below the %s reserve", r["name"], r["res"])
            continue
        return dict(r, have=have)      # amount read before any window covers the resource bar
    return None


# --- confirming an upgrade / research ----------------------------------------------------------

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


def _confirm(bot, item, which):
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
    bot.tap_match(m)
    bot.sleep(1.5)
    go_home(bot, 10)
    after = loot.home_resources(bot).get(item["res"])
    if bot.exists("upgrade/confirm") or (after is not None and have is not None and after >= have):
        # still open, or nothing was paid: a gem offer or an error popup -> back out
        _close_offer(bot)
        go_home(bot)
        log.info("%s: the game did not accept the upgrade", item["name"])
        return False
    log.info("%s %s started for %s %s", "Research" if which == "lab" else "Upgrade", item["name"],
             f"{cost:,}", item["res"])
    return True


def upgrade_buildings(bot, max_count=None):
    """Use free builders on affordable upgrades. Returns the number started."""
    v = bot.settings.get("village", {})
    max_count = max_count if max_count is not None else v.get("max_upgrades", 2)
    started = 0
    for _ in range(max_count):
        control.checkpoint()
        if not go_home(bot):
            break
        counter = read_counter(bot, "builders")
        if not counter or counter[0] <= 0:
            log.info("No free builder%s", f" ({counter[0]}/{counter[1]})" if counter else "")
            break
        rows = read_menu(bot, "builders")
        item = _pick(bot, rows, "builders")
        if not item:
            log.info("No affordable building upgrade (%d listed)", len(rows))
            close_menu(bot)
            break
        bot.tap(*item["tap"], jitter=2)
        bot.sleep(1.2)
        up = bot.wait("building/upgrade_button", 4)
        if not up:
            log.info("%s: no Upgrade button", item["name"])
            close_menu(bot)
            break
        bot.tap_match(up)
        bot.sleep(1.2)
        ok = _confirm(bot, item, "builders")
        close_menu(bot)
        if not ok:
            break
        started += 1
    go_home(bot)
    return started


def research(bot):
    """Start one research if the laboratory is free. Returns True if started."""
    if not go_home(bot):
        return False
    counter = read_counter(bot, "lab")
    if not counter or counter[0] <= 0:
        log.info("Laboratory busy")
        return False
    rows = read_menu(bot, "lab")
    item = _pick(bot, rows, "lab")
    if not item:
        log.info("No affordable research (%d listed)", len(rows))
        close_menu(bot)
        return False
    bot.tap(*item["tap"], jitter=2)          # opens the research window directly
    bot.sleep(1.5)
    ok = _confirm(bot, item, "lab")
    _close_offer(bot)
    go_home(bot)
    return ok


def chores(bot, account, phase="arrive"):
    """Run the village chores enabled in Settings. phase: 'arrive' (collect) or 'leave' (spend)."""
    v = bot.settings.get("village", {})
    if detect(bot.shot()) != "home" and not go_home(bot):
        return
    try:
        if phase == "arrive" and v.get("collect", True):
            collect(bot)
        if phase == "leave":
            if v.get("upgrade_buildings", False):
                n = upgrade_buildings(bot)
                if n:
                    bot.stats.setdefault("upgrades", 0)
                    bot.stats["upgrades"] += n
            if v.get("research", False) and research(bot):
                bot.stats.setdefault("research", 0)
                bot.stats["research"] += 1
    except BotError as e:
        log.warning("Village chores on %s: %s", account.get("name", "?"), e)
        go_home(bot)


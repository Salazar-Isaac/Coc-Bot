"""The Build side panel (2026-10 UI), read fast.

The panel lists builder upgrades (or laboratory research) with their prices. Reading every row
with text recognition took ~7 s a page (14 pages = 2 minutes). Here:
  * the list is sorted "Cost Min" (the panel's own filter), so it can stop at the first price the
    account cannot pay - the game draws those red - for every resource that matters;
  * a page is read by finding the text boxes first (~1.4 s) and recognising only what is needed:
    a row's name only when its price is affordable, its price with the game-font digit reader;
  * the upgrades in progress (rows with a time but no price) give the time the next builder is free.
"""

import logging
import re
import time

from ..core import vision
from ..core.control import control
from ..core.space import space
from . import timers

log = logging.getLogger("bot")

PANEL = (1410, 70, 505, 890)          # the list part of the side panel (above its tabs)
NAME_X = (1475, 1530)                 # names start here (after the picture)
PRICE_RIGHT = 1880                    # prices and times end here (their icon is right of them)
POPUP = (600, 80, 920, 650)           # where the filter popup opens (left of the panel's filter button)
RESOURCES = ("gold", "elixir", "dark")
STEP = 600                            # one page: the list moves exactly as far as the swipe (measured);
#                                       the panel shows 890 px, so every row is whole on some page


# ----------------------------------------------------------------------------- open / sort
def open_menu(bot, where):
    """Open the side panel on this menu's tab, scrolled to the top. True if it is open."""
    if bot.exists("build/close"):
        bot.tap_point("build.close")
        bot.sleep(0.6)
    bot.tap_point(where["menu"])
    if not bot.wait("build/close", 4, interval=0.2):
        return False
    bot.tap_point(where["tab"])
    bot.sleep(0.9)
    return True


def _yellow(frame, box):
    """True if a button is the selected (yellow) one."""
    import cv2
    x, y, w, h = [int(v) for v in box]
    patch = frame[max(0, y):y + h, max(0, x):x + w]
    if patch.size == 0:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    return float(((hsv[:, 0] >= 18) & (hsv[:, 0] <= 35) & (hsv[:, 1] > 130) & (hsv[:, 2] > 170)).mean()) > 0.3


# the filter popup (left of the panel) always opens at the same place: its buttons
FILTER_LABEL = (805, 500, 150, 48)        # "Sorting"
FILTER_BUTTONS = {"costmin": (1042, 553, 208, 74), "costmax": (812, 553, 208, 74),
                  "gold": (812, 186, 208, 74), "elixir": (1042, 186, 208, 74), "dark": (1270, 186, 208, 74),
                  "army": (812, 328, 208, 74), "defense": (1042, 328, 208, 74), "hero": (1270, 328, 208, 74),
                  "resource": (812, 415, 208, 74), "new": (1042, 415, 208, 74),
                  "permanent": (1270, 415, 208, 74)}


def ensure_sorted(bot, where, account=None):
    """Make the open panel list "Cost Min" (cheapest first) with no filter on. The game forgets it when
    an account is loaded, so it is checked once per account visit (a second each: the popup's buttons
    are always at the same place, their colour tells which are on). Returns True if sorted."""
    account = account if account is not None else (bot.current_acc or {})
    key = "_sorted_" + where["tab"]
    if account.get(key) is not None:
        return account[key]
    bot.tap_point("build.filter")
    bot.sleep(0.8)
    f = bot.shot()
    text, _ = vision.text_reader.read_line(f, space.region(*FILTER_LABEL))
    if "sort" not in text.lower():
        log.info("The %s list has no sorting popup: reading all of it", where["tab"].split(".")[-1])
        bot.tap_point("build.filter")
        bot.sleep(0.5)
        account[key] = False
        return False
    taps = [name for name, box in FILTER_BUTTONS.items()
            if (name == "costmin") != _yellow(f, space.region(*box))]   # Cost Min on, everything else off
    for name in taps:
        x, y, w, h = space.region(*FILTER_BUTTONS[name])
        bot.tap(x + w // 2, y + h // 2, jitter=2)
        bot.sleep(0.35)
    if taps:
        log.info("Builder list sorted by cost (cheapest first)")
    bot.tap_point("build.filter")                          # close the filter popup
    bot.sleep(0.6)
    account[key] = True
    return True


# ----------------------------------------------------------------------------- one page
def _detect(frame, region):
    x0, y0, w, h = region
    area = frame[y0:y0 + h, x0:x0 + w]
    with vision.text_reader._lock:
        res, _ = vision.text_reader._get()(area, use_det=True, use_cls=False, use_rec=False)
    out = []
    for pts in res or []:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        out.append((int(min(xs)) + x0, int(min(ys)) + y0, int(max(xs) - min(xs)), int(max(ys) - min(ys))))
    return sorted(out, key=lambda b: (b[1], b[0]))


def _line(frame, b):
    text, _ = vision.text_reader.read_line(frame, (b[0] - 3, b[1] - 3, b[2] + 6, b[3] + 6))
    return text


def read_page(frame, want_name=None):
    """Rows with a price on one page of the open panel, and the times of the upgrades in progress.
    want_name(row) decides which rows get their name read (default: affordable-looking ones).
    Returns (rows, progress_seconds)."""
    from . import upgrades, village
    region = space.region(*PANEL)
    sx = space.s(100) / 100
    right_x = space.point(PRICE_RIGHT, 0)[0]
    lo, hi = space.point(NAME_X[0], 0)[0], space.point(NAME_X[1], 0)[0]
    boxes = _detect(frame, region)
    right = [b for b in boxes if abs(b[0] + b[2] - right_x) < 30 * sx and b[0] > right_x - 260 * sx]
    names = [b for b in boxes if lo - 20 * sx <= b[0] <= hi]
    rows, progress, used = [], [], set()
    for i, b in enumerate(right):
        if i in used:
            continue
        below = next((j for j in range(i + 1, len(right)) if 15 * sx <= right[j][1] - b[1] <= 45 * sx), None)
        timeless = below is None
        if below is not None:
            used.add(below)
            price = right[below]
        else:                                               # one line only: a time in progress, or a price
            text = _line(frame, b)                           # with no time (walls), or FREE
            secs = timers.parse_time(text)
            if secs:
                progress.append(secs)
                continue
            if len(re.sub(r"\D", "", text)) < 3 or re.search(r"[A-Za-z]", text):
                continue
            price = b
        px, py, pw, ph = price
        if py + ph > region[1] + region[3] - 10 * sx:
            continue                                        # cut off at the bottom
        name_box = max((n for n in names if py - 50 * sx <= n[1] < py - 5 * sx and n[2] > 40 * sx),
                       key=lambda n: n[1], default=None)
        if name_box is None:
            continue                                        # its name is cut off at the top
        res = upgrades._resource_right(frame, price)
        red = village._is_red(frame, price)
        cost = None if red else vision.digits.read(frame, (px - 4, py - 2, pw + 8, ph + 4))
        new = any(abs(n[1] - py) < 25 * sx and n[2] < 75 * sx for n in names)   # the short "New" under the name
        row = {"cost": cost, "res": res, "red": red, "new": new, "name": None, "base": None,
               "timeless": timeless,                        # a price with no time: walls (done at once)
               "tap": (name_box[0] + min(name_box[2], space.s(160)) // 2, name_box[1] + name_box[3] // 2),
               "y": py}
        if want_name is None:
            ask = not red and res in RESOURCES and cost is not None
        else:
            ask = want_name(row)
        if ask:
            row["name"] = _line(frame, name_box).strip()
            row["base"] = upgrades._base(row["name"])
        rows.append(row)
    return rows, progress


def _shift(before, after):
    """How far the list moved up between two pictures of the panel (in pixels): a strip of the lower
    part of `before` is found again in `after`. The rows all look alike, so counting changed pixels
    is not reliable here; finding the strip is."""
    import cv2
    h = before.shape[0]
    top = int(h * 0.70)
    strip = before[top:top + int(h * 0.12)]
    r = cv2.matchTemplate(after, strip, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(r)
    return (top - loc[1]) if score > 0.8 else None


def _scroll(bot, check=True, up=False):
    """One page down (or up). check: return False if the list did not move (its end)."""
    x, y, w, h = space.region(*PANEL)
    cx, low, step = x + w // 2, y + h - space.s(80), space.s(STEP)   # not the very bottom: the village takes that
    before = bot.shot()[y:y + h, x:x + w] if check else None
    for attempt in range(2 if check else 1):
        if up:
            bot.swipe((cx, low - step), (cx, low), 700)
        else:
            bot.swipe((cx, low), (cx, low - step), 700)
        bot.sleep(0.45)
        if not check:
            return True
        moved = _shift(before, bot.shot()[y:y + h, x:x + w])
        log.debug("panel scrolled %s px", moved)
        if moved is None or abs(moved) > space.s(20):
            return True
    return False                                    # did not move twice: the end of the list


# ----------------------------------------------------------------------------- whole list
AT = {"page": None}                     # the page of the open panel on screen now (for a direct tap)


def scan(bot, where, have, need=("gold", "elixir"), full=False, account=None, max_pages=16, stop_when=None,
         start_page=0, want=None):
    """Read the panel's list from the top. With the list sorted cheapest first, reading stops once
    every resource in `need` has shown a price the account cannot pay (all later ones cost more).
    full=True reads to the end and every row's name (for "is anything of the plan still listed?").
    stop_when(rows so far): True ends the reading early (the best possible choice is found).
    start_page: jump that many pages down without reading (the wanted row is known to be further
    down); want(row): which rows get their name read.
    Returns dict(rows, progress, complete, sorted)."""
    AT["page"] = None
    if not open_menu(bot, where):
        return {"rows": [], "progress": [], "complete": False, "sorted": False}
    is_sorted = ensure_sorted(bot, where, account)
    done = {r: False for r in need}
    seen, out, progress = set(), [], []
    if want is None and full:
        want = lambda r: r["res"] in RESOURCES             # noqa: E731
    complete = False
    progress = read_page(bot.shot(), lambda r: False)[1] if start_page else []
    for _ in range(start_page if is_sorted else 0):
        _scroll(bot, check=False)
    if start_page and is_sorted:
        bot.sleep(0.3)
    first = start_page if is_sorted else 0
    for page in range(first, first + max_pages):
        control.checkpoint()
        rows, prog = read_page(bot.shot(), want)
        AT["page"] = page
        if page == 0:
            progress = prog
        for r in rows:
            key = (r["base"], r["cost"], r["res"], r["red"], r["new"])
            if key in seen:
                continue                                    # the half-page scroll shows rows twice
            seen.add(key)
            out.append(dict(r, page=page))
            res = r["res"]
            if res in done and (r["red"] or (r["cost"] and have.get(res) is not None and r["cost"] > have[res])):
                done[res] = True
        if is_sorted and not full and done and all(done.values()):
            break                                           # every later price is too high
        if is_sorted and not full and stop_when is not None and stop_when(out):
            break                                           # nothing later can be a better choice
        if not _scroll(bot):
            complete = True
            break
        AT["page"] = None
    return {"rows": out, "progress": progress, "complete": complete, "sorted": is_sorted, "first": first}


def goto_row(bot, where, item, account=None):
    """Open the panel, go to the page the row was seen on and tap it (found again by its name, the
    closest price of that name). True if tapped. A row on the page shown right now is tapped directly."""
    if AT["page"] is not None and AT["page"] == item.get("page") and item.get("tap") \
            and vision.find(bot.shot(), "build/close"):
        AT["page"] = None
        bot.tap(*item["tap"], jitter=2)
        return True
    AT["page"] = None
    if not open_menu(bot, where):
        return False
    ensure_sorted(bot, where, account)
    page = int(item.get("page", 0))
    for _ in range(page):                                   # the list moves exactly a page per swipe
        _scroll(bot, check=False)
    bot.sleep(0.3)
    for attempt in range(4):                                # its page; then a bit higher (a row above it may
        control.checkpoint()                                # be gone), then further down

        def want(r):
            return (not r["red"] and r["res"] == item["res"] and r["cost"]
                    and abs(r["cost"] - item["cost"]) <= max(1, item["cost"]) * 0.5)

        rows, _ = read_page(bot.shot(), want)
        same = [r for r in rows if r["base"] == item["base"] and r["new"] == item.get("new", False)]
        if same:
            hit = min(same, key=lambda r: abs((r["cost"] or 0) - item["cost"]))
            if hit["cost"] and hit["cost"] != item["cost"]:
                log.info("%s: price changed from %s to %s", item["name"], f"{item['cost']:,}", f"{hit['cost']:,}")
                item["cost"] = hit["cost"]
            bot.tap(*hit["tap"], jitter=2)
            return True
        if attempt == 0 and page > 0:
            x, y, w, h = space.region(*PANEL)
            cx, low = x + w // 2, y + h - space.s(80)
            bot.swipe((cx, low - space.s(STEP // 2)), (cx, low), 600)     # half a page back up
            bot.sleep(0.45)
        elif not _scroll(bot):
            break
    return False


def next_free_in(progress, started):
    """Seconds until the next builder (lab) is free: the soonest upgrade in progress or just started."""
    times = [t for t in list(progress) + list(started) if t]
    return min(times) if times else None


def remember(bot, account, kind, secs):
    """Remember when this account's builder / lab is free again (no menu to open: the time is known)."""
    t = timers._timers(bot).setdefault(account["name"], {})
    if secs:
        t[kind] = time.time() + secs + 20
        log.info("%s: %s free again in %s", account["name"], kind.replace("_", " "), timers._fmt(secs))
    else:
        t.pop(kind, None)
    if bot.state is not None:
        from .. import config
        config.save_state(bot.state)

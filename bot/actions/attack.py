"""Deploying an army with an attack plan, then ending the battle.

Plans live in config/attack_plans.json. A step selects a unit (keyboard key on
PC, or troop-bar slot number on ADB where there is no keyboard) and drops it
at a list of points.

Smart deployment (Loot Settings):
  * count_troops - read the count on the card (x15) and tap exactly that many
    times, checking after each tap that one unit really came out. A tap that
    did not deploy (illegal spot) moves that spot and tries again. Stops the
    moment the card is empty, so no unit is dropped by accident.
  * smart_deploy - instead of fixed points, drop troops on a ring just outside
    the scouted base's buildings (see deployzone.py). Heroes go to the ring point
    nearest the plan's hero spot. Spells always use the plan's points.
  * afterwards any troop still left on the bar is dropped on the ring (except
    for strategies that deliberately use a different deployment gesture).
"""

import copy
import json
import logging
import math
import os
import random
import re
import time

import cv2
import numpy as np

from .. import paths
from ..core import vision
from ..core.control import control
from ..core.profile import profile
from ..core.space import space
from ..states import detect, surrender
from . import deployzone

log = logging.getLogger("bot")

PLANS_PATH = os.path.join(paths.CONFIG, "attack_plans.json")

# The old bot's E-Dragon attack (typos in its third deploy pass fixed).
DEFAULT_PLANS = {
    "edrag_spread": {
        "description": "Spells on 3 sides, E-Dragons + Lava + Baby all round, heroes on 4 sides, siege last",
        "offsets": [[-15, -15], [0, 0], [15, 15]],
        "points": {
            "spells": [[240, 525], [913, 10], [1708, 520]],
            "ring": [[683, 876], [491, 714], [240, 525], [515, 312], [751, 137], [913, 10],
                     [1177, 125], [1438, 306], [1708, 520], [1539, 675], [1298, 848]],
            "king": [[491, 714]],
            "queen": [[751, 137]],
            "warden": [[1438, 306]],
            "champion": [[1298, 848]],
        },
        "steps": [
            {"key": "a", "slot": 9, "points": "spells", "type": "spell"},
            {"key": "3", "slot": 3, "points": "ring", "type": "troop"},
            {"key": "1", "slot": 1, "points": "ring", "type": "troop"},
            {"key": "2", "slot": 2, "points": "ring", "type": "troop"},
            {"key": "q", "slot": 5, "points": "king", "type": "hero"},
            {"key": "w", "slot": 6, "points": "queen", "type": "hero"},
            {"key": "e", "slot": 7, "points": "warden", "type": "hero"},
            {"key": "r", "slot": 8, "points": "champion", "type": "hero"},
            {"key": "z", "slot": 4, "points": "ring", "type": "siege"},
        ],
    },
    "troop_spam": {
        "title": "Troop Spam",
        "description": "Swipe troop-bar slot 1 around the perimeter, then deploy the siege, heroes, and earthquake spells.",
        "style": "troop_spam",
        "points": {
            "corners": {
                "left": [240, 525],
                "top": [913, 10],
                "right": [1708, 520],
                "bottom": [683, 876],
            },
            "ring": [[683, 876], [491, 714], [240, 525], [515, 312], [751, 137], [913, 10],
                     [1177, 125], [1438, 306], [1708, 520], [1539, 675], [1298, 848]],
            "king": [[491, 714]],
            "queen": [[751, 137]],
            "warden": [[1438, 306]],
            "champion": [[1298, 848]],
            "spells": [[240, 525], [913, 10], [1708, 520]],
        },
        "steps": [
            {"key": "1", "slot": 1, "points": "ring", "type": "troop"},
            {"key": "z", "slot": 4, "points": "ring", "type": "siege"},
            {"key": "q", "slot": 5, "points": "king", "type": "hero"},
            {"key": "w", "slot": 6, "points": "queen", "type": "hero"},
            {"key": "e", "slot": 7, "points": "warden", "type": "hero"},
            {"key": "r", "slot": 8, "points": "champion", "type": "hero"},
            {"key": "a", "slot": 9, "points": "spells", "type": "spell"},
        ],
    },
    "edrag_perimeter": {
        "title": "E-Dragon Perimeter",
        "description": "Deploy E-Dragons around the perimeter, then the siege, heroes, and earthquake spells.",
        "points": {
            "ring": [[683, 876], [491, 714], [240, 525], [515, 312], [751, 137], [913, 10],
                     [1177, 125], [1438, 306], [1708, 520], [1539, 675], [1298, 848]],
            "spells": [[240, 525], [913, 10], [1708, 520]],
            "king": [[491, 714]],
            "queen": [[751, 137]],
            "warden": [[1438, 306]],
            "champion": [[1298, 848]],
        },
        "steps": [
            {"key": "1", "slot": 1, "points": "ring", "type": "troop"},
            {"key": "z", "slot": 4, "points": "ring", "type": "siege"},
            {"key": "q", "slot": 5, "points": "king", "type": "hero"},
            {"key": "w", "slot": 6, "points": "queen", "type": "hero"},
            {"key": "e", "slot": 7, "points": "warden", "type": "hero"},
            {"key": "r", "slot": 8, "points": "champion", "type": "hero"},
            {"key": "a", "slot": 9, "points": "spells", "type": "spell"},
        ],
    },
    "valkyrie_sneaky_minion": {
        "title": "Valkyries / Sneaky Goblins / Super Minions",
        "description": "Continuous randomized perimeter drag, optional Super Dragon, siege, randomized hero abilities, then 11 Earthquake clicks.",
        "style": "perimeter_hero_earthquake",
        "optional_units": [{"template": "battle/super_dragon", "type": "troop", "points": "ring"}],
        "siege_templates": ["battle/log_launcher", "battle/siege_barracks"],
        "points": {
            "corners": {
                "left": [240, 525],
                "top": [913, 10],
                "right": [1708, 520],
                "bottom": [683, 876],
            },
            "ring": [[683, 876], [491, 714], [240, 525], [515, 312], [751, 137], [913, 10],
                     [1177, 125], [1438, 306], [1708, 520], [1539, 675], [1298, 848]],
            "spells": [[240, 525], [913, 10], [1708, 520]],
            "queen": [[491, 714]],
            "warden": [[751, 137]],
            "champion": [[1438, 306]],
            "king": [[1298, 848]],
            "prince": [[1177, 125]],
            "dragonduke": [[1539, 675]],
        },
        "steps": [
            {"key": "1", "slot": 1, "points": "ring", "type": "troop", "role": "primary"},
            {"key": "z", "slot": 3, "points": "ring", "type": "siege"},
            {"key": "q", "slot": 4, "points": "queen", "type": "hero"},
            {"key": "w", "slot": 5, "points": "warden", "type": "hero"},
            {"key": "e", "slot": 6, "points": "champion", "type": "hero"},
            {"key": "r", "slot": 7, "points": "king", "type": "hero"},
            {"key": "t", "slot": 8, "points": "prince", "type": "hero"},
            {"key": "y", "slot": 9, "points": "dragonduke", "type": "hero"},
            {"key": "a", "slot": 10, "points": "spells", "type": "spell"},
        ],
    },
}


def load_plans():
    if not os.path.exists(PLANS_PATH):
        with open(PLANS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PLANS, f, indent=2)
    with open(PLANS_PATH, encoding="utf-8") as f:
        plans = copy.deepcopy(DEFAULT_PLANS)
        plans.update(json.load(f))
        return plans


def get_plan(name):
    plans = load_plans()
    if name not in plans:
        log.warning("Attack plan '%s' not found; using edrag_spread", name)
        return copy.deepcopy(DEFAULT_PLANS["edrag_spread"])
    return plans[name]


def step_type(step):
    if step.get("type"):
        return step["type"]
    k = (step.get("key") or "").lower()
    if k in ("q", "w", "e", "r", "t", "y"):
        return "hero"
    if k in ("a", "s", "d", "f", "g"):
        return "spell"
    if k in ("z", "x"):
        return "siege"
    return "troop"


# --- troop bar ------------------------------------------------------------------------

def detect_slots(frame, region=None):
    """X centres of the troop-bar cards, left to right (cards are ~108 px wide)."""
    x, y, w, h = region or (0, frame.shape[0] - space.s(140), frame.shape[1], space.s(120))
    gray = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY).astype(np.float32)
    edge = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)) > 60
    cols = np.where(edge.mean(axis=0) > 0.6)[0]
    borders = []
    for c in cols:
        if borders and c - borders[-1][-1] <= 3:
            borders[-1].append(c)
        else:
            borders.append([c])
    borders = [int(np.mean(b)) for b in borders]
    cards, i = [], 0
    while i < len(borders):
        a = borders[i]
        pair = next((j for j in range(i + 1, len(borders))
                     if space.s(98) <= borders[j] - a <= space.s(120)), None)
        if pair is None:
            i += 1
            continue
        cards.append(x + (a + borders[pair]) // 2)
        i = pair + 1
    return cards


KEY_ORDER = {"troop": "123456789", "siege": "ZXCV", "hero": "QWERTY", "spell": "ASDFGHJKL"}
OCR_FIX = {"艺": "Z", "乙": "Z", "2Z": "Z", "0": "Q", "O": "Q", "V": "W", "VV": "W", "5": "S", "$": "S",
           "|": "1", "I": "1", "L": "1", "l": "1", "B": "8"}


_HINTS = {}


def _hint_templates():
    """Key-hint letters (assets/profiles/<profile>/templates/hint/<key>.png)."""
    folder = os.path.join(profile.templates, "hint")
    if not _HINTS and os.path.isdir(folder):
        for n in os.listdir(folder):
            if n.endswith(".png"):
                _HINTS[n[:-4]] = cv2.imdecode(np.fromfile(os.path.join(folder, n), dtype=np.uint8), cv2.IMREAD_COLOR)
    return _HINTS


def card_keys(frame, slots):
    """Read the keyboard hint printed on each card ("1", "Z", "Q", "A"...). Returns {key: card x}.
    OCR slips are fixed from the bar's fixed order: troops 1,2,3.. siege Z.. heroes Q,W,E,R,T,Y.. spells A,S,D.."""
    y = space.point(0, 1026)[1]
    hints = _hint_templates()
    raw = []
    for cx in slots:
        area = frame[y:y + space.s(56), cx + space.s(20):cx + space.s(68)]   # tall: a raised card moves up
        best, best_s = "", 0.0
        for k, tpl in hints.items():
            if area.shape[0] >= tpl.shape[0] and area.shape[1] >= tpl.shape[1]:
                sc = float(cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED).max())
                if sc > best_s:
                    best, best_s = k.upper(), sc
        if best_s >= 0.8:
            raw.append((best, best_s))
            continue
        text, conf = vision.text_reader.read_line(frame, (cx + space.s(22), y + space.s(10), space.s(42),
                                                          space.s(40)))   # unknown letter: OCR
        text = text.strip()
        if text in OCR_FIX:
            raw.append((OCR_FIX[text], max(conf, 0.5)))       # a known look-alike: trust the mapping
        else:
            raw.append((text.upper()[:1], conf))
    valid = set("".join(KEY_ORDER.values()))
    keys = [t if conf >= 0.45 and t in valid else "" for t, conf in raw]
    # a key can only appear once: keep the most confident reading
    for k in set(keys) - {""}:
        idx = [i for i, t in enumerate(keys) if t == k]
        if len(idx) > 1:
            best = max(idx, key=lambda i: raw[i][1])
            for i in idx:
                if i != best:
                    keys[i] = ""
    # fill gaps from the neighbours: next after the left one, or the one before the right one
    for _ in range(2):
        for i, k in enumerate(keys):
            if k:
                continue
            left = keys[i - 1] if i > 0 else ""
            right = keys[i + 1] if i + 1 < len(keys) else ""
            guess = ""
            for order in KEY_ORDER.values():
                if left and left in order and order.index(left) + 1 < len(order):
                    nxt = order[order.index(left) + 1]
                    # between troops and heroes there may be a siege instead of another troop
                    if not (right and right not in order and raw[i][0] in KEY_ORDER["siege"]):
                        guess = nxt
                    break
                if right and right in order and order.index(right) > 0:
                    guess = order[order.index(right) - 1]
                    break
            if raw[i][0] in valid and raw[i][0] not in keys:
                guess = raw[i][0]                      # a weak but unique reading beats a guess
            if guess and guess not in keys:
                keys[i] = guess
    return {k.lower(): cx for k, cx in zip(keys, slots) if k}


def _card_y():
    return space.point(0, 1000)[1]


def read_count(frame, cx):
    """The 'x15' count on the card centred at cx, or None (heroes/sieges have none, empty is grey).
    The selected card is raised a few pixels, so both label positions are read and the
    longer number wins."""
    best = None
    for top in (924, 915):
        v = vision.digits.read(frame, (cx - space.s(10), space.point(0, top)[1], space.s(62), space.s(32)))
        if v is not None and (best is None or len(str(v)) > len(str(best))):
            best = v
    if best is None:            # the selected card is lighter: the game-font reader misses its white digits
        text, conf = vision.text_reader.read_line(frame, (cx - space.s(12), space.point(0, 915)[1], space.s(70),
                                                          space.s(34)))
        m = re.match(r"\s*[x×]\s*(\d{1,3})\s*$", text.lower())
        if m and conf > 0.6:
            best = int(m.group(1))
    return best


def slot_empty(frame, cx):
    """Used-up cards turn grey."""
    y = space.point(0, 960)[1]
    card = frame[y:y + space.s(70), max(0, cx - space.s(45)):cx + space.s(45)]
    return cv2.cvtColor(card, cv2.COLOR_BGR2HSV)[:, :, 1].mean() < 25


def event_lavaloon_slot(frame, slots):
    """Find the event Lavaloon card by its distinctive x50 count.

    Return its troop-bar slot index only when exactly one card has that count;
    otherwise it is unsafe to guess which stack is the event troop.
    """
    matches = [i for i, cx in enumerate(slots) if not slot_empty(frame, cx) and read_count(frame, cx) == 50]
    if len(matches) == 1:
        return matches[0] + 1
    return None


def _card(frame, cx):
    y = space.point(0, 925)[1]
    return frame[y:y + space.s(130), max(0, cx - space.s(50)):cx + space.s(50)].astype(np.int16)


def select(bot, step, slots):
    """Select the unit for a step: keyboard on PC, tap the card on ADB."""
    if bot.device.supports_keys and step.get("key"):
        bot.key(step["key"])
        return True
    n = step.get("slot")
    if n and 1 <= n <= len(slots):
        bot.tap(slots[n - 1], _card_y(), jitter=4)
        return True
    log.warning("Step %s: slot %s not on the troop bar", step, n)
    return False


# --- placing ----------------------------------------------------------------------------

def _spread(points, n):
    """n points picked evenly around a list (cycling if n > len)."""
    if not points or n <= 0:
        return []
    if n >= len(points):
        return [points[i % len(points)] for i in range(n)]
    return [points[int(i * len(points) / n)] for i in range(n)]


def _nudge(pt, centre, outward=True, step=34):
    """Move a point away from (or toward) the base centre."""
    x, y = pt
    dx, dy = x - centre[0], y - centre[1]
    d = math.hypot(dx, dy) or 1.0
    k = step if outward else -step
    return int(x + dx / d * k), int(y + dy / d * k)


def _label(frame, cx):
    y = space.point(0, 910)[1]
    return frame[y:y + space.s(50), max(0, cx - space.s(12)):cx + space.s(54)].astype(np.int16)


def _drop(bot, cx, spots, centre, single=False, fixes=None, reselect=None, count_override=None):
    """Drop every unit on the card at cx, checking that each tap really deployed one.

    Units with a count (x15) are tracked by the count; a hero, a siege machine or
    anything without a readable count is one unit, confirmed by its card changing.
    A tap that did nothing (red area / outside the map) moves that spot and retries.
    Stops as soon as the card is empty, so the game never auto-selects the next unit
    under our taps.
    """
    if not spots:
        return
    fixes = {} if fixes is None else fixes

    def fixed(p):
        seen = 0
        while p is not None and p in fixes and seen < 10:   # corrections learned earlier this attack
            p, seen = fixes[p], seen + 1
        return p

    frame = bot.shot()
    wanted = list(spots)
    spots = [p for p in (fixed(p) for p in spots) if p is not None and deployzone.valid_spot(frame, *p)]
    good = fixes.setdefault("__good__", [])          # spots where a unit was really deployed this attack
    if not spots and good:
        # every planned spot turned out unusable: use the closest spots that worked for others
        ref = wanted[0] if wanted else centre
        spots = sorted(set(good), key=lambda g: (g[0] - ref[0]) ** 2 + (g[1] - ref[1]) ** 2)[:max(1, len(wanted))]
    if not spots:
        log.warning("No usable deploy spots left")
        return False
    moves = {}
    count = None if single else (count_override if count_override is not None else read_count(frame, cx))
    by_count = count is not None
    left = count if by_count else 1
    queue = _spread(spots, left)
    deployed = False
    tries, max_tries = 0, left * 2 + 10
    while left > 0 and queue and tries < max_tries:
        control.checkpoint()
        tries += 1
        card0, label0 = _card(frame, cx), _label(frame, cx)
        x, y = queue.pop(0)
        bot.tap(x, y, jitter=3)
        ok = False
        waited = 0.0
        for pause in (0.08, 0.1, 0.1, 0.12):               # the bar updates ~0.1-0.2 s after a tap
            time.sleep(pause)
            waited += pause
            frame = bot.shot()
            if slot_empty(frame, cx):
                good.append((x, y))
                return True
            if by_count:
                now = read_count(frame, cx)
                if now is not None and now < left:
                    left, ok = now, True
                    break
                if now is None and np.abs(_label(frame, cx) - label0).mean() > 10:
                    left, ok = left - 1, True              # number changed but not readable
                    break
            elif np.abs(_card(frame, cx) - card0).mean() > 12:
                good.append((x, y))
                return True                                 # the single unit is on the field
        if ok:
            good.append((x, y))
            deployed = True
        log.debug("tap %s: %s, %s left (%.2fs)", (x, y), "ok" if ok else "no effect", left, waited)
        if not ok:
            # illegal spot: inside the red zone -> move it out; beyond the map -> move it in.
            # A moved spot must still be on the map and off every button, and moves at most 3 times.
            n = moves.get((x, y), 0) + 1
            nx, ny = _nudge((x, y), centre, outward=deployzone.in_diamond(x, y, inset=-deployzone.MAP_GROW))
            if n <= 3 and deployzone.valid_spot(frame, nx, ny):
                fixes[(x, y)] = (nx, ny)
                moves[(nx, ny)] = n
                queue.append((nx, ny))
            else:
                fixes[(x, y)] = None
                spots = [p for p in spots if p != (x, y)]
            if reselect:
                reselect()                         # in case a stray tap selected something else
        if not queue and left > 0:
            queue = [p for p in (fixed(p) for p in _spread(spots, left)) if p is not None]
    return deployed


def _deploy_troop_spam(bot, step, slots, card_of, points):
    """Deploy the selected troop along the four sides, like the legacy TroopSpam strategy."""
    cx = card_of(step)
    if cx is not None and slot_empty(bot.shot(), cx):
        return
    if not select(bot, step, slots):
        return
    corners = ("top", "right", "bottom", "left")
    start = random.choice((1, 3))
    direction = random.choice((1, -1))
    order = [corners[(start + i * direction) % len(corners)] for i in range(len(corners) + 1)]
    anchors = points["corners"]
    for current, following in zip(order, order[1:]):
        if cx is not None and slot_empty(bot.shot(), cx):
            break
        x1, y1 = space.center(*anchors[current])
        x2, y2 = space.center(*anchors[following])
        x1 += random.randint(-10, 10)
        y1 += random.randint(-10, 10)
        x2 += random.randint(-10, 10)
        y2 += random.randint(-10, 10)
        bot.swipe((x1, y1), (x2, y2), 800)


def _sample_arc(anchors, count):
    """Sample a circular arc from left to right that passes through its top anchor."""
    (lx, ly), (tx, ty), (rx, ry) = anchors
    d = 2 * (lx * (ty - ry) + tx * (ry - ly) + rx * (ly - ty))
    if count < 2:
        return [(int(round(lx)), int(round(ly)))]
    if abs(d) < 1e-6:
        cx, cy = 2 * tx - (lx + rx) / 2, 2 * ty - (ly + ry) / 2
        return [(int(round((1 - t) ** 2 * lx + 2 * (1 - t) * t * cx + t ** 2 * rx)),
                 int(round((1 - t) ** 2 * ly + 2 * (1 - t) * t * cy + t ** 2 * ry)))
                for t in (i / (count - 1) for i in range(count))]
    l2, t2, r2 = lx * lx + ly * ly, tx * tx + ty * ty, rx * rx + ry * ry
    ox = (l2 * (ty - ry) + t2 * (ry - ly) + r2 * (ly - ty)) / d
    oy = (l2 * (rx - tx) + t2 * (lx - rx) + r2 * (tx - lx)) / d
    radius = math.hypot(lx - ox, ly - oy)

    def angle(point):
        return math.atan2(point[1] - oy, point[0] - ox)

    start, middle, end = angle((lx, ly)), angle((tx, ty)), angle((rx, ry))
    span = (end - start) % (2 * math.pi)
    middle_span = (middle - start) % (2 * math.pi)
    sweep = span if middle_span <= span else span - 2 * math.pi
    return [(int(round(ox + radius * math.cos(start + i / (count - 1) * sweep))),
             int(round(oy + radius * math.sin(start + i / (count - 1) * sweep))))
            for i in range(count)]


def _inside_polygon(x, y, polygon):
    inside = False
    j = len(polygon) - 1
    for i, (ix, iy) in enumerate(polygon):
        jx, jy = polygon[j]
        if (iy > y) != (jy > y) and x < (jx - ix) * (y - iy) / (jy - iy) + ix:
            inside = not inside
        j = i
    return inside


def _polygon_double_area(polygon):
    return sum(x1 * y2 - x2 * y1
               for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]))


def _earthquake_points(anchors, width, height, method):
    """Return eleven bounded curve or random-region Earthquake points."""
    def bounded(points):
        return [(max(0, min(width - 1, x)), max(0, min(height - 1, y))) for x, y in points]

    def curve():
        arc = _sample_arc(anchors, 11)
        if random.choice((True, False)):
            arc.reverse()
        return bounded([(x + random.randint(-100, 100), y + random.randint(-100, 100)) for x, y in arc])

    if method == "curve":
        return curve()
    if method != "random":
        log.warning("Unknown Earthquake placement %r; using curve placement", method)
        return curve()
    dense = _sample_arc(anchors, 49)
    line_y = round((height - 1) * 0.6)
    polygon = dense + [(dense[-1][0], line_y), (dense[0][0], line_y)]
    if len(polygon) < 3 or abs(_polygon_double_area(polygon)) < 2:
        log.warning("Earthquake random region is degenerate; using curve placement")
        return curve()
    min_x = max(0, min(p[0] for p in polygon))
    max_x = min(width - 1, max(p[0] for p in polygon))
    min_y = max(0, min(p[1] for p in polygon))
    max_y = min(height - 1, max(p[1] for p in polygon))
    points = []
    for _ in range(11):
        for _ in range(1000):
            point = (random.randint(min_x, max_x), random.randint(min_y, max_y))
            if _inside_polygon(*point, polygon):
                points.append(point)
                break
        else:
            return curve()
    return points


def _template_card_step(template, frame, slots, by_key):
    """Find an optional troop card by its captured troop-bar icon template."""
    if not vision.templates.has(template):
        log.debug("Optional troop skipped; template %s has not been captured", template)
        return None
    region = (0, max(0, frame.shape[0] - space.s(140)), frame.shape[1], space.s(120))
    matches = vision.find_all(frame, template, region=region)
    for match in sorted(matches, key=lambda m: m.score, reverse=True):
        if not slots:
            break
        cx = min(slots, key=lambda slot: abs(slot - match.x))
        if slot_empty(frame, cx):
            continue
        key = next((k for k, x in by_key.items() if x == cx), "")
        if by_key and not key:
            continue
        return {"key": key, "slot": slots.index(cx) + 1, "type": "troop"}
    return None


def _deploy_perimeter_hero_earthquake(bot, plan, steps, frame, slots, by_key, card_of, ring, centre):
    """Run the continuous perimeter drag followed by optional units, heroes, and Earthquakes."""
    points = plan["points"]
    handled = {str(step.get("key") or "").lower() for step in steps}
    main = next((step for step in steps if step.get("role") == "primary"), None)
    if main is None:
        main = next((step for step in steps if step_type(step) == "troop"), None)
    main_card = card_of(main) if main else None
    if main_card is None or slot_empty(frame, main_card):
        log.warning("Perimeter strategy aborted: its primary troop card is not in the deploy bar")
        return handled
    if not select(bot, main, slots):
        log.warning("Perimeter strategy aborted: its primary troop card could not be selected")
        return handled

    corner_names = ("left", "top", "right", "bottom")
    start_options = (0, 2, 1) if space.w / space.h <= 1.7 else (0, 2)
    start = random.choice(start_options)
    direction = random.choice((-1, 1))
    order = [corner_names[(start + direction * i) % len(corner_names)] for i in range(5)]
    path = [space.center(*points["corners"][name]) for name in order]
    durations = [round(1000 * random.uniform(0.9, 1.1)) for _ in range(4)]
    bot.drag_path(path, durations)

    optional = plan.get("optional_units", [])
    for definition in optional:
        optional_step = _template_card_step(definition["template"], bot.shot(), slots, by_key)
        if optional_step is None:
            if not vision.templates.has(definition["template"]):
                log.info("Optional troop skipped: capture its icon as template %s", definition["template"])
            continue
        cx = card_of(optional_step)
        if cx == main_card:
            continue
        if not select(bot, optional_step, slots):
            continue
        spots = ring or [space.center(*p) for p in points.get(definition.get("points", "ring"), [])]
        _drop(bot, cx, spots, centre)

    siege_steps = []
    for template in plan.get("siege_templates", []):
        match = _template_card_step(template, bot.shot(), slots, by_key)
        if match:
            siege_steps = [dict(match, type="siege")]
            break
    if not siege_steps:
        if by_key:
            indexed = {k: x for k, x in by_key.items() if k in "zxcv"}
            siege_steps = [{"key": key, "slot": slots.index(cx) + 1, "type": "siege"}
                           for key, cx in sorted(indexed.items(), key=lambda item: "zxcv".index(item[0]))]
        if not siege_steps:
            siege_steps = [step for step in steps if step_type(step) == "siege"]
    siege_deployed = False
    for step in siege_steps:
        cx = card_of(step)
        current = bot.shot()
        if cx is None or slot_empty(current, cx):
            continue
        if select(bot, step, slots):
            spots = ring or [space.center(*p) for p in points.get(step.get("points", "ring"), [])]
            siege_deployed = _drop(bot, cx, spots, centre, single=True)
            break
    if not siege_deployed:
        log.warning("No siege machine was found in the troop bar")

    heroes = [step for step in steps if step_type(step) == "hero"]
    random.shuffle(heroes)
    for step in heroes:
        cx = card_of(step)
        current = bot.shot()
        if cx is None or slot_empty(current, cx) or not select(bot, step, slots):
            continue
        base = points.get(step.get("points"), points.get("ring", []))
        desired = [space.center(*point) for point in base]
        spots = [min(ring, key=lambda p: (p[0] - desired[0][0]) ** 2 + (p[1] - desired[0][1]) ** 2)] \
            if ring and desired else desired
        if not spots:
            log.warning("No deploy point configured for hero %s", step.get("key"))
            continue
        if _drop(bot, cx, spots, centre, single=True):
            time.sleep(0.15)
            select(bot, step, slots)

    earthquake = next((step for step in steps if step_type(step) == "spell"), None)
    if earthquake:
        cx = card_of(earthquake)
        current = bot.shot()
        if cx is None or slot_empty(current, cx):
            log.warning("Earthquake spell card is not in the deploy bar")
            return handled
        if not select(bot, earthquake, slots):
            return handled
        anchor_points = points.get(earthquake.get("points"), points.get("spells", []))
        anchors = [space.center(*point) for point in anchor_points[:3]]
        if len(anchors) != 3:
            log.warning("Earthquake placement needs three anchor points")
            return handled
        method = (bot.settings.get("loot") or {}).get("earthquake_method", "curve")
        for x, y in _earthquake_points(anchors, space.w, space.h, method):
            bot.tap(x, y, jitter=0)
    return handled


CLONE_IN = 55          # a Clone goes this far inside a dragon group's spot: where the dragons fly to
GROUP_SPREAD = 15      # the units of a group land within this many pixels of its spot (the old bot's offsets)


def clone_card(frame, slots):
    """X of the Clone spell's card on the troop bar (found by its picture, whatever its key), or None."""
    if not vision.templates.has("battle/clone_card"):
        return None
    ms = [m for m in vision.find_all(frame, "battle/clone_card") if not slot_empty(frame, m.x)]
    if not ms:
        return None
    m = max(ms, key=lambda m: m.score)
    return min(slots, key=lambda c: abs(c - m.x)) if slots else m.x


def _sides(plan, ring, centre):
    """The spots of the dragon groups: the plan's spell spots (left, top and right of the map, like
    the old bot), each moved to the nearest point of the deploy ring when the ring was found."""
    pts = [space.center(x, y) for x, y in plan["points"].get("spells", [])] or \
        [space.center(240, 525), space.center(913, 10), space.center(1708, 520)]
    if not ring:
        return pts
    return [min(ring, key=lambda r: (r[0] - p[0]) ** 2 + (r[1] - p[1]) ** 2) for p in pts]


def _toward(pt, centre, d):
    x, y = pt
    dx, dy = centre[0] - x, centre[1] - y
    n = math.hypot(dx, dy) or 1.0
    return int(x + dx / n * d), int(y + dy / n * d)


def deploy_clone_groups(bot, plan, frame, slots, by_key, card_of, ring, centre):
    """E-Dragons + Clone: the dragons go down in a few tight groups (one per side), each group in one
    quick burst, and a Clone is cast on every group right after it lands - while the dragons are still
    inside it (a Clone cast before the dragons, or seconds later somewhere else, copies nothing).
    Returns the set of plan keys it deployed (the rest of the plan does the others)."""
    clone_x = clone_card(frame, slots)
    clone_key = next((k for k, x in by_key.items() if x == clone_x), None) if clone_x is not None else None
    clones = (read_count(frame, clone_x) or 1) if clone_x is not None else 0
    sides = _sides(plan, ring, centre)
    done = set()
    groups = []                                       # (spot, step, n)
    for step in plan["steps"]:
        if step_type(step) != "troop":
            continue
        cx = card_of(step)
        if cx is None or slot_empty(frame, cx):
            continue
        n = read_count(frame, cx)
        if not n:
            continue
        done.add((step.get("key") or "").lower())
        k = len(sides)
        for i, spot in enumerate(sides):
            share = n // k + (1 if i < n % k else 0)
            if share:
                groups.append((spot, step, share))
    if not groups:
        return set()
    log.info("Deploying %d group(s) of troops on %d side(s)%s", len(groups), len(sides),
             f", a Clone on each ({clones} Clone spell(s), key {clone_key or '?'})" if clone_x is not None
             else " (no Clone spell found on the troop bar)")
    cast = 0
    good = []
    for spot, step, n in groups:
        control.checkpoint()
        if not select(bot, step, slots):
            continue
        cx = card_of(step)
        spot = _land(bot, cx, spot, centre)            # the first unit shows the spot can be used
        if spot is None:
            log.info("No usable spot on this side (red area): its %d unit(s) go elsewhere", n)
            continue
        good.append(spot)
        # the others along the ring at that spot (same distance from the base: no red area)
        tx, ty = centre[1] - spot[1], spot[0] - centre[0]
        d = math.hypot(tx, ty) or 1.0
        for i in range(1, n):
            k = ((i + 1) // 2) * (1 if i % 2 else -1) * space.s(GROUP_SPREAD)
            bot.tap(int(spot[0] + tx / d * k), int(spot[1] + ty / d * k), jitter=2)
            time.sleep(0.07)
        if clone_x is not None and cast < clones:
            time.sleep(0.15)
            ok = select(bot, {"key": clone_key, "slot": slots.index(clone_x) + 1 if clone_x in slots else None},
                        slots)
            if ok:
                bot.tap(*_toward(spot, centre, space.s(CLONE_IN)), jitter=2)
                cast += 1
                time.sleep(0.1)
    # Clones left over (more Clones than groups): on the groups again, in the same order
    while clone_x is not None and cast < clones and groups:
        spot = groups[cast % len(groups)][0]
        if not select(bot, {"key": clone_key, "slot": slots.index(clone_x) + 1 if clone_x in slots else None}, slots):
            break
        bot.tap(*_toward(spot, centre, space.s(CLONE_IN + 30)), jitter=2)
        cast += 1
        time.sleep(0.1)
    if clone_key and cast:
        done.add(clone_key)
    bot.deploy_spots = good                           # where units really landed (for leftovers)
    return done


def _land(bot, cx, spot, centre, tries=4):
    """Drop one unit of the selected card at `spot`; if it does not come out (red area, off the map),
    the spot moves out (or in) and is tried again. Returns the spot that worked, or None."""
    frame = bot.shot()
    before = read_count(frame, cx)
    p = spot
    for _ in range(tries):
        if deployzone.valid_spot(frame, *p):
            bot.tap(*p, jitter=1)
            for pause in (0.1, 0.12, 0.15):
                time.sleep(pause)
                frame = bot.shot()
                now = read_count(frame, cx)
                if slot_empty(frame, cx) or (before is not None and now is not None and now < before):
                    return p
                if before is None and now is not None:
                    return p                          # (count not read before: it changed)
            log.debug("deploy spot %s: nothing came out", p)
        outward = deployzone.in_diamond(p[0], p[1], inset=-deployzone.MAP_GROW)
        p = _nudge(p, centre, outward=outward, step=space.s(40))
    return None


def deploy(bot, plan):
    s = bot.settings["loot"]
    smart, verify = s.get("smart_deploy", True), s.get("count_troops", True)
    offsets = plan.get("offsets") or [[0, 0]]
    frame = bot.shot()
    slots = detect_slots(frame)
    by_key = card_keys(frame, slots) if (bot.device.supports_keys and verify and slots) else {}
    if by_key:
        log.debug("Troop bar keys: %s", " ".join(sorted(by_key, key=by_key.get)))

    def card_of(step):
        """X of the card a step uses: by its key hint on PC, else by its slot number."""
        if by_key:
            return by_key.get((step.get("key") or "").lower())
        n = step.get("slot")
        return slots[n - 1] if n and n <= len(slots) else None

    event_slot = event_lavaloon_slot(frame, slots) if s.get("event_lavaloons", False) else None
    event_cx = slots[event_slot - 1] if event_slot is not None else None
    active_steps = [step for step in plan["steps"]
                    if not (event_cx is not None and step_type(step) == "troop" and card_of(step) == event_cx)]
    active_plan = dict(plan, steps=active_steps)

    ring = deployzone.deploy_line(frame) if smart else []
    if smart and len(ring) < 8:
        log.info("Deploy zone not found (%d points); using the plan's points", len(ring))
        bot.save_error("no-deploy-zone")
        ring = []
    if ring:
        centre = (int(np.mean([p[0] for p in ring])), int(np.mean([p[1] for p in ring])))
    else:
        centre = space.center(deployzone.DIAMOND["cx"], deployzone.DIAMOND["cy"])

    def plan_points(step):
        pts = plan["points"].get(step["points"], []) if isinstance(step["points"], str) else step["points"]
        return [space.center(x, y) for x, y in pts]

    def nearest_on_ring(pt):
        return min(ring, key=lambda r: (r[0] - pt[0]) ** 2 + (r[1] - pt[1]) ** 2)

    fixes = {}                                  # bad spot -> corrected spot, shared by all units
    handled = set()
    bot.deploy_spots = []
    bot.deploy_started = time.monotonic()       # the battle clock starts here (not while reading the base)
    if plan.get("style") == "perimeter_hero_earthquake":
        handled = _deploy_perimeter_hero_earthquake(
            bot, plan, active_steps, frame, slots, by_key, card_of, ring, centre)
    elif plan.get("style") == "clone_groups" and verify:
        handled = deploy_clone_groups(bot, active_plan, frame, slots, by_key, card_of, ring, centre)
    for step in active_steps:
        control.checkpoint()
        kind = step_type(step)
        key = (step.get("key") or "").lower()
        if key in handled:
            continue
        cx = card_of(step)
        if by_key and cx is None:
            log.debug("Key %s is not on the troop bar: this army has no such unit", step.get("key"))
            continue
        if plan.get("style") == "troop_spam" and kind == "troop":
            _deploy_troop_spam(bot, step, slots, card_of, plan["points"])
            if key:
                handled.add(key)
            continue
        if cx is not None and slot_empty(bot.shot(), cx):
            continue                         # nothing of this unit left
        if not select(bot, step, slots):
            continue
        base_pts = plan_points(step) if isinstance(step.get("points"), list) or step.get("points") in plan["points"] else []
        if kind == "spell" and step.get("points") == "ring":
            # e.g. Clone right after the dragons: just inside the ring, spread around the base
            src = ring or base_pts
            spots = [(int(x + (centre[0] - x) * 0.18), int(y + (centre[1] - y) * 0.18)) for x, y in src]
        elif kind == "spell" or not ring:
            spots = base_pts
        elif step.get("points") == "ring" and kind != "hero":
            spots = ring
        else:
            spots = [nearest_on_ring(p) for p in base_pts]
        if cx is None or not verify:
            for dx, dy in step.get("offsets", offsets):   # the old way: each point once per offset
                for px, py in spots:
                    bot.tap(px + dx, py + dy, jitter=2)
        else:
            _drop(bot, cx, spots, centre, single=kind in ("hero", "siege"), fixes=fixes,
                  reselect=lambda st=step: select(bot, st, slots))
        time.sleep(0.1)

    if s.get("event_lavaloons", False) and slots:
        frame = bot.shot()
        if event_slot is None:
            log.warning("Event Lavaloon deployment skipped: no unique troop card showed x50")
        else:
            slot = event_slot
            cx = slots[slot - 1]
            event_count = read_count(frame, cx) if not slot_empty(frame, cx) else None
            key = next((k for k, x in by_key.items() if x == cx), None)
            step = {"key": key, "slot": slot, "type": "troop"}
            if event_count and select(bot, step, slots):
                log.info("Deploying all event Lavaloon troops from troop-bar slot %d", slot)
                fallback = next((plan_points(st) for st in active_steps
                                 if step_type(st) == "troop" and st.get("points")), [])
                default_ring = [space.center(x, y) for x, y in DEFAULT_PLANS["edrag_spread"]["points"]["ring"]]
                _drop(bot, cx, ring or fallback or default_ring, centre, fixes=fixes,
                      reselect=lambda st=step: select(bot, st, slots), count_override=event_count)
                remaining_frame = bot.shot()
                if not slot_empty(remaining_frame, cx):
                    remaining = read_count(remaining_frame, cx)
                    if remaining is None:
                        log.warning("Could not verify that all event Lavaloon troops were deployed")
                    elif remaining:
                        log.warning("%d event Lavaloon troop(s) remain undeployed", remaining)
            else:
                log.warning("Event Lavaloon deployment skipped: the x50 troop card is empty or unreadable")

    # any troop of the plan still showing a count on the bar -> drop the rest on the ring
    if verify and slots:
        frame = bot.shot()
        for step in active_steps:
            if (step.get("key") or "").lower() in handled:
                continue
            cx = card_of(step)
            if step_type(step) != "troop" or cx is None:
                continue
            if not slot_empty(frame, cx) and read_count(frame, cx) and select(bot, step, slots):
                log.debug("Dropping leftovers of %s", step.get("key") or step.get("slot"))
                _drop(bot, cx, getattr(bot, "deploy_spots", None) or ring or plan_points(step), centre,
                      fixes=fixes, reselect=lambda st=step: select(bot, st, slots))
                frame = bot.shot()


def finish_battle(bot, seconds, started=None):
    """The battle lasts at most `seconds` from `started` (when the attack began; default now): it
    is surrendered then, retrying until the results show (a single missed Surrender let battles
    run to the game's 3 minutes). Returns True once the results screen is showing."""
    end = (time.monotonic() if started is None else started) + seconds
    while time.monotonic() < end:
        if detect(bot.shot()) == "results":
            return True
        control.sleep(0.6)
    give_up = time.monotonic() + 25
    tries = 0
    while time.monotonic() < give_up:
        frame = bot.shot()
        state = detect(frame)
        if state == "results":
            return True
        if state in ("battle", "unknown", "confirm"):
            if state == "confirm":
                bot.tap_template("battle/confirm_okay", timeout=1)
            elif not surrender(bot, frame, blind=tries >= 2):
                if tries == 1:
                    bot.save_error("no-surrender")     # what is covering the Surrender button
                tries += 1
        control.sleep(0.7)
    log.warning("The battle could not be ended after %d s", seconds)
    return False

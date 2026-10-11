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
  * afterwards any troop still left on the bar is dropped on the ring.
"""

import copy
import json
import logging
import math
import os
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
    }
}


def load_plans():
    if not os.path.exists(PLANS_PATH):
        with open(PLANS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PLANS, f, indent=2)
    with open(PLANS_PATH, encoding="utf-8") as f:
        return json.load(f)


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
    if k in ("q", "w", "e", "r"):
        return "hero"
    if k in ("a", "s", "d", "f", "g"):
        return "spell"
    if k in ("z", "x"):
        return "siege"
    return "troop"


# --- troop bar ------------------------------------------------------------------------

def detect_slots(frame, region=None):
    """X centres of the troop-bar cards, left to right (cards are ~108 px wide)."""
    x, y, w, h = region or (0, frame.shape[0] - 140, frame.shape[1], 120)
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
        pair = next((j for j in range(i + 1, len(borders)) if 98 <= borders[j] - a <= 120), None)
        if pair is None:
            i += 1
            continue
        cards.append(x + (a + borders[pair]) // 2)
        i = pair + 1
    return cards


KEY_ORDER = {"troop": "123456789", "siege": "ZXCV", "hero": "QWERT", "spell": "ASDFGHJKL"}
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
    OCR slips are fixed from the bar's fixed order: troops 1,2,3.. siege Z.. heroes Q,W,E,R.. spells A,S,D.."""
    y = space.point(0, 1026)[1]
    hints = _hint_templates()
    raw = []
    for cx in slots:
        area = frame[y:y + 56, cx + 20:cx + 68]               # tall: a raised (selected) card moves up
        best, best_s = "", 0.0
        for k, tpl in hints.items():
            if area.shape[0] >= tpl.shape[0] and area.shape[1] >= tpl.shape[1]:
                sc = float(cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED).max())
                if sc > best_s:
                    best, best_s = k.upper(), sc
        if best_s >= 0.8:
            raw.append((best, best_s))
            continue
        text, conf = vision.text_reader.read_line(frame, (cx + 22, y + 10, 42, 40))   # unknown letter: OCR
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
        v = vision.digits.read(frame, (cx - 10, space.point(0, top)[1], 62, 32))
        if v is not None and (best is None or len(str(v)) > len(str(best))):
            best = v
    return best


def slot_empty(frame, cx):
    """Used-up cards turn grey."""
    y = space.point(0, 960)[1]
    card = frame[y:y + 70, max(0, cx - 45):cx + 45]
    return cv2.cvtColor(card, cv2.COLOR_BGR2HSV)[:, :, 1].mean() < 25


def _card(frame, cx):
    y = space.point(0, 925)[1]
    return frame[y:y + 130, max(0, cx - 50):cx + 50].astype(np.int16)


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
    return frame[y:y + 50, max(0, cx - 12):cx + 54].astype(np.int16)


def _drop(bot, cx, spots, centre, single=False, fixes=None, reselect=None):
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
        return
    moves = {}
    count = None if single else read_count(frame, cx)
    by_count = count is not None
    left = count if by_count else 1
    queue = _spread(spots, left)
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
                return
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
                return                                      # the single unit is on the field
        if ok:
            good.append((x, y))
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
        pts = plan["points"][step["points"]] if isinstance(step["points"], str) else step["points"]
        return [space.center(x, y) for x, y in pts]

    def nearest_on_ring(pt):
        return min(ring, key=lambda r: (r[0] - pt[0]) ** 2 + (r[1] - pt[1]) ** 2)

    fixes = {}                                  # bad spot -> corrected spot, shared by all units
    for step in plan["steps"]:
        control.checkpoint()
        kind = step_type(step)
        cx = card_of(step)
        if by_key and cx is None:
            log.debug("Key %s is not on the troop bar: this army has no such unit", step.get("key"))
            continue
        if cx is not None and slot_empty(bot.shot(), cx):
            continue                         # nothing of this unit left
        if not select(bot, step, slots):
            continue
        base_pts = plan_points(step)
        if kind == "spell" or not ring:
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

    # any troop of the plan still showing a count on the bar -> drop the rest on the ring
    if verify and slots:
        frame = bot.shot()
        for step in plan["steps"]:
            cx = card_of(step)
            if step_type(step) != "troop" or cx is None:
                continue
            if not slot_empty(frame, cx) and read_count(frame, cx) and select(bot, step, slots):
                log.debug("Dropping leftovers of %s", step.get("key") or step.get("slot"))
                _drop(bot, cx, ring or plan_points(step), centre, fixes=fixes,
                      reselect=lambda st=step: select(bot, st, slots))
                frame = bot.shot()


def finish_battle(bot, seconds):
    """Wait up to `seconds` for the battle to end by itself, then surrender.
    Returns once the results screen is showing (or after a timeout)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if detect(bot.shot()) == "results":
            return True
        control.sleep(1.0)
    surrender(bot)
    for _ in range(20):
        if detect(bot.shot()) == "results":
            return True
        control.sleep(0.5)
    return False

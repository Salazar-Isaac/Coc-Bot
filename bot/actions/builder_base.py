"""Builder Base (the night village): travel there and back, attack, collect and upgrade.

Builder Base battles have two stages: destroy the first base (stage 1), then the surviving
troops plus a new one attack a second, smaller base (stage 2). Each attack can earn up to
6 stars; the "Star Bonus" (the 4/8 counter on the Attack button) pays extra loot until the
daily star bonus is used up. There is no "Next": every attack is one random base.

Upgrades use the same builder menu as the main village. With "gear up for Builder Hall"
on, the bot first upgrades the Builder Hall itself, then the defences the game needs
before the next Builder Hall (Cannon, Archer Tower, Mortar first), then new buildings.
"""

import logging
import time

import cv2
import numpy as np

from ..core import vision
from ..core.context import BotError
from ..core.control import control
from ..core.space import space
from ..states import detect, go_home

log = logging.getLogger("bot")

# Builder-hall-first priority (part of the name is enough)
GEAR_UP_ORDER = ["Builder Hall", "Cannon", "Archer Tower", "Double Cannon", "Mortar", "Multi Mortar",
                 "Crusher", "Air Bombs", "Firecrackers", "Guard Post", "Roaster", "Giant Cannon",
                 "Mega Tesla", "Lava Launcher", "Hidden Tesla", "Builder Barracks", "Elixir Storage",
                 "Gold Storage", "Clock Tower", "Star Laboratory"]


def is_builder_base(frame):
    return vision.find(frame, "bb/attack_button") is not None


def where(bot):
    """'main', 'builder' or None (unknown)."""
    f = bot.shot()
    if vision.find(f, "bb/attack_button"):
        return "builder"
    if detect(f) == "home":
        return "main"
    return None


def go_home_bb(bot, timeout=60.0):
    """Get back to the Builder Base village from any of its screens."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = bot.shot()
        if vision.find(f, "bb/attack_button"):
            return True
        for key, tap in (("bb/star_bonus_okay", None), ("bb/return_home", None), ("bb/menu_close", None),
                         ("upgrade/close", None), ("lab/close", None)):
            if vision.templates.has(key):
                m = vision.find(f, key)
                if m:
                    bot.tap_match(m)
                    break
        else:
            if detect(f) == "home":
                return False                         # we are in the main village
            bot.tap_point("home.safe", jitter=5)
        control.sleep(0.6)
    return False


def _find_boat(bot, here):
    """Find and return the boat of the current village. The camera can be anywhere, so zoom out
    and look; if it is not on screen, pan in a fixed pattern (the boat is at an island edge)."""
    keys = ["home/boat", "home/boat_bubble"] if here == "main" else ["bb/boat", "bb/boat_bubble"]
    full = (0, 0, 1920, 1080)
    pans = [None, ((1300, 300), (600, 800)), ((1300, 300), (600, 800)), ((600, 800), (1300, 300)),
            ((600, 800), (1300, 300)), ((600, 800), (1300, 300)), ((700, 300), (1300, 800)),
            ((1300, 800), (700, 300)), ((1300, 800), (700, 300))]
    for pan in pans:
        control.checkpoint()
        if pan:
            bot.swipe(space.center(*pan[0]), space.center(*pan[1]), 600)
            control.sleep(0.6)
        f = bot.shot()
        for k in keys:
            if vision.templates.has(k):
                m = vision.find(f, k, region=full)
                if m:
                    return m if k.endswith("boat") else type(m)(m.x, m.y + 70, m.score, m.box)   # bubble -> boat
    return None


def travel(bot, to):
    """Sail to the Builder Base (to='builder') or back to the home village (to='main')."""
    here = where(bot)
    if here == to:
        return True
    if here is None:
        if to == "builder" and go_home_bb(bot, 15):
            return True
        if not go_home(bot):
            go_home_bb(bot, 20)
        here = where(bot)
        if here == to:
            return True
    bot.tap_point("home.safe", jitter=5)            # deselect anything first
    bot.device.zoom_out()
    control.sleep(0.5)
    boat = _find_boat(bot, here)
    if boat is None:
        if to == "builder":
            raise BotError("No boat found: the Builder Base is not unlocked on this account yet "
                           "(it needs Town Hall 4+ and the boat repaired)")
        raise BotError("Could not find the boat back to the home village")
    bot.tap_match(boat, jitter=3)
    end = time.monotonic() + 25
    while time.monotonic() < end:
        control.sleep(1.0)
        if where(bot) == to:
            log.info("Now in the %s village", "Builder Base" if to == "builder" else "home")
            return True
        f = bot.shot()
        m = vision.templates.has("bb/star_bonus_okay") and vision.find(f, "bb/star_bonus_okay")
        if m:
            bot.tap_match(m)
    raise BotError("The boat did not sail (is the boat repaired on this account?)")


def _status_once(bot):
    f = bot.shot()
    return {
        "gold": vision.digits.read(f, bot.layout.region("bb.gold")),
        "elixir": vision.digits.read(f, bot.layout.region("bb.elixir")),
        "stars": vision.digits.read_fraction(f, bot.layout.region("bb.stars")),
    }


def status(bot, settle=3.0):
    """{'gold', 'elixir', 'stars': (won, max) or None}. The numbers count up after a battle,
    so read until two reads 0.4 s apart agree."""
    end = time.monotonic() + settle
    prev = _status_once(bot)
    while time.monotonic() < end:
        control.sleep(0.4)
        cur = _status_once(bot)
        if cur == prev:
            return cur
        prev = cur
    return prev


def _troop_keys(frame):
    """Keys of the cards on the Builder Base troop bar: hero Q, troops 1..9 (by the hint)."""
    from .attack import card_keys, detect_slots
    slots = detect_slots(frame)
    return card_keys(frame, slots), slots


BB_UI = [(0, 0, 330, 110), (1600, 0, 320, 110), (820, 0, 290, 100), (0, 760, 480, 150),
         (1640, 640, 280, 270), (0, 905, 1920, 175)]          # names, timer, buttons, troop bar


def _ui(h, w):
    m = np.zeros((h, w), np.uint8)
    for x, y, bw, bh in BB_UI:
        rx, ry, rw, rh = space.region(x, y, bw, bh)
        m[max(0, ry):ry + rh, max(0, rx):rx + rw] = 255
    return m


def red_line(frame):
    """The red no-deploy boundary drawn around a Builder Base before the battle starts."""
    b, g, r = (frame[:, :, i].astype(np.int16) for i in range(3))
    m = ((r >= 100) & (r <= 175) & (r - g >= 40) & (r - b >= 45) & (g < 115) & (b < 105)).astype(np.uint8) * 255
    m &= cv2.bitwise_not(_ui(*m.shape))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if (w * w + h * h) ** 0.5 >= 40 and a / max(1, w * h) < 0.35:   # long and thin
            keep[lab == i] = 255
    return keep


def _base_outline(frame):
    """Hull of the base for stage 2 (no red line): learn the ground colours from the edges of
    the play area and keep what is not ground near the middle."""
    h, w = frame.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    ui = _ui(h, w)
    x0, y0, x1, y1 = space.point(260, 120)[0], 120, space.point(1650, 0)[0], space.point(0, 880)[1]
    band = np.zeros((h, w), bool)
    band[y0:y1, x0:x1] = True
    inner = np.zeros((h, w), bool)
    inner[y0 + 130:y1 - 130, x0 + 220:x1 - 220] = True
    samples = lab[band & ~inner & (ui == 0)][::5]
    if len(samples) < 500:
        return None
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(samples, 5, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=5)
    ground = centers[counts > 0.1 * len(samples)]
    dist = np.min(np.stack([np.linalg.norm(lab - c, axis=2) for c in ground]), axis=0)
    m = ((dist > 18) & band & (ui == 0)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8))
    n, lab_, st, cents = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None
    cx, cy = w / 2, (y0 + y1) / 2
    best = min(range(1, n), key=lambda i: (st[i, cv2.CC_STAT_AREA] < 3000, np.hypot(cents[i][0] - cx, cents[i][1] - cy)))
    pts = cv2.findNonZero(((lab_ == best) * 255).astype(np.uint8))
    return cv2.convexHull(pts) if pts is not None else None


def deploy_spots(frame):
    """Spots just outside the base, best first: outside the red line (stage 1) or outside the
    building cluster (stage 2). Each next spot is a bit further out, for retries."""
    line = red_line(frame)
    pts = cv2.findNonZero(line)
    if pts is not None and len(pts) >= 1500:
        hull, gap = cv2.convexHull(pts), 30
    else:
        hull, gap = _base_outline(frame), 90
    if hull is None:
        return [space.center(330, 540), space.center(250, 540)]
    lx, ly = hull[hull[:, :, 0].argmin()][0]           # left corner of the base
    return [(int(lx - gap - 35 * i), int(ly)) for i in range(4)]


def _drop_all(bot, spots):
    """Drop every available unit at the first spot that works (moving out if a tap does nothing)."""
    from .attack import _card, detect_slots
    f = bot.shot()
    keys, slots = _troop_keys(f)
    order = [k for k in ["q"] + [str(i) for i in range(1, 10)] if k in keys]
    spot_i, dropped = 0, 0
    for k in order:
        cx = keys[k]
        for _ in range(len(spots)):
            before = _card(bot.shot(), cx)
            bot.key(k)
            control.sleep(0.12)
            bot.tap(*spots[spot_i], jitter=6)
            control.sleep(0.35)
            if np.abs(_card(bot.shot(), cx) - before).mean() > 8:
                dropped += 1
                break
            spot_i = min(spot_i + 1, len(spots) - 1)        # nothing happened: step further out
    if not order:                                     # no hints read: tap every card instead
        for cx in detect_slots(f):
            bot.tap(cx, space.point(0, 1000)[1], jitter=3)
            control.sleep(0.12)
            bot.tap(*spots[-1], jitter=6)
            dropped += 1
    return dropped


def attack(bot):
    """One Builder Base attack (both stages). Returns the stars earned (0-6) or None."""
    if not go_home_bb(bot, 20):
        raise BotError("Not in the Builder Base")
    before = status(bot)
    bot.tap_point("bb.attack")
    if not bot.tap_template("bb/find_now", timeout=6, after=0.5):
        raise BotError("Builder Base attack menu did not open")
    if not bot.wait_any(["bb/battle_starts", "bb/end_battle"], 40)[0]:
        raise BotError("Builder Base battle did not start")
    control.sleep(0.6)
    stage_seen = 0
    end = time.monotonic() + 7 * 60
    while time.monotonic() < end:
        f = bot.shot()
        if vision.templates.has("bb/return_home") and vision.find(f, "bb/return_home"):
            break
        stage_start = vision.find(f, "bb/battle_starts") is not None
        if stage_start and stage_seen < 2:
            stage_seen += 1
            n = _drop_all(bot, deploy_spots(f))
            log.info("Builder Base stage %d: %d unit(s) deployed", stage_seen, n)
            control.sleep(2.0)
            continue
        control.sleep(1.5)
    bot.tap_template("bb/return_home", timeout=5, after=1.0)
    go_home_bb(bot, 30)
    control.sleep(0.8)
    after = status(bot)
    gold = (after.get("gold") or 0) - (before.get("gold") or 0) if after.get("gold") and before.get("gold") else None
    stars = None
    if before.get("stars") and after.get("stars"):
        b, a = before["stars"][0], after["stars"][0]
        stars = (a - b) if a >= b else (before["stars"][1] - b + a)   # wrapped after a Star Bonus
    log.info("Builder Base attack done: %s star(s) toward the bonus (now %s), gold %s",
             "?" if stars is None else stars, "{}/{}".format(*after["stars"]) if after.get("stars") else "?",
             f"{gold:+,}" if gold is not None else "?")
    bot.stats["bb_attacks"] = bot.stats.get("bb_attacks", 0) + 1
    return stars


def bonus_done(bot, st=None):
    """True when today's Star Bonus is complete (e.g. 8/8)."""
    st = st or status(bot)
    s = st.get("stars")
    return bool(s and s[0] >= s[1])


def full(bot, account, st):
    """Builder Base storages full (measured capacity minus margin)?"""
    from .storage import BB_BARS, estimate
    caps = account.setdefault("bb_capacity", {})
    f = bot.shot()
    flags = []
    for res in ("gold", "elixir"):
        amount = st.get(res)
        cap, _ = estimate(f, res, amount, bars=BB_BARS)
        if cap:
            caps[res] = max(cap, caps.get(res, 0)) if abs(cap - caps.get(res, cap)) / cap < 0.05 else cap
        if caps.get(res) and amount is not None:
            margin = bot.settings.get("builder", {}).get("full_margin", 50000)
            flags.append(amount >= caps[res] - margin)
    return bool(flags) and all(flags)


def upgrade(bot, max_count=1):
    """Builder Base upgrades with the gear-up priority. Returns the number started."""
    from . import village
    cfg = bot.settings.get("builder", {})
    started = 0
    for _ in range(max_count):
        if not go_home_bb(bot, 15):
            break
        counter = vision.digits.read_fraction(bot.shot(), bot.layout.region("bb.builders"))
        if not counter or counter[0] <= 0:
            log.info("Builder Base: no free builder")
            break
        bot.tap_point("bb.builders_menu")
        bot.sleep(1.0)
        rows = village.parse_menu(bot.shot(), bot.layout.point("bb.builders_menu")[0])
        st = status(bot)
        res_now = {"gold": st.get("gold"), "elixir": st.get("elixir")}
        skip = cfg.get("upgrade_skip", [])
        prio = GEAR_UP_ORDER if cfg.get("gear_up", True) else []

        def rank(r):
            name = r["name"].lower().replace(" ", "")
            for i, p in enumerate(prio):
                if p.lower().replace(" ", "") in name:
                    return i
            return len(prio) + (0 if r["section"] == "suggested" else 1)

        pick = None
        for r in sorted(rows, key=rank):
            have = res_now.get(r["res"])
            if r["res"] not in ("gold", "elixir") or r["red"] or have is None or r["cost"] > have:
                continue
            if village._skipped(r["name"], skip):
                continue
            pick = dict(r, have=have)
            break
        if not pick:
            log.info("Builder Base: no affordable upgrade (%d listed)", len(rows))
            village.close_menu(bot)
            break
        bot.tap(*pick["tap"], jitter=2)
        bot.sleep(1.2)
        up = bot.wait("building/upgrade_button", 4)
        if not up:
            village.close_menu(bot)
            break
        bot.tap_match(up)
        bot.sleep(1.2)
        ok = village._confirm(bot, pick, "builders", home=go_home_bb)
        village.close_menu(bot)
        if not ok:
            break
        started += 1
        bot.stats["upgrades"] = bot.stats.get("upgrades", 0) + 1
    return started


def collect(bot):
    """Tap the Builder Base collector bubbles (gold mine, elixir collector, gem mine is left alone)."""
    f = bot.shot()
    full = (0, 0, f.shape[1], f.shape[0])
    for key in ("bb/bubble_gold", "bb/bubble_elixir"):
        if vision.templates.has(key):
            ms = vision.find_all(f, key, region=full)
            if ms:
                bot.tap_match(ms[0], jitter=2)
                bot.sleep(0.6)

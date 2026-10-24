"""Builder Base (the night village): travel there and back, attack, collect and upgrade.

Builder Base battles have two stages: destroy the first base (stage 1), then the surviving
troops plus a new one attack a second, smaller base (stage 2). Each attack can earn up to
6 stars; the "Star Bonus" (the 4/8 counter on the Attack button) pays extra loot until the
daily star bonus is used up. There is no "Next": every attack is one random base.

Builder Base upgrades and Star Laboratory research are in actions/upgrades.py and
actions/research.py (the "Builder Base upgrade" / "research" steps of the window's options).
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

BB_MARK = "bb/trophy_hammer"     # the hammer by the trophy count: only shown in the Builder Base
TROOPS_BOX = (400, 435, 650, 60)   # the "Your troops" line in the Start Attack window


class NoArmy(BotError):
    """The Builder Base army is empty ("Train an army before attacking!")."""


def is_builder_base(frame):
    return vision.find(frame, BB_MARK) is not None


def _tap_attack_button(bot):
    frame = bot.shot()
    if not vision.find(frame, BB_MARK):
        raise BotError("Not in the Builder Base")
    if not vision.templates.has("bb/attack_button"):
        raise BotError("Builder Base battle icon template is missing")
    m = vision.find(frame, "bb/attack_button", region=(0, 0, frame.shape[1], frame.shape[0]))
    if not m:
        raise BotError("Builder Base battle icon not found on screen")
    bot.tap_match(m)


def where(bot):
    """'main', 'builder' or None (unknown)."""
    f = bot.shot()
    if vision.find(f, BB_MARK):
        return "builder"
    if detect(f) == "home":
        return "main"
    return None


def go_home_bb(bot, timeout=60.0):
    """Get back to the Builder Base village from any of its screens."""
    from ..states import cancel_placement
    cancel_placement(bot)                            # a building left waiting to be placed
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = bot.shot()
        if vision.find(f, BB_MARK):
            return True
        for key, tap in (("bb/star_bonus_okay", None), ("bb/return_home", None), ("bb/menu_close", None),
                         ("upgrade/close", None), ("lab/close", None), ("shop/close", None)):
            if vision.templates.has(key):
                m = vision.find(f, key)
                if m:
                    bot.tap_match(m)
                    break
        else:
            st = detect(f)
            if st == "home":
                return False                         # we are in the main village
            if st == "exit_dialog":
                bot.tap_point("dialog.cancel")       # never quit the game
                control.sleep(0.6)
                continue
            bot.tap_point("bb.safe", jitter=5)
        control.sleep(0.6)
    return False


def _find_boat(bot, here):
    """Find the boat of the current village. Its little ship icon (in a bubble above the boat)
    is the same in every scenery and both villages, only its size changes with the zoom, so
    it is searched at several sizes. If it is not on screen, pan in a fixed pattern."""
    pans = [None, ((1300, 300), (600, 800)), ((1300, 300), (600, 800)), ((600, 800), (1300, 300)),
            ((600, 800), (1300, 300)), ((600, 800), (1300, 300)), ((700, 300), (1300, 800)),
            ((1300, 800), (700, 300)), ((1300, 800), (700, 300))]
    for pan in pans:
        control.checkpoint()
        if detect(bot.shot()) not in ("home", "bb_home"):
            return None                              # not on a village (a popup opened): never swipe over it
        if pan:
            bot.swipe(space.center(*pan[0]), space.center(*pan[1]), 600)
            control.sleep(0.6)
        m, sc = vision.find_scaled(bot.shot(), "boat/icon")
        if m:
            return m
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
    boat = None
    for attempt in range(2):
        bot.tap_point("home.safe" if here == "main" else "bb.safe", jitter=5)    # deselect anything first
        bot.device.zoom_out()
        control.sleep(0.5)
        boat = _find_boat(bot, here)
        if boat is not None:
            break
        # e.g. right after building something the view can be moved: clear the screen and look again
        (go_home(bot, 20) if here == "main" else go_home_bb(bot, 20))
        control.sleep(1.0)
    if boat is None:
        if to == "builder":
            raise BotError("No boat found: the Builder Base is not unlocked on this account yet "
                           "(it needs Town Hall 4+ and the boat repaired)")
        raise BotError("Could not find the boat back to the home village")
    bot.tap_match(boat, jitter=3)
    start = time.monotonic()
    retried = False
    while time.monotonic() - start < 60:              # loading the other village can take a while
        control.sleep(1.0)
        now = where(bot)
        if now == to:
            log.info("Now in the %s village", "Builder Base" if to == "builder" else "home")
            return True
        if now == here and not retried and time.monotonic() - start > 20:
            boat = _find_boat(bot, here)                # first tap the bubble; retry on the hull only if needed
            if boat:
                scale = boat.box[2] / vision.templates.image("boat/icon").shape[1]
                y = int(boat.y + 80 * scale)
                if y > space.point(0, 930)[1]:
                    y = int(boat.y + 45 * scale)
                bot.tap(boat.x, y, jitter=3)
            retried = True
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
    _tap_attack_button(bot)
    if not bot.wait("bb/find_now", 6):
        raise BotError("Builder Base attack menu did not open")
    bot.sleep(0.3)
    text, _ = vision.text_reader.read_line(bot.shot(), space.region(*TROOPS_BOX))
    if "train" in text.lower() and "army" in text.lower():
        go_home_bb(bot, 15)
        raise NoArmy("the Builder Base army is empty (\"Train an army before attacking!\")")
    if not bot.tap_template("bb/find_now", timeout=3, after=0.5):
        raise BotError("Builder Base attack menu did not open")
    if not bot.wait_any(["bb/battle_starts", "bb/end_battle"], 40)[0]:
        raise BotError("Builder Base battle did not start")
    control.sleep(0.6)
    stage_seen = 0
    started = time.monotonic()
    limit = bot.settings.get("builder", {}).get("battle_seconds", 60)
    ended = False
    end = time.monotonic() + 7 * 60
    next_end = 0.0
    while time.monotonic() < end:
        f = bot.shot()
        if vision.templates.has("bb/return_home") and vision.find(f, "bb/return_home"):
            break
        if limit and time.monotonic() - started > limit:
            # each attack lasts at most `limit` seconds in all: ending stage 1 can lead into
            # stage 2, so End Battle is tapped again until the results show (no stage 2 troops)
            if time.monotonic() >= next_end:
                if _end_battle(bot, f) and not ended:
                    ended = True
                    log.info("Builder Base battle ended after %d s", time.monotonic() - started)
                next_end = time.monotonic() + 2.5
            control.sleep(0.6)
            continue
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


def _end_battle(bot, frame):
    """Surrender / End Battle, then Okay. Returns True if the battle was ended."""
    for key in ("bb/surrender", "bb/end_battle"):
        m = vision.templates.has(key) and vision.find(frame, key)
        if m:
            bot.tap_match(m)
            bot.tap_template("battle/confirm_okay", timeout=4, after=1.0)
            return True
    return False


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


def attacks(bot, account):
    """Builder Base attacks on this account (you must be in its Builder Base): until the Star Bonus
    is done (or on, see the settings), the storages are full or stop growing, or the attack limit."""
    cfg = bot.settings.get("builder", {})
    name = account.get("name", "?")
    bot.status(action="Builder Base attack")
    if cfg.get("army", "auto") != "keep" and account.get("_bb_army") != cfg.get("army", "auto"):
        try:
            unit = set_army(bot, cfg.get("army", "auto"))
        except BotError as e:
            log.warning("%s Builder Base army setup failed: %s", name, e)
            bot.save_error("bb-army")
            return 0
        if not unit:
            log.warning("%s Builder Base army setup failed; no attacks this visit", name)
            return 0
        account["_bb_army"] = cfg.get("army", "auto")      # once per visit
    attacks, stuck, prev = 0, 0, None
    max_attacks = cfg.get("max_attacks", 20)
    while True:
        control.checkpoint()
        st = status(bot)
        bot.status(account=name, action="Builder Base",
                   resources={"gold": st.get("gold"), "elixir": st.get("elixir"), "dark": None})
        if full(bot, account, st):
            log.info("%s Builder Base: storages full", name)
            break
        if bonus_done(bot, st) and not cfg.get("after_bonus", False):
            log.info("%s Builder Base: Star Bonus complete (%s/%s)", name, *st["stars"])
            break
        if max_attacks and attacks >= max_attacks:
            log.info("%s Builder Base: attack limit (%d) reached", name, max_attacks)
            break
        if prev is not None and bonus_done(bot, st):
            grew = any((st.get(r) or 0) > (prev.get(r) or 0) for r in ("gold", "elixir"))
            stuck = 0 if grew else stuck + 1
            if stuck >= cfg.get("stuck_attacks", 3):
                log.info("%s Builder Base: storages stopped growing: treating as full", name)
                break
        prev = st
        try:
            attack(bot)
            attacks += 1
        except NoArmy as e:
            if account.get("_bb_army_retry"):
                log.warning("%s Builder Base: %s - no attacks this visit", name, e)
                break
            account["_bb_army_retry"] = True
            log.info("%s Builder Base: %s - choosing the army again", name, e)
            try:
                unit = set_army(bot, cfg.get("army", "auto") if cfg.get("army", "auto") != "keep" else "auto")
            except BotError as setup_error:
                log.warning("%s Builder Base army setup failed: %s", name, setup_error)
                bot.save_error("bb-army")
                break
            if not unit:
                log.warning("%s Builder Base: no army - no attacks this visit", name)
                break
        except BotError as e:
            log.warning("%s Builder Base attack: %s", name, e)
            bot.save_error("bb-attack")
            break
    return attacks


# --- Builder Base army ------------------------------------------------------------------------

BB_UNITS = ["pekka", "night_witch", "archer", "barbarian", "boxer_giant", "bomber", "cannon_cart", "drop_ship",
            "hog_glider", "beta_minion", "baby_dragon", "electrofire_wizard"]
AUTO_ORDER = ["pekka", "archer", "barbarian"]          # "Auto": P.E.K.K.A when unlocked, else Sneaky Archer
SLOTS_REGION = (310, 330, 1300, 190)                    # starting + reinforcement slots (4-6 + 0-2)
LIST_REGION = (320, 640, 1300, 270)                     # the unit list


def _unit(frame, name, region, unlocked=False):
    """The unit's icon; unlocked=True: only if it is in colour (a locked unit is drawn grey)."""
    key = f"bb/unit_{name}"
    m = vision.find(frame, key, region=space.region(*region)) if vision.templates.has(key) else None
    if m and unlocked:
        x, y, w, h = m.box
        if cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)[:, :, 1].mean() < 40:
            return None
    return m


def set_army(bot, choice):
    """Fill the Builder Base army with one unit type (plus the Battle Machine).
    choice: "keep", "auto" (P.E.K.K.A if unlocked, else Sneaky Archer) or a unit name.
    Returns the unit used, or None if the army was left as it was."""
    if not choice or choice == "keep":
        return None
    wanted = AUTO_ORDER if choice == "auto" else [choice] + [u for u in AUTO_ORDER if u != choice]
    # since the 2026-10 UI: Battle -> "Edit Army" in the Start Attack window -> Choose Army
    _tap_attack_button(bot)
    if not bot.wait("bb/find_now", 5, interval=0.25):
        raise BotError("Builder Base attack menu did not open")
    bot.tap_point("bb.edit_army")
    if not bot.wait("bb/army_title", 5, interval=0.25):
        bot.tap_template("bb/menu_close", timeout=2, after=0.2)
        raise BotError("Builder Base army screen did not open")
    try:
        bot.sleep(0.4)
        f = bot.shot()
        # already this army (first slot and a reinforcement slot show the wanted unit)? then leave it
        u = wanted[0]                                   # only the first choice counts as "already set"
        if _unit(f, u, (310, 340, 300, 170)) and _unit(f, u, (1300, 340, 280, 170)):
            log.info("Builder Base army is already %s", u.replace("_", " "))
            return u
        bot.tap_point("bb.army_clear")                  # empty the army (no confirmation)
        bot.sleep(0.6)
        f = bot.shot()
        unit = next((u for u in wanted if _unit(f, u, LIST_REGION, unlocked=True)), None)
        if unit is None:
            log.info("None of %s unlocked on this Builder Base; using what is available", ", ".join(wanted))
            unit = next((u for u in BB_UNITS if _unit(f, u, LIST_REGION, unlocked=True)), None)
        hero = next((h for h in ("battle_machine", "battle_copter") if _unit(f, h, LIST_REGION, unlocked=True)), None)
        if hero:
            bot.tap_match(_unit(f, hero, LIST_REGION), jitter=2)
            bot.sleep(0.4)
        ok = None
        for _ in range(2):                              # a second go if the slots stayed empty
            if not unit:
                break
            m = _unit(bot.shot(), unit, LIST_REGION)
            for _ in range(8):                          # every free slot (6 + 2 at the top Builder Hall)
                control.checkpoint()
                bot.tap_match(m, jitter=2)
                bot.sleep(0.3)
            bot.sleep(0.4)
            ok = _unit(bot.shot(), unit, SLOTS_REGION)
            if ok:
                break
        if ok:
            log.info("Builder Base army: %s%s", "Battle Machine + " if hero else "", unit.replace("_", " "))
            return unit
        log.warning("Builder Base army could not be filled (%s)", unit.replace("_", " ") if unit else "no unit unlocked")
        return None
    finally:
        bot.tap_point("bb.army_close")
        bot.sleep(0.5)
        go_home_bb(bot, 15)

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

BB_MARK = "bb/trophy_hammer"     # the hammer by the trophy count: only shown in the Builder Base

# Builder-Hall-first priority: the Builder Hall, then NEW buildings (unlocks), then the
# Cannon / Archer Tower / Mortar line (needed for Gear Up), then the rest (part of a name is enough).
GEAR_UP_ORDER = ["Builder Hall", "__new__", "Cannon", "Archer Tower", "Mortar", "Double Cannon", "Multi Mortar",
                 "Crusher", "Air Bombs", "Firecrackers", "Guard Post", "Roaster", "Giant Cannon",
                 "Mega Tesla", "Lava Launcher", "Hidden Tesla", "Builder Barracks", "Elixir Storage",
                 "Gold Storage", "Clock Tower", "Star Laboratory"]


def is_builder_base(frame):
    return vision.find(frame, BB_MARK) is not None


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
            return type(m)(m.x, int(m.y + 80 * sc), m.score, m.box)    # the boat is under its icon
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
    retapped = False
    while time.monotonic() - start < 60:              # loading the other village can take a while
        control.sleep(1.0)
        now = where(bot)
        if now == to:
            log.info("Now in the %s village", "Builder Base" if to == "builder" else "home")
            return True
        if now == here and not retapped and time.monotonic() - start > 8:
            boat = _find_boat(bot, here)                # the tap did not register: tap the boat again
            if boat:
                bot.tap_match(boat, jitter=3)
            retapped = True
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
    started = time.monotonic()
    limit = bot.settings.get("builder", {}).get("battle_seconds", 60)
    ended = False
    end = time.monotonic() + 7 * 60
    while time.monotonic() < end:
        f = bot.shot()
        if vision.templates.has("bb/return_home") and vision.find(f, "bb/return_home"):
            break
        if limit and not ended and time.monotonic() - started > limit:
            ended = _end_battle(bot, f)                # each attack lasts at most `limit` seconds
            if ended:
                log.info("Builder Base battle ended after %d s", limit)
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
                if (p == "__new__" and r.get("new")) or (p != "__new__" and p.lower().replace(" ", "") in name):
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
            village.close_menu(bot, "bb.safe")
            break
        bot.tap(*pick["tap"], jitter=2)
        bot.sleep(1.2)
        up = bot.wait("building/upgrade_button", 4)
        if not up:
            village.close_menu(bot, "bb.safe")
            break
        bot.tap_match(up)
        bot.sleep(1.2)
        ok = village._confirm(bot, pick, "builders", home=go_home_bb)
        village.close_menu(bot, "bb.safe")
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


def research(bot):
    """Start one Star Laboratory research if it is free (Builder Base)."""
    from . import village
    if not go_home_bb(bot, 15):
        return False
    counter = vision.digits.read_fraction(bot.shot(), bot.layout.region("bb.lab"))
    if not counter or counter[0] <= 0:
        log.info("Builder Base: Star Laboratory busy")
        return False
    bot.tap_point("bb.lab_menu")
    bot.sleep(1.0)
    rows = village.parse_menu(bot.shot(), bot.layout.point("bb.lab_menu")[0])
    st = status(bot)
    skip = bot.settings.get("builder", {}).get("research_skip", [])
    for r in rows:
        have = st.get(r["res"])
        if r["res"] in ("gold", "elixir") and not r["red"] and have and r["cost"] <= have \
                and not village._skipped(r["name"], skip):
            bot.tap(*r["tap"], jitter=2)
            bot.sleep(1.5)
            ok = village._confirm(bot, dict(r, have=have), "lab", home=go_home_bb)
            go_home_bb(bot, 20)
            if ok:
                bot.stats["research"] = bot.stats.get("research", 0) + 1
            return ok
    log.info("Builder Base: no affordable research (%d listed)", len(rows))
    village.close_menu(bot, "bb.safe")
    return False


def session(bot, account, plan=False):
    """A Builder Base visit for this account: sail there, collect, attack until the Star Bonus is
    done (and optionally keep going), stop early if storages are full or stop growing, upgrade,
    research, sail back. Returns False if the account has no Builder Base.
    plan=True ("Builder Base upgrades" mode): the Builder Base upgrade plan (upgrades.py) runs
    before attacking, if there are resources already, and again after attacking."""
    from . import upgrades
    cfg = bot.settings.get("builder", {})
    name = account.get("name", "?")
    try:
        travel(bot, "builder")
    except BotError as e:
        log.info("%s: %s. Skipping the Builder Base.", name, e)
        go_home(bot)
        return False
    bot.status(action="Builder Base")
    if cfg.get("collect", True):
        collect(bot)
    if plan:
        upgrades.run_bb(bot, account, "before attacking")
    if cfg.get("army", "auto") != "keep" and account.get("_bb_army") != cfg.get("army", "auto"):
        set_army(bot, cfg.get("army", "auto"))
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
        except BotError as e:
            log.warning("%s Builder Base attack: %s", name, e)
            bot.save_error("bb-attack")
            if not go_home_bb(bot, 45):
                break
    if plan:
        upgrades.run_bb(bot, account, "after attacking")
    elif cfg.get("upgrade", False):
        upgrade(bot, cfg.get("max_upgrades", 1))
    if cfg.get("research", False):
        research(bot)
    try:
        travel(bot, "main")
    except BotError as e:
        log.warning("%s: %s", name, e)
    return True


# --- Builder Base army ------------------------------------------------------------------------

BB_UNITS = ["pekka", "night_witch", "archer", "barbarian", "boxer_giant", "bomber", "cannon_cart", "drop_ship",
            "hog_glider", "beta_minion", "baby_dragon", "electrofire_wizard"]
AUTO_ORDER = ["pekka", "archer", "barbarian"]          # "Auto": P.E.K.K.A when unlocked, else Sneaky Archer
SLOTS_REGION = (455, 340, 1120, 170)                    # starting + reinforcement slots
LIST_REGION = (320, 640, 1300, 270)                     # the unit list


def _unit(frame, name, region):
    key = f"bb/unit_{name}"
    return vision.find(frame, key, region=space.region(*region)) if vision.templates.has(key) else None


def set_army(bot, choice):
    """Fill the Builder Base army with one unit type (plus the Battle Machine).
    choice: "keep", "auto" (P.E.K.K.A if unlocked, else Sneaky Archer) or a unit name.
    Returns the unit used, or None if the army was left as it was."""
    if not choice or choice == "keep":
        return None
    wanted = AUTO_ORDER if choice == "auto" else [choice] + [u for u in AUTO_ORDER if u != choice]
    bot.tap_point("bb.army")
    if not bot.wait("bb/army_title", 5, interval=0.25):
        log.warning("Builder Base army screen did not open")
        go_home_bb(bot, 15)
        return None
    try:
        bot.sleep(0.4)
        f = bot.shot()
        # already this army (first slot and a reinforcement slot show the wanted unit)? then leave it
        u = wanted[0]                                   # only the first choice counts as "already set"
        if _unit(f, u, (455, 340, 140, 170)) and _unit(f, u, (1300, 340, 280, 170)):
            log.info("Builder Base army is already %s", u.replace("_", " "))
            return u
        bot.tap_point("bb.army_clear")                  # empty the army (no confirmation)
        bot.sleep(0.6)
        f = bot.shot()
        unit = next((u for u in wanted if _unit(f, u, LIST_REGION)), None)   # in colour = unlocked
        if unit is None:
            log.info("None of %s unlocked on this Builder Base; using what is available", ", ".join(wanted))
            unit = next((u for u in BB_UNITS if _unit(f, u, LIST_REGION)), None)
        hero = _unit(f, "battle_machine", LIST_REGION) or _unit(f, "battle_copter", LIST_REGION)
        if hero:
            bot.tap_match(hero, jitter=2)
            bot.sleep(0.4)
        if unit:
            m = _unit(bot.shot(), unit, LIST_REGION)
            for _ in range(8):                          # every free slot (6 + 2 at the top Builder Hall)
                control.checkpoint()
                bot.tap_match(m, jitter=2)
                bot.sleep(0.3)
        bot.sleep(0.4)
        ok = unit and _unit(bot.shot(), unit, SLOTS_REGION)
        log.info("Builder Base army: Battle Machine + %s%s", (unit or "?").replace("_", " "),
                 "" if ok else " (could not confirm)")
        return unit
    finally:
        bot.tap_point("bb.army_close")
        bot.sleep(0.5)
        go_home_bb(bot, 15)

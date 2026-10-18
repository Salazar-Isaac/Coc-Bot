"""Clan Capital Raid Weekend: every account uses its raid attacks, quickly.

Raid Weekend runs from Friday 07:00 to Monday 07:00 UTC (12:30 India time). An account has 5 raid
attacks (6 with the bonus); how many are left shows as a red badge ("5 ⚔") over the Clan Capital
airship by the river. The quick way, no army to choose and no troops placed:
  airship -> (raid summary: Next Raid / own Capital: Raid Map) -> the raid map -> a district ->
  Attack -> "Attack Now?" Attack -> the battle starts -> close the game and open it again.
The attack is over and counted when the game is back (checked: the badge goes 5 -> 4). Again until
the badge is gone (no raid attack left).
"""

import datetime as dt
import logging
import re
import time

import cv2
import numpy as np

from .. import config, states
from ..core import vision
from ..core.context import BotError
from ..core.control import control
from ..core.space import space
from ..states import go_home

log = logging.getLogger("bot")

UTC = dt.timezone.utc
START = (4, 7)                     # Friday (weekday 4) 07:00 UTC
LENGTH = dt.timedelta(days=3)      # to Monday 07:00 UTC

# the raid map is always drawn the same way: its districts, tried in this order (Capital Peak opens last)
DISTRICTS = [("Barbarian Camp", (1135, 560)), ("Wizard Valley", (925, 660)), ("Dragon Cliffs", (1290, 775)),
             ("Balloon Lagoon", (745, 820)), ("Builder's Workshop", (1065, 860)), ("Golem Quarry", (550, 955)),
             ("Goblin Mines", (1215, 990)), ("Skeleton Park", (870, 1000)), ("Capital Peak", (920, 390))]
BAR_ATTACK = (1045, 960, 120, 35)  # the district bar's Attack button (red = can attack, grey = no attack left)
NOTICE = (470, 220, 990, 120)      # the game's red notice at the top of the raid map


def window(now=None):
    """(active, start, end) of the current Raid Weekend, or of the next one when none is on."""
    now = now or dt.datetime.now(UTC)
    day, hour = START
    start = (now - dt.timedelta(days=(now.weekday() - day) % 7)).replace(hour=hour, minute=0, second=0,
                                                                         microsecond=0)
    if start > now:
        start -= dt.timedelta(days=7)
    end = start + LENGTH
    if now < end:
        return True, start, end
    start += dt.timedelta(days=7)
    return False, start, start + LENGTH


def weekend_key(start):
    return start.strftime("%Y-%m-%d")


def _done(bot):
    """{account: "done" | n attacks used} of the current Raid Weekend (kept in the bot's state)."""
    active, start, _ = window()
    if bot.state is None:
        return {}
    slot = bot.state.setdefault("raid", {})
    for k in [k for k in slot if k != weekend_key(start)]:
        slot.pop(k)                                      # an older weekend
    return slot.setdefault(weekend_key(start), {})


def pending(bot, names):
    """The accounts that still have raid attacks this weekend (as far as the bot knows)."""
    done = _done(bot)
    return [n for n in names if done.get(n) != "done"]


# ----------------------------------------------------------------------------- the village
def _badges(frame):
    """Red badges like the airship's "5 ⚔" (a rounded red box): [(x, y, w, h)]."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = (((hsv[:, :, 0] < 7) | (hsv[:, :, 0] > 173)) & (hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 140)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if space.s(48) <= w <= space.s(80) and space.s(35) <= h <= space.s(56) and a / (w * h) > 0.6 \
                and space.s(200) < y < space.s(1000) and space.s(150) < x < space.s(1500):
            out.append((int(x), int(y), int(w), int(h)))
    return out


def find_airship(bot):
    """Zoom out and bring the river into view: the airship's badge (x, y, w, h) and the raid attacks
    left it shows, or (None, 0) when there is no badge (no raid attack left). The badge is found by its
    colour and shape (the same in every village scenery - the airship itself looks different in each),
    looked for twice before deciding there is none."""
    found = []
    for attempt in range(2):
        go_home(bot, 30)
        bot.device.zoom_out()
        control.sleep(0.6)
        bot.swipe(space.center(900, 800), space.center(1100, 350 + 120 * attempt), 700)
        control.sleep(1.2)
        f = bot.shot()
        found = _badges(f)
        if found:
            break
    if not found:
        return None, 0
    x, y, w, h = max(found, key=lambda b: b[1])          # the lowest one: the airship is by the river
    text, conf = vision.text_reader.read_line(f, (x + space.s(4), y + space.s(2), w // 2, h - space.s(6)))
    digits = re.sub(r"\D", "", text.replace("S", "5").replace("s", "5").replace("l", "1").replace("O", "0"))
    left = int(digits) if digits and int(digits) <= 6 else 1
    return (x, y, w, h), left


# ----------------------------------------------------------------------------- the Capital
def _wait_any(bot, keys, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = bot.shot()
        for k in keys:
            if vision.templates.has(k) and vision.find(f, k):
                return k
        control.sleep(0.5)
    return None


def _red(frame, box):
    x, y, w, h = space.region(*box)
    p = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    return float((((p[:, 0] < 8) | (p[:, 0] > 172)) & (p[:, 1] > 120) & (p[:, 2] > 120)).mean()) > 0.3


def open_raid_map(bot, badge):
    """Tap the airship (under its badge) and get to the raid map. True when it is on screen."""
    x, y, w, h = badge
    bot.tap(x + w // 2, y + h + space.s(75), jitter=3)
    key = _wait_any(bot, ["raid/attacking_title", "raid/next_raid", "raid/capital_title"], 25)
    if key == "raid/next_raid":                          # the summary of the last raid: Next Raid
        bot.tap_template("raid/next_raid", timeout=3)
        key = _wait_any(bot, ["raid/attacking_title"], 15)
    elif key == "raid/capital_title":                    # the clan's own Capital: Raid Map
        bot.tap_template("raid/raid_map", timeout=3)
        key = _wait_any(bot, ["raid/attacking_title", "raid/next_raid"], 15)
        if key == "raid/next_raid":
            bot.tap_template("raid/next_raid", timeout=3)
            key = _wait_any(bot, ["raid/attacking_title"], 15)
    return key == "raid/attacking_title"


def _not_allowed(frame):
    """The game's notice "Only members who were in the clan before the Raid Weekend began can attack!"
    (an account that joined the clan during the weekend; Elders and up can attack anyway)."""
    x, y, w, h = space.region(*NOTICE)
    p = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    if float((((p[:, 0] < 8) | (p[:, 0] > 172)) & (p[:, 1] > 170) & (p[:, 2] > 170)).mean()) < 0.02:
        return False
    text = re.sub(r"[^a-z]", "", " ".join(t for t, _, _ in vision.text_reader.read(frame, (x, y, w, h))).lower())
    return "before" in text and "raid" in text or "onlymembers" in text


def _wait_battle(bot, timeout):
    """Wait for the raid battle; returns "battle", "not_allowed" or None."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = bot.shot()
        if vision.find(f, "raid/battle_starts") or vision.find(f, "battle/surrender"):
            return "battle"
        if _not_allowed(f):
            return "not_allowed"
        control.sleep(0.4)
    return None


def start_attack(bot):
    """On the raid map: a district that can be attacked -> Attack -> "Attack Now?" Attack. Returns
    (district, "started") once the battle has started, (None, "none") when no district can be attacked
    (no raid attack left), or (district, "failed") when the attack did not start."""
    for name, (x, y) in DISTRICTS:
        control.checkpoint()
        bot.tap(*space.center(x, y), jitter=4)
        control.sleep(1.0)
        f = bot.shot()
        if not vision.find(f, "raid/district_bar"):
            continue                                     # destroyed / locked / not on this map
        if not _red(f, BAR_ATTACK):
            log.info("Raid: %s cannot be attacked (no raid attack left, or destroyed)", name)
            bot.tap(*space.center(1650, 400), jitter=3)   # close the district bar
            control.sleep(0.6)
            continue
        x0, y0, w0, h0 = space.region(*BAR_ATTACK)
        key = None
        for _ in range(3):                               # a tap while the bar slides in is lost: again
            bot.tap(x0 + w0 // 2, y0 + h0 // 2, jitter=3)
            key = _wait_any(bot, ["raid/attack_now_title", "raid/battle_starts", "battle/surrender"], 5)
            if key:
                break
        for _ in range(3):
            if key != "raid/attack_now_title":
                break
            bot.tap_template("raid/attack_go", timeout=3)
            got = _wait_battle(bot, 8)
            if got == "not_allowed":
                return name, "not_allowed"
            key = "raid/battle_starts" if got == "battle" else _wait_any(bot, ["raid/attack_now_title"], 1)
        if key in ("raid/battle_starts", "battle/surrender"):
            return name, "started"
        log.info("Raid: the attack on %s did not start", name)
        bot.save_error("raid-no-battle")
        return name, "failed"
    return None, "none"


def restart(bot):
    """Close the game and open it again: the raid attack ends there and counts."""
    bot.device.close_game()
    end = time.monotonic() + 20
    while bot.device.is_game_running() and time.monotonic() < end:
        control.sleep(0.5)
    control.sleep(1.0)
    states.ensure_game(bot)


# ----------------------------------------------------------------------------- one account
def run(bot, account, max_attacks=6):
    """Use this account's raid attacks. Returns the number of raid attacks made."""
    active, _, end = window()
    if not active:
        return 0
    done = _done(bot)
    if done.get(account["name"]) == "done":
        return 0
    made, failed = 0, 0
    for _ in range(max_attacks + 3):
        control.checkpoint()
        badge, left = find_airship(bot)
        if badge is None:
            log.info("%s: no raid attack left this Raid Weekend", account["name"])
            done[account["name"]] = "done"
            break
        if made >= max_attacks:
            break
        log.info("%s: %d raid attack(s) left - starting one", account["name"], left)
        bot.status(account=account["name"], action=f"Raid attack {made + 1} ({left} left)")
        if not open_raid_map(bot, badge):
            log.info("%s: the Clan Capital raid did not open (a game tutorial still pending?) - skipped this "
                     "Raid Weekend", account["name"])
            bot.save_error("raid-no-map")
            done[account["name"]] = "done"             # not tried again and again this weekend
            restart(bot)
            break
        district, status = start_attack(bot)
        if status == "none":
            log.info("%s: nothing to attack on the raid map now", account["name"])
            restart(bot)
            done[account["name"]] = "done"
            break
        if status == "not_allowed":
            log.info("%s: joined the clan after this Raid Weekend began - the game lets it raid only if promoted "
                     "(Elder) or the clan is Invite Only; skipped this weekend", account["name"])
            done[account["name"]] = "done"
            restart(bot)
            break
        if status == "failed":
            restart(bot)                                 # try again (not counted as done)
            failed += 1
            if failed >= 2:
                log.info("%s: raid attacks did not start twice - looked at again later", account["name"])
                break
            continue
        log.info("%s: raid attack on %s started - restarting the game to end it", account["name"], district)
        restart(bot)
        made += 1
        bot.stats["raids"] = bot.stats.get("raids", 0) + 1
        if bot.state is not None:
            config.save_state(bot.state)
    if bot.state is not None:
        config.save_state(bot.state)
    if made:
        log.info("%s: %d raid attack(s) made", account["name"], made)
    return made


def raid_accounts(bot, accounts, state, switch, start_from=None):
    """Raid Weekend: every account that still has raid attacks uses them. switch(acc) opens an account.
    start_from: the account to begin with (then the ones after it, then the ones before it)."""
    active, _, end = window()
    if not active:
        return 0
    if start_from is not None:
        i = next((k for k, a in enumerate(accounts) if a["name"] == start_from), 0)
        accounts = accounts[i:] + accounts[:i]
    names = pending(bot, [a["name"] for a in accounts])
    if not names:
        return 0
    left = end - dt.datetime.now(UTC)
    log.info("== Raid Weekend (%dh %dm left): raid attacks on %d account(s)", left.days * 24 + left.seconds // 3600,
             left.seconds % 3600 // 60, len(names))
    total = 0
    for acc in accounts:
        if acc["name"] not in names:
            continue
        control.checkpoint()
        if not window()[0]:
            break
        if not switch(acc):
            continue
        try:
            total += run(bot, acc, (bot.settings.get("steps", {}).get("raid") or {}).get("attacks", 6))
        except BotError as e:
            log.warning("%s: raid: %s", acc["name"], e)
            restart(bot)
    log.info("== Raid Weekend: %d raid attack(s) made", total)
    return total

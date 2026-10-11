"""Which screen is the game on, and how to get back to the home village."""

import logging
import time

from .core import vision
from .core.context import BotError
from .core.control import control
from .core.space import space

log = logging.getLogger("bot")

# Order matters: overlays that leave the village buttons visible (chat, "Anyone there?") come
# first, then the village itself (the most common screen: checked early to save time; every
# other overlay dims the village buttons, so they cannot match under it), then the rest.
STATES = [
    ("shop", ["shop/close", "shop/title"]),       # the Shop (gem / money offers): only ever its X
    ("reload", ["popup/reload", "popup/try_again", "popup/anyone_there"]),
    ("donate", ["donate/window_title"]),
    ("chat", ["chat/close"]),                     # clan chat open over the village
    ("bb_home", ["bb/trophy_hammer"]),            # Builder Base village (night): before "home"
    ("home", ["home/attack_button", "home/settings_button"]),
    ("daily", ["popup/daily_title"]),
    ("shield_info", ["popup/shield_title"]),       # Magic Shield info: Continue only, NEVER "Remove"
    ("lab_window", ["lab/in_progress_title"]),     # laboratory after starting research (has a gems button!)
    ("upgrade_window", ["upgrade/confirm", "upgrade/close", "lab/close"]),   # any big window with a red X
    ("dialog", ["popup/speech_corner"]),          # event/tutorial character talking
    ("switcher", ["sid/switch_id_label"]),
    ("settings", ["settings/title"]),
    ("army", ["army/my_army_title"]),
    ("attack_menu", ["attack_menu/find_match"]),
    ("remove_dialog", ["army/remove_title"]),      # "Remove troops?" -> Cancel when lost
    ("request_window", ["request/title"]),         # request window -> Cancel when lost
    ("results", ["results/claim_reward", "results/return_home"]),
    ("chest", ["chest/continue", "chest/room", "chest/pedestal", "chest/tap_text"]),
    ("confirm", ["battle/confirm_okay"]),
    ("scout", ["scout/next"]),              # "Available Loot" stays visible in battle, Next does not
    ("battle", ["battle/surrender"]),
    ("loading", ["load/loading"]),
]

CLOSE_BUTTONS = ["settings/close", "army/close", "sid/close"]
# Buttons worth tapping wherever they appear when the screen is not recognised.
ANYWHERE_BUTTONS = ["results/return_home", "results/claim_reward", "chest/continue", "battle/confirm_okay",
                    "popup/reload", "popup/try_again", "popup/okay", "popup/daily_claim", "popup/close_x"]


def detect(frame):
    for name, keys in STATES:
        for k in keys:
            if vision.templates.has(k) and vision.find(frame, k):
                return name
    return "unknown"


def _close_any_popup(bot, frame):
    """Unknown screen: tap a known button or a red X if one is anywhere, else tap empty forest."""
    full = (0, 0, frame.shape[1], frame.shape[0])
    for k in ANYWHERE_BUTTONS:
        if vision.templates.has(k):
            m = vision.find(frame, k, region=full)
            if m:
                bot.tap_match(m)
                return
    for k in CLOSE_BUTTONS:
        if vision.templates.has(k):
            m = vision.find(frame, k, region=(0, 0, frame.shape[1], frame.shape[0]), threshold=0.8)
            if m:
                bot.tap_match(m, jitter=2)
                return
    _tap_empty(bot, frame)


def _tap_empty(bot, frame):
    """Tap an empty spot of whichever village is behind the popup (each has its own)."""
    bb = vision.templates.has("bb/trophy_hammer") and vision.find(frame, "bb/trophy_hammer", any_brightness=True)
    bot.tap_point("bb.safe" if bb else "home.safe", jitter=5)


def surrender(bot):
    """End a battle in progress and return to the results screen."""
    if bot.tap_template("battle/surrender", timeout=3):
        bot.tap_template("battle/confirm_okay", timeout=4)


def go_home(bot, timeout=60.0):
    """Get back to the home village from wherever the game is. Returns True on success."""
    end = time.monotonic() + timeout
    unknown = 0
    chest_taps = 0
    last = None
    while time.monotonic() < end:
        frame = bot.shot()
        state = detect(frame)
        if state != last:
            log.debug("screen: %s", state)
            last = state
        if state == "home":
            return True
        if state == "unknown":
            unknown += 1
            if unknown % 3 == 0:     # give animations a moment before tapping blindly
                _close_any_popup(bot, frame)
        else:
            unknown = 0
        if state == "switcher":
            bot.tap_point("sid.close", jitter=2)
        elif state == "settings":
            bot.tap_point("settings.close", jitter=2)
        elif state == "army":
            bot.tap_point("army.close", jitter=2)
        elif state == "attack_menu":
            bot.tap_point("attack_menu.close")
        elif state == "scout":
            bot.tap_point("scout.end_battle")
        elif state == "battle":
            surrender(bot)
        elif state == "confirm":
            bot.tap_template("battle/confirm_okay", timeout=1)
        elif state == "results":
            for k in ("results/claim_reward", "results/return_home"):
                m = vision.templates.has(k) and vision.find(frame, k)
                if m:
                    bot.tap_match(m)
                    break
        elif state == "chest":
            m = vision.templates.has("chest/continue") and vision.find(frame, "chest/continue")
            if m:
                bot.tap_match(m)
            else:
                # each tap breaks one lock; taps during the shake animation are ignored, so wait
                # between taps and rotate between the chest, above it and the side of the room
                spots = [(960, 600), (960, 420), (1830, 420), (960, 600), (700, 700)]
                bot.tap(*space.center(*spots[chest_taps % len(spots)]), jitter=12)
                chest_taps += 1
                control.sleep(0.6)
        elif state == "donate":
            bot.tap_point("donate.close", jitter=3)
        elif state == "chat":
            bot.tap_point("chat.close", jitter=2)
        elif state in ("lab_window", "upgrade_window"):
            m = None
            for key in ("lab/close", "upgrade/close"):
                m = vision.templates.has(key) and vision.find(frame, key)
                if m:
                    break
            if m:
                bot.tap_match(m, jitter=1)          # never the Finish Now (gems / magic item) buttons
            else:
                _tap_empty(bot, frame)
        elif state == "remove_dialog":
            bot.tap_point("dialog.cancel")
        elif state == "request_window":
            bot.tap_point("request.cancel")
        elif state == "shop":
            m = vision.find(frame, "shop/close") if vision.templates.has("shop/close") else None
            bot.tap_match(m, jitter=1) if m else bot.tap_point("shop.close", jitter=0)
        elif state == "shield_info":
            m = vision.templates.has("popup/shield_continue") and vision.find(frame, "popup/shield_continue")
            bot.tap_match(m) if m else bot.tap_point("popup.shield_continue")
        elif state == "bb_home":
            # in the Builder Base but the home village is wanted: sail back
            from .actions import builder_base
            try:
                builder_base.travel(bot, "main")
            except Exception as e:  # noqa: BLE001
                log.warning("Could not sail back from the Builder Base: %s", e)
        elif state == "daily":
            # the X only works after claiming today's reward
            m = vision.templates.has("popup/daily_claim") and vision.find(frame, "popup/daily_claim")
            if m:
                bot.tap_match(m)
            else:
                bot.tap_point("popup.close_x", jitter=2)
        elif state == "dialog":
            bot.tap(*space.center(1300, 300), jitter=10)     # next line of the conversation
            control.sleep(0.4)
            continue
        elif state == "reload":
            for k in ("popup/reload", "popup/try_again"):
                m = vision.templates.has(k) and vision.find(frame, k)
                if m:
                    bot.tap_match(m)
                    break
        control.sleep(0.45)
    bot.save_error("not-home")
    return False


def ensure_game(bot, timeout=150.0):
    """Start the game if needed and wait for the home village."""
    dev = bot.device
    if not dev.is_game_running():
        log.info("Starting Clash of Clans...")
        dev.launch_game()
        start = time.monotonic()
        while not dev.is_game_running():
            if time.monotonic() - start > 60:
                raise BotError("Clash of Clans did not start")
            control.sleep(2)
    if not go_home(bot, timeout):
        raise BotError("Could not reach the home village")
    return True


def restart_game(bot):
    log.warning("Restarting Clash of Clans")
    bot.device.close_game()
    control.sleep(8)
    ensure_game(bot)

"""Which screen is the game on, and how to get back to the home village."""

import logging
import re
import time

import cv2
import numpy as np

from .core import net, vision
from .core.context import BotError
from .core.control import control
from .core.space import space

log = logging.getLogger("bot")

# Order matters: overlays that leave the village buttons visible (chat, "Anyone there?") come
# first, then the village itself (the most common screen: checked early to save time; every
# other overlay dims the village buttons, so they cannot match under it), then the rest.
STATES = [
    ("exit_dialog", ["popup/exit_title"]),        # "Confirm Exit - quit the game?": ALWAYS Cancel, never Okay
    ("wall_dialog", ["wall/dialog_title"]),       # "Upgrade Walls ... for 40000 Gold?" left open: Cancel (only
    #                                               the wall upgrade itself presses its Okay, after checking it)
    ("maintenance", ["popup/maintenance"]),       # "Maintenance break" (news page): wait its estimated time
    ("live_replay", ["battle/live_replay"]),      # someone attacks this village right now: wait until it ends
    ("shop", ["shop/close", "shop/title"]),       # the Shop (gem / money offers): only ever its X
    ("reload", ["popup/try_again", "popup/reload_device", "popup/reload", "popup/anyone_there"]),
    ("donate", ["donate/window_title"]),
    ("chat", ["chat/close"]),                     # clan chat open over the village
    ("bb_army", ["bb/army_title"]),               # Builder Base "Choose Army": close with its X
    ("bb_home", ["bb/trophy_hammer"]),            # Builder Base village (night): before "home"
    # the Build button (not in battles) and the dark elixir drop (not in the Builder Base), both undimmed
    # (the button under the profile picture is a trophy or a league badge, depending on the account)
    ("home", ["home/build_button", "home/dark_drop"]),
    ("daily", ["popup/daily_title"]),
    ("reward_popup", ["popup/hoggy_title"]),        # Hoggy Bank rewards etc.: Continue
    ("shield_info", ["popup/shield_title"]),       # Magic Shield info: Continue only, NEVER "Remove"
    ("lab_window", ["lab/in_progress_title"]),     # laboratory after starting research (has a gems button!)
    ("upgrade_window", ["upgrade/confirm", "upgrade/close", "lab/close"]),   # any big window with a red X
    ("dialog", ["popup/speech_corner"]),          # event/tutorial character talking
    ("switcher", ["sid/switch_id_label"]),
    ("settings", ["settings/title"]),
    ("army", ["army/my_army_title"]),
    ("attack_menu", ["attack_menu/find_match", "attack_menu/edit_army"]),   # (Battle card grey: no army)
    ("remove_dialog", ["army/remove_title"]),      # "Remove troops?" -> Cancel when lost
    ("request_window", ["request/title"]),         # request window -> Cancel when lost
    ("results", ["results/claim_reward", "results/return_home"]),
    ("chest", ["chest/continue", "chest/room", "chest/pedestal", "chest/tap_text"]),
    ("confirm", ["battle/confirm_okay"]),
    ("scout", ["scout/next"]),              # "Available Loot" stays visible in battle, Next does not
    ("battle", ["battle/surrender"]),
    ("loading", ["load/loading"]),
]

CLOSE_BUTTONS = ["settings/close", "army/close", "sid/close", "build/close"]   # build: the Build side panel
# Buttons worth tapping wherever they appear when the screen is not recognised.
ANYWHERE_BUTTONS = ["results/return_home", "results/claim_reward", "chest/continue", "popup/continue_green",
                    "battle/confirm_okay",
                    "popup/try_again", "popup/reload_device", "popup/reload", "popup/okay", "popup/daily_claim",
                    "popup/close_x"]


# The game's own dialogs (dark box, light-blue capital buttons): connection lost -> TRY AGAIN,
# another device opened this account -> RELOAD, idle too long -> RELOAD GAME.
RELOAD_KEYS = ["popup/try_again", "popup/reload", "popup/reload_device"]   # RELOAD GAME before its prefix RELOAD
SYSTEM_TEXT = [("try again", "popup/try_again"), ("reload game", "popup/reload"), ("reload", "popup/reload_device")]
SYSTEM_REGION = (160, 120, 1600, 840)
DIALOG_BGR = (30, 28, 25)          # the flat dark grey of those dialogs
RELOAD_LOG = {"popup/try_again": "Connection lost: tapping Try Again",
              "popup/reload_device": "Another device opened this account: opening it here again",
              "popup/reload": "The game asks to reload (idle too long): Reload Game"}


def dialog_box(frame):
    """The game's system dialog (a large flat dark-grey box: (30, 28, 25) on the PC, (64, 57, 54) on
    Android), if one is on screen: (x, y, w, h) or None. Cheap, so the (slow) text reading only
    runs when there really is such a dialog."""
    x, y, w, h = space.region(*SYSTEM_REGION)
    step = 4                                         # every 4th pixel is plenty for a box this big
    roi = frame[y:y + h:step, x:x + w:step].astype(np.int16)
    q = roi // 8
    packed = (q[:, :, 0] * 1024 + q[:, :, 1] * 32 + q[:, :, 2]).ravel()
    counts = np.bincount(packed, minlength=32768)
    top = int(counts.argmax())
    if counts[top] < packed.size * 0.1:
        return None
    colour = np.array([top // 1024, (top // 32) % 32, top % 32]) * 8 + 4
    if colour.min() < 14 or colour.max() > 100 or colour.max() - colour.min() > 24:
        return None                                  # not a dark neutral grey (black = loading screen)
    mask = np.abs(roi - colour).max(axis=2) <= 7
    if mask.sum() < 30000 // step ** 2:
        return None
    rows = np.where(mask.sum(axis=1) > 200 // step)[0]
    cols = np.where(mask.sum(axis=0) > 60 // step)[0]
    if len(rows) < 60 // step or len(cols) < 200 // step:
        return None
    x0, y0 = x + int(cols.min()) * step, y + int(rows.min()) * step
    box = (x0, y0, int(cols.max() - cols.min() + 1) * step, int(rows.max() - rows.min() + 1) * step)
    H, W = frame.shape[:2]
    bx, by, bw, bh = box
    if not (abs(bx + bw / 2 - W / 2) < W * 0.12 and abs(by + bh / 2 - H / 2) < H * 0.2
            and 0.3 * W <= bw <= 0.72 * W and 0.15 * H <= bh <= 0.6 * H):
        return None                                  # not centred / not dialog-sized (e.g. clan chat)
    global _dialog_colour
    _dialog_colour = tuple(int(c) for c in colour)
    return box


_dialog_colour = DIALOG_BGR


def _button_boxes(frame, box):
    """Text groups in the bottom row of the dialog = its buttons (light-blue capitals)."""
    x, y, w, h = box
    x0, y0 = x + 20, y + int(h * 0.55)                 # the buttons are in the lower part
    strip = frame[y0:y + h - 12, x0:x + w - 20].astype(np.int16)
    ink = np.abs(strip - np.array(_dialog_colour)).max(axis=2) > 60
    if ink.size:
        ink[ink.mean(axis=1) > 0.5, :] = False       # an outlined button (Android): drop its frame lines
        ink[:, ink.mean(axis=0) > 0.5] = False
    cols = np.where(ink.any(axis=0))[0]
    out = []
    if len(cols) == 0:
        return out
    start = prev = cols[0]
    for c in list(cols[1:]) + [None]:
        if c is None or c - prev > 30:                 # a wide gap separates two buttons
            rows = np.where(ink[:, start:prev + 1].any(axis=1))[0]
            out.append((x0 + int(start) - 6, y0 + int(rows.min()) - 6, int(prev - start) + 13,
                        int(rows.max() - rows.min()) + 13))
            start = c
        prev = c if c is not None else prev
    return out


def system_button(frame):
    """Read the game's Try Again / Reload buttons on its dark system dialog (for when there is no
    template for them yet). Returns (template key, (x, y, w, h)) or (None, None)."""
    box = dialog_box(frame)
    if box is None:
        return None, None
    for b in _button_boxes(frame, box):
        text, conf = vision.text_reader.read_line(frame, b)
        words = re.sub(r"[^a-z]", "", text.lower())
        for button, key in SYSTEM_TEXT:
            if conf > 0.6 and words == button.replace(" ", ""):
                return key, b
    return None, None


_last_reload_log = {}


def press_reload(bot, frame, key=None, box=None):
    """Tap the game's Try Again / Reload button. Offline: wait for the internet first, so the bot
    keeps trying instead of restarting the game again and again. Returns True if tapped."""
    m = None
    if key is None or box is None:
        for k in ([key] if key else RELOAD_KEYS):
            m = vision.templates.has(k) and vision.find(frame, k)
            if m:
                key = k
                break
    if key is None or (m is None and box is None):
        return False
    now = time.monotonic()
    if now - _last_reload_log.get(key, 0) > 60:
        _last_reload_log[key] = now
        log.warning(RELOAD_LOG[key])
    if key == "popup/try_again":
        net.wait_until_online(bot)
    if m:
        bot.tap_match(m)
    else:
        x, y, w, h = box
        if not vision.templates.has(key):              # remember the button: next time it is found at once
            pad = 6
            vision.templates.save(key, frame, (max(0, x - pad), max(0, y - pad), w + 2 * pad, h + 2 * pad),
                                  threshold=0.8, pad=120)
            log.info("Saved the game's '%s' button as template %s", key.split("/")[-1].replace("_", " "), key)
        bot.tap(x + w // 2, y + h // 2, jitter=2)
    bot.reloaded = True
    bot.reload_at = time.monotonic()
    return True


def after_reload(bot):
    """After a reload the game shows the account it had; make sure it is still the one the bot
    was working on (it usually is), else open that one again."""
    bot.reloaded = False
    acc = getattr(bot, "current_acc", None)
    if not acc or getattr(bot, "_reopening", False):
        return
    from .actions import account
    if account.on_account(bot, acc, check_name=True):
        log.info("Back on %s after the reload", acc["name"])
        return
    log.warning("After the reload the game shows another account: opening %s again", acc["name"])
    bot._reopening = True
    try:
        bot.current_account = None
        account.switch_to(bot, acc, getattr(bot, "state", None))
    finally:
        bot._reopening = False


def placement(frame):
    """A building waiting to be placed (after buying one): its green tick and red X, drawn at the
    map's zoom (so at any size). Returns (tick, cross) matches, either can be None."""
    small = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)   # half size: 4x faster
    found = {}
    for key, hues in (("building/place_ok", (35, 90)), ("building/place_cancel", (0, 12))):
        if not vision.templates.has(key):
            continue
        base = vision.templates.image(key)
        best = None
        for sc in (0.8, 0.9, 1.0, 1.1, 1.2):
            tpl = cv2.resize(base, None, fx=sc / 2, fy=sc / 2, interpolation=cv2.INTER_AREA)
            _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(small, tpl, cv2.TM_CCOEFF_NORMED))
            if score >= 0.8 and (best is None or score > best[0]):
                h, w = tpl.shape[0] * 2, tpl.shape[1] * 2
                best = (score, vision.Match(loc[0] * 2 + w // 2, loc[1] * 2 + h // 2, float(score),
                                            (loc[0] * 2, loc[1] * 2, w, h)))
        m = best[1] if best else None
        if m:
            x, y, w, h = m.box
            hsv = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)
            px = hsv[(hsv[..., 1] > 120) & (hsv[..., 2] > 100)]
            hue = float(np.median(px[:, 0])) if len(px) > 30 else -1
            if hues[0] <= hue <= hues[1] or (key.endswith("cancel") and hue >= 165):
                found[key] = m                     # the right colour: a tick is green, a cross red
    tick, cross = found.get("building/place_ok"), found.get("building/place_cancel")
    if tick and cross and not (tick.x > cross.x and abs(tick.y - cross.y) < 25):
        return None, None                          # not the pair (the tick is right of the cross)
    return tick, cross


def cancel_placement(bot, frame=None):
    """Leave placement mode with the red X (nothing is bought). Returns True if it was open."""
    frame = bot.shot() if frame is None else frame
    _, cross = placement(frame)
    if cross:
        bot.tap_match(cross, jitter=1)
        control.sleep(1.0)
        log.info("Left placement mode (cancelled)")
        return True
    return False


ALL_KEYS = {"home"}       # states that need all their pictures to match


def detect(frame):
    for name, keys in STATES:
        if name == "reload" and dialog_box(frame) is not None:
            return "reload"                      # the village behind those dialogs is not dimmed
        have = [k for k in keys if vision.templates.has(k)]
        if name == "home":
            # the Build button (not in battles), and the dark elixir drop - or, for an account without dark
            # elixir yet, the green + of the gems (both not in the Builder Base, which is checked before)
            if vision.find(frame, "home/build_button") and (
                    vision.find(frame, "home/dark_drop")
                    or (vision.templates.has("home/gem_plus") and vision.find(frame, "home/gem_plus"))):
                return name
            continue
        if name in ALL_KEYS:
            if have and all(vision.find(frame, k) for k in have):
                return name
            continue
        for k in have:
            if vision.find(frame, k, any_brightness=name == "bb_home"):
                return name
    return "unknown"


def tutorial_bubble(frame):
    """A character's speech bubble (the new-UI tutorials: "Settings has moved...", "Easily view
    Battle Logs..."): the match of its top-left ornament, or None."""
    if not vision.templates.has("popup/speech_corner"):
        return None
    return vision.find(frame, "popup/speech_corner", any_brightness=True)


TUTORIAL_TAPS = [            # tutorials that wait for a button instead of a tap on the message
    (("builder", "menu"), "top.builders_menu"),        # "Let's view the new Builder Menu!" -> Build button
]


def dismiss_tutorial(bot, frame=None):
    """Close a tutorial speech bubble of the game: tap the message, or - for the ones that point at a
    button with an arrow (e.g. the new Builder Menu) - tap that button and close what it opens.
    True if there was one."""
    frame = bot.shot() if frame is None else frame
    m = tutorial_bubble(frame)
    if not m:
        return False
    x, y, w, h = m.box
    text = " ".join(t for t, _, _ in vision.text_reader.read(frame, (x, y, space.s(430), space.s(170)))).lower()
    for words, point in TUTORIAL_TAPS:
        if all(wd in text for wd in words):
            log.info("Game tutorial (%s): tapping the button it points at", " ".join(words))
            bot.tap_point(point, jitter=3)
            control.sleep(1.5)
            for _ in range(5):                         # the tutorial may go on inside: tap its messages
                b = tutorial_bubble(bot.shot())
                if not b:
                    break
                bot.tap(b.x + space.s(180), b.y + space.s(60), jitter=4)
                control.sleep(1.0)
            if vision.templates.has("build/close") and vision.find(bot.shot(), "build/close"):
                bot.tap_point("build.close")
                control.sleep(0.6)
            return True
    bot.tap(m.x + space.s(180), m.y + space.s(60), jitter=4)
    log.info("Closed a tutorial message of the game")
    control.sleep(0.8)
    return True


def _close_any_popup(bot, frame):
    """Unknown screen: tap a known button or a red X if one is anywhere, else tap empty forest."""
    full = (0, 0, frame.shape[1], frame.shape[0])
    for k in ANYWHERE_BUTTONS:
        if vision.templates.has(k):
            m = vision.find(frame, k, region=full)
            if m:
                if k in RELOAD_KEYS:
                    press_reload(bot, frame, k)
                else:
                    bot.tap_match(m)
                return
    for k in CLOSE_BUTTONS:
        if vision.templates.has(k):
            m = vision.find(frame, k, region=(0, 0, frame.shape[1], frame.shape[0]), threshold=0.8)
            if m:
                bot.tap_match(m, jitter=2)
                return
    if cancel_placement(bot, frame):
        return
    if bot.device.kind == "adb":
        bot.key("back")                  # Android: Back closes the window on top - safer than a blind tap
        return
    _tap_empty(bot, frame)


def _tap_empty(bot, frame):
    """Tap an empty spot of whichever village is behind the popup (each has its own)."""
    bb = vision.templates.has("bb/trophy_hammer") and vision.find(frame, "bb/trophy_hammer", any_brightness=True)
    bot.tap_point("bb.safe" if bb else "home.safe", jitter=5)


SURRENDER_WIDE = (0, 560, 560, 520)      # bottom-left quarter: where the Surrender button can be


def surrender(bot, frame=None, blind=False):
    """End a battle in progress: Surrender, then Okay. The button is looked for where it usually is,
    then in the whole bottom-left corner; blind=True (the caller knows a battle is running) also
    taps its usual spot when it cannot be seen. Returns True if the battle was ended."""
    frame = bot.shot() if frame is None else frame
    m = (vision.find(frame, "battle/surrender") or
         vision.find(frame, "battle/surrender", region=space.region(*SURRENDER_WIDE), threshold=0.75,
                     any_brightness=True))
    if m:
        bot.tap_match(m)
    elif blind:
        x, y, w, h = vision.templates.meta("battle/surrender")["box"]
        bot.tap(*space.point(x + w // 2, y + h // 2), jitter=2)
    else:
        return False
    return bool(bot.tap_template("battle/confirm_okay", timeout=3))


MAINTENANCE_TIME = (1650, 50, 250, 80)     # "Estimated time 39m" at the top right of the maintenance page
LIVE_REPLAY_MAX = 300                     # an attack lasts 3 minutes at most (+ its results)


def wait_maintenance(bot, frame):
    """Supercell's maintenance break: nothing can be done until it is over. Wait the time it shows
    (checking every minute), then restart the game."""
    from .actions.timers import parse_time
    secs = None
    for text, _, _ in vision.text_reader.read(frame, space.region(*MAINTENANCE_TIME)):
        secs = parse_time(text) or secs
    secs = secs or 15 * 60
    log.warning("The game is in a maintenance break (about %d min): waiting, then going on", secs // 60 + 1)
    bot.status(action=f"Maintenance break - about {secs // 60 + 1} min", waiting=False)
    until = time.monotonic() + secs + 60
    while time.monotonic() < until:
        control.sleep(60)
        if not vision.find(bot.shot(), "popup/maintenance"):
            break                                     # over (or the game shows something else now)
    restart_game(bot)


def go_home(bot, timeout=60.0):
    """Get back to the home village from wherever the game is. Returns True on success."""
    end = time.monotonic() + timeout
    live_since = None
    unknown = 0
    chest_taps = 0
    last = None
    last_ocr = 0.0
    loaded_after = None         # the Reload / Try Again tap after which the game was seen loading
    while time.monotonic() < end:
        frame = bot.shot()
        state = detect(frame)
        if state != last:
            log.debug("screen: %s", state)
            last = state
        if bot.reloaded and state not in ("home", "reload"):
            loaded_after = bot.reload_at            # the game is loading again after that tap
        if state == "home" and tutorial_bubble(frame):
            dismiss_tutorial(bot, frame)             # a tutorial over the village: close it first
            continue
        if state == "home":
            if bot.reloaded:
                # right after the tap the old picture is still there: wait until it really reloaded
                if loaded_after != bot.reload_at and time.monotonic() - bot.reload_at < 10:
                    control.sleep(0.45)
                    continue
                after_reload(bot)
            return True
        if state == "unknown":
            unknown += 1
            if unknown % 3 == 0:     # give animations a moment before tapping blindly
                _close_any_popup(bot, frame)
        else:
            unknown = 0
        if state == "maintenance":
            wait_maintenance(bot, frame)
            end = time.monotonic() + timeout
            continue
        if state == "live_replay":
            if live_since is None:
                live_since = time.monotonic()
                log.info("Someone is attacking this village right now (live replay): waiting until it ends")
            if time.monotonic() - live_since < LIVE_REPLAY_MAX:
                end = max(end, time.monotonic() + 20)  # the attack ends by itself: never tap into it
            control.sleep(3)
            continue
        if state in ("exit_dialog", "wall_dialog"):
            bot.tap_point("dialog.cancel")           # never quit the game / never pay for walls by accident
        elif state == "switcher":
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
        elif state == "bb_army":
            bot.tap_point("bb.army_close")
        elif state == "shop":
            m = vision.find(frame, "shop/close") if vision.templates.has("shop/close") else None
            bot.tap_match(m, jitter=1) if m else bot.tap_point("shop.close", jitter=0)
        elif state == "reward_popup":
            m = vision.templates.has("popup/continue_green") and vision.find(frame, "popup/continue_green")
            bot.tap_match(m) if m else bot.tap_point("popup.shield_continue")
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
            if not dismiss_tutorial(bot, frame):
                bot.tap(*space.center(1300, 300), jitter=10)     # next line of the conversation
            control.sleep(0.4)
            continue
        elif state == "reload":
            tapped = press_reload(bot, frame)
            if not tapped and time.monotonic() - last_ocr > 2.5:
                last_ocr = time.monotonic()
                key, box = system_button(frame)                    # no template for this button yet
                tapped = bool(key) and press_reload(bot, frame, key, box)
                if not tapped:
                    if bot.device.kind == "adb":
                        bot.key("back")          # e.g. Android's "exit the game?": dismiss it
                    else:
                        log.warning("A game dialog without Try Again / Reload is open; waiting")
            if tapped:
                end = max(end, time.monotonic() + 90)              # never give up while it reconnects
                control.sleep(1.0)
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
        for _ in range(4):                    # the store window can appear a little after the game
            dev.tidy_up()
            control.sleep(2)
    else:
        dev.tidy_up()
    if not go_home(bot, timeout):
        raise BotError("Could not reach the home village")
    return True


def restart_game(bot):
    log.warning("Restarting Clash of Clans")
    bot.device.close_game()
    control.sleep(8)
    ensure_game(bot)

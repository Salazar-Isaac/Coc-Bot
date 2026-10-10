"""Clan Castle and donations: empty the CC, request reinforcements, donate to requests.

Screens (Google Play Games 1920x1080, all captured as templates):
  Army screen   - CC section with a trash button (army/cc_remove) and the green
                  request button (army/request_button). Removing asks
                  "Remove troops?" -> Okay (battle/confirm_okay, same dialog style).
  Request       - "Request Reinforcements" window (request/title) with Send.
  Clan chat     - opened from the chat button on the left; each open request has
                  a green Donate button (chat/donate_button).
  Donate window - "Donation Resource" (donate/window_title) with troop/spell icons;
                  a usable icon is in colour, an unusable one is grey.
"""

import logging
import time

import cv2
import numpy as np

from ..core import vision
from ..core.context import BotError
from ..core.control import control
from ..core.space import space
from ..states import go_home

log = logging.getLogger("bot")

# --- army screen ------------------------------------------------------------------------

def open_army(bot):
    if not go_home(bot):
        raise BotError("Not on the home village")
    bot.tap_point("home.army")
    if not bot.wait("army/my_army_title", 8):
        raise BotError("Army screen did not open")
    bot.sleep(0.6)


def close_army(bot):
    bot.tap_point("army.close")
    bot.sleep(0.5)


def _active(frame, key):
    """A button that is in colour (enabled), not greyed out."""
    m = vision.find(frame, key, any_brightness=True)
    if not m:
        return None
    x, y, w, h = m.box
    sat = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)[:, :, 1].mean()
    tpl_sat = cv2.cvtColor(vision.templates.image(key), cv2.COLOR_BGR2HSV)[:, :, 1].mean()
    return m if sat >= tpl_sat * 0.6 else None


def remove_cc_troops(bot):
    """Empty the Clan Castle (army screen must be open). Returns True if something was removed."""
    frame = bot.shot()
    m = vision.find(frame, "army/cc_remove", any_brightness=True)
    if not m:
        log.debug("Clan Castle remove button not found")
        return False
    x, y, w, h = m.box
    # greyed trash = nothing to remove (or the CC is locked by an open request)
    if frame[y:y + h, x:x + w].mean() < vision.templates.image("army/cc_remove").mean() * 0.75:
        log.debug("Clan Castle already empty or locked")
        return False
    bot.tap_match(m)
    if not bot.wait("army/remove_title", 4):
        msg = "Clan Castle troops are locked (a request is still open)"
        log.info(msg)
        return False
    bot.tap_template("battle/confirm_okay", timeout=3, after=0.6)
    log.info("Clan Castle emptied")
    return True


def request(bot, text=""):
    """Send a reinforcement request (army screen must be open). Returns True if sent."""
    frame = bot.shot()
    if vision.templates.has("army/request_cooldown") and vision.find(frame, "army/request_cooldown",
                                                                      any_brightness=True):
        log.info("Request is on cooldown (never paying gems to skip it)")
        return False
    m = _active(frame, "army/request_button")
    if not m or m.score < 0.9:
        log.info("Request button not available (cooldown, request already open, or CC full)")
        return False
    bot.tap_match(m)
    if not bot.wait("request/title", 5):
        log.info("Request window did not open")
        return False
    if text:
        box = bot.find("request/text_box")
        if box:
            bot.tap_match(box)
            bot.sleep(0.3)
            bot.key("end")
            for _ in range(60):
                bot.key("backspace")
            bot.device.type_text(text)
            bot.sleep(0.2)
    if not bot.tap_template("request/send", timeout=4, after=0.8):
        return False
    log.info("Reinforcements requested")
    return True


def feeder_turn(bot, account, settings):
    """On a feeder account: empty the CC (optional) and request."""
    open_army(bot)
    try:
        if settings["donate"].get("remove_cc_before_request", True):
            remove_cc_troops(bot)
            bot.sleep(0.4)
        return request(bot, settings["donate"].get("request_text", ""))
    finally:
        close_army(bot)
        go_home(bot)


# --- clan chat / donating ----------------------------------------------------------------

def open_chat(bot):
    if not go_home(bot):
        raise BotError("Not on the home village")
    bot.tap_point("home.chat")
    bot.sleep(1.2)
    if bot.exists("chat/rules_understand"):         # first time on this account
        bot.tap_template("chat/rules_understand", timeout=2, after=0.8)
    if not bot.wait_any(["chat/close", "chat/challenge"], 6)[0]:
        raise BotError("Clan chat did not open")


def close_chat(bot):
    m = bot.find("chat/close")
    if m:
        bot.tap_match(m)
    else:
        bot.tap_point("chat.close")
    bot.sleep(0.6)


def donate_buttons(frame):
    """All Donate buttons visible in the chat, bottom first (newest requests)."""
    full = (0, 0, frame.shape[1] // 3, frame.shape[0])
    ms = vision.find_all(frame, "chat/donate_button", region=full)
    return sorted(ms, key=lambda m: -m.y)


def _donate_items(settings):
    return [i for i in settings["donate"].get("items", []) if i.get("enabled", True) and i.get("template")]


def _donated_strip(frame):
    """The 'Donated Troops and Spells' row at the bottom of the donate window."""
    x, y, w, h = space.region(640, 945, 820, 100)
    return frame[y:y + h, x:x + w].astype(np.int16)


def fill_request(bot, items):
    """Donate window is open: tap items in priority order. Returns the number of units donated
    (a tap counts only if the 'donated' row changed, e.g. not when the CC is full)."""
    donated = 0
    for item in items:
        key = item["template"]
        if not vision.templates.has(key):
            continue
        for _ in range(max(1, int(item.get("clicks", 1)))):
            control.checkpoint()
            frame = bot.shot()
            if not vision.find(frame, "donate/window_title"):
                return donated                      # window closed itself: request filled
            m = _active(frame, key)
            if not m:
                break                               # not available / not wanted by this request
            before = _donated_strip(frame)
            bot.tap_match(m, jitter=2)
            time.sleep(0.3)
            after = bot.shot()
            if not vision.find(after, "donate/window_title"):
                return donated + 1                  # that tap filled the request and closed the window
            if np.abs(_donated_strip(after) - before).mean() < 2:
                break                               # no room for this item in the request
            donated += 1
    return donated


def donate_all(bot, settings, max_requests=60):
    """Main account: donate to every open request in the chat, scrolling up through older
    messages until no new Donate buttons appear. Returns the number of donations."""
    items = _donate_items(settings)
    if not items:
        raise BotError("Nothing to donate: add items in the Donate tab")
    open_chat(bot)
    total, handled = 0, 0
    page, empty_pages = 0, 0
    tried = set()
    try:
        while handled < max_requests and empty_pages < 3:
            frame = bot.shot()
            buttons = [b for b in donate_buttons(frame) if (page, b.y // 12) not in tried]
            if not buttons:
                empty_pages += 1
                page += 1
                bot.swipe(bot.layout.point("chat.scroll_from"), bot.layout.point("chat.scroll_to"), 500)
                bot.sleep(0.8)
                continue
            empty_pages = 0
            b = buttons[0]
            tried.add((page, b.y // 12))
            handled += 1
            bot.tap_match(b)
            if not bot.wait("donate/window_title", 4):
                continue
            n = fill_request(bot, items)
            total += n
            log.info("Donated %d unit(s) to a request", n)
            if bot.exists("donate/window_title"):
                bot.tap_point("donate.close")          # tap beside the window to close it
                bot.sleep(0.6)
            bot.sleep(0.4)
    finally:
        close_chat(bot)
        go_home(bot)
    log.info("Donating done: %d unit(s) to %d request(s)", total, handled)
    return total

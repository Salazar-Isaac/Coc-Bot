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
import re
import time

import cv2
import numpy as np

from ..core import vision
from ..core.context import BotError
from ..core.control import control
from ..core.space import space
from ..states import go_home
from . import troops

log = logging.getLogger("bot")

# --- army screen ------------------------------------------------------------------------

def open_army(bot):
    if not go_home(bot):
        raise BotError("Not on the home village")
    bot.tap_point("home.army")
    if not bot.wait("army/my_army_title", 8, interval=0.25):
        raise BotError("Army screen did not open")
    bot.sleep(0.35)


def close_army(bot):
    bot.tap_point("army.close")
    bot.sleep(0.3)


def _active(frame, key, region=None):
    """A button that is in colour (enabled), not greyed out."""
    m = vision.find(frame, key, any_brightness=True, region=region)
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
    if not bot.wait("army/remove_title", 4, interval=0.2):
        msg = "Clan Castle troops are locked (a request is still open)"
        log.info(msg)
        return False
    bot.tap_template("battle/confirm_okay", timeout=3, after=0.4)
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
        log.info("Request button not available (cooldown, request still open, or Clan Castle full)")
        return False
    bot.tap_match(m)
    if not bot.wait("request/title", 5, interval=0.2):
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
    if not bot.tap_template("request/send", timeout=4, after=0.5):
        return False
    log.info("Reinforcements requested")
    return True


def in_clan(bot):
    """True / False from a clearly visible chat or "Social" button; dialogs over the village are
    dismissed first. None if it could not be told (then nothing is decided from it)."""
    for _ in range(4):
        if not go_home(bot):
            raise BotError("Not on the home village")
        bot.sleep(0.4)
        f = bot.shot()
        if vision.templates.has("home/social_button") and vision.find(f, "home/social_button"):
            return False
        if vision.find(f, "home/chat_button"):
            return True
        bot.sleep(1.0)                                # a dialog or animation is covering the buttons
    log.warning("Could not tell whether this account is in a clan")
    return None


def feeder_turn(bot, account, settings):
    """On a feeder account: empty the CC (optional) and request."""
    if in_clan(bot) is False:
        tag = settings["donate"].get("clan_tag", "")
        if tag and settings["donate"].get("auto_join", True):
            log.info("%s is not in a clan: joining %s", account["name"], tag)
            if join_clan(bot, tag):
                bot.sleep(1.0)
            else:
                account["_no_clan"] = True
                return False
        else:
            log.warning("%s is not in a clan: it cannot request. Set the clan tag on the Donate page to join "
                        "it automatically, or set it to Skip. (Skipped for the next hour.)", account["name"])
            account["_no_clan"] = True
            return False
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
    bot.sleep(0.7)
    if bot.exists("chat/rules_understand"):         # first time on this account
        bot.tap_template("chat/rules_understand", timeout=2, after=0.8)
    if not bot.wait_any(["chat/close", "chat/challenge"], 6)[0]:
        raise BotError("Clan chat did not open")
    m = bot.find("chat/jump_latest")                # chat remembers its scroll: go to the newest
    if m:
        bot.tap_match(m)
        bot.sleep(0.7)


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
    out = []
    for i in settings["donate"].get("items", []):
        if not (i.get("enabled", True) and i.get("template")):
            continue
        i = dict(i)
        i["category"] = i.get("category") or troops.category(i.get("name", ""))
        i["space"] = int(i.get("space") or troops.space_of(i.get("name", "")))
        out.append(i)
    return out


BASE_TITLE_Y = 268      # where the donate window's title sits for a request at the bottom of the chat


def _window_dy(frame):
    """The donate window is drawn next to its request, so it moves up for requests higher in
    the chat. Returns how far it moved (pixels), or None if the window is not open."""
    m = vision.find(frame, "donate/window_title")
    return None if m is None else m.box[1] - BASE_TITLE_Y


def _shifted(region, dy):
    x, y, w, h = space.region(*region)
    return (x, max(0, y + dy), w, h)


def _donated_strip(frame, dy=0):
    """The 'Donated Troops and Spells' row at the bottom of the donate window."""
    x, y, w, h = _shifted((640, 945, 820, 100), dy)
    return frame[y:y + h, x:x + w].astype(np.int16)


def _strip_changed(before, after):
    """True if the donated row changed (a new unit, or an 'x1' -> 'x2' label)."""
    return int((np.abs(after - before).max(axis=2) > 45).sum()) > 20


def _fraction(frame, box):
    f = vision.digits.read_fraction(frame, box)
    if f:
        return f
    text, _ = vision.text_reader.read_line(frame, box)
    m = re.search(r"(\d+)\s*/\s*(\d+)", text.replace(" ", ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def read_request(frame, button):
    """What a request card says, from its Donate button's position:
    {"name", "message", "troop": (have, max), "spell": (...), "siege": (...)}."""
    bx, by = button.x, button.y
    name, _ = vision.text_reader.read_line(frame, (max(0, bx - 420), by - 152, 380, 38))
    msg, _ = vision.text_reader.read_line(frame, (max(0, bx - 432), by - 88, 470, 40))
    return {
        "name": name.strip(),
        "message": msg.strip(),
        "troop": _fraction(frame, (max(0, bx - 374), by - 16, 84, 32)),
        "spell": _fraction(frame, (max(0, bx - 236), by - 16, 64, 32)),
        "siege": _fraction(frame, (max(0, bx - 140), by - 16, 56, 32)),
    }


def _space_left(req):
    left = {}
    for cat in ("troop", "spell", "siege"):
        f = req.get(cat)
        left[cat] = max(0, f[1] - f[0]) if f else None      # None = unknown: let the game decide
    return left


def plan(req, items):
    """Order the items for this request: ones named in the message first, then your priority.
    Items of a full category are left out. Returns (items, space left, asked_for_something)."""
    left = _space_left(req)
    usable = [i for i in items if left.get(i["category"]) != 0]
    if left.get("troop") is not None and left["troop"] < 10:
        usable = [i for i in usable if i.get("use", "all") != "big"]   # a big request needs 10+ troop space
    if not any(i.get("use", "all") != "big" or left.get("troop") is None or left["troop"] >= 10
               for i in usable if i["category"] != "siege"):
        usable = []                                    # only a siege slot left: nothing worth opening
    asked = [i for i in usable if troops.wants(req.get("message"), i)]
    if asked:
        return asked + [i for i in usable if i not in asked], left, True
    return usable, left, False


ROWS = {"troop": (630, 375, 840, 320), "siege": (630, 375, 840, 320), "spell": (630, 720, 840, 180)}


def _find_item(bot, frame, key, dy, cat):
    """Find an item's icon in the donate window. If it is not visible, slide its row to the left
    (more troops / siege machines further right) a few times. Returns a usable match or None."""
    region = _shifted(ROWS.get(cat, ROWS["troop"]), dy)
    for slide in range(4):
        m = _active(frame, key, region=region)
        if m:
            return m
        if vision.find(frame, key, region=region, any_brightness=True, threshold=0.8):
            return None                             # visible but greyed out: not available
        if slide == 3:
            break
        x, y, w, h = region
        cy = y + h // 3
        bot.swipe((x + w - 60, cy), (x + 60, cy), 500)   # slide the row to see further right
        bot.sleep(0.8)
        frame = bot.shot()
    return None


def fill_request(bot, items, left=None):
    """Donate window is open: donate items in order until each category's space is used.
    Returns the number of units donated. A tap counts only if the 'donated' row changed."""
    left = dict(left or {})
    donated = 0
    for item in items:
        key, cat, size = item["template"], item.get("category", "troop"), item.get("space", 1)
        if not vision.templates.has(key):
            continue
        for _ in range(max(1, int(item.get("clicks", 1)))):
            control.checkpoint()
            if left.get(cat) is not None and left[cat] < size:
                break                               # this unit no longer fits
            frame = bot.shot()
            dy = _window_dy(frame)
            if dy is None:
                return donated                      # window closed itself: request filled
            m = _find_item(bot, frame, key, dy, cat)
            if not m:
                break                               # not trained / not available
            frame = bot.frame
            before = _donated_strip(frame, dy)
            bot.tap_match(m, jitter=2)
            changed = False
            for _ in range(4):                      # the row updates 0.2-0.5 s after the tap
                time.sleep(0.15)
                after = bot.shot()
                if _window_dy(after) is None:
                    return donated + 1              # that tap filled the request and closed the window
                if _strip_changed(before, _donated_strip(after, dy)):
                    changed = True
                    break
            if not changed:
                break                               # the game refused (no room for this unit)
            donated += 1
            if left.get(cat) is not None:
                left[cat] -= size
    return donated


# --- fast donating (the XpIncrease way) --------------------------------------------------------

def is_big_request(frame, dy, settings):
    """Like XpIncrease: the Super Wizard (10 housing space) is only in colour while the request
    still has lots of room, so "Super Wizard donatable" = a big request -> the big items."""
    key = settings["donate"].get("special_template", "donate/super_wizard")
    if not key or not vision.templates.has(key):
        return False
    return _active(frame, key, region=_shifted(ROWS["troop"], dy)) is not None


def _find_fast(bot, frame, key, dy, cat):
    """An item's icon; siege machines are at the far right of the troop rows, so if it is not
    visible the row is dragged all the way left once (like XpIncrease) and searched again."""
    region = _shifted(ROWS.get(cat, ROWS["troop"]), dy)
    m = _active(frame, key, region=region)
    if m or cat == "spell":
        return m, frame
    if vision.find(frame, key, region=region, any_brightness=True, threshold=0.8):
        return None, frame                          # visible but grey: not available for this request
    x, y, w, h = region
    cy = y + h // 3
    bot.swipe((x + w - 40, cy), (max(5, x - 600), cy), 450)
    bot.sleep(0.6)
    frame = bot.shot()
    return _active(frame, key, region=region), frame


def fill_fast(bot, items, dy, big):
    """Donate window is open: tap each item its count times in a quick burst (no check after each
    tap; the game ignores taps that do not fit). Items marked "big" are only used for big requests,
    "small" only for the others. Returns the number of taps that went to available items."""
    taps = 0
    frame = bot.shot()
    for item in items:
        use = item.get("use", "all")
        if (use == "big" and not big) or (use == "small" and big):
            continue
        key = item["template"]
        if not vision.templates.has(key):
            continue
        if _window_dy(frame) is None:
            break                                   # the request is full: the window closed itself
        m, frame = _find_fast(bot, frame, key, dy, item.get("category", "troop"))
        if not m:
            continue
        for _ in range(max(1, int(item.get("clicks", 1)))):
            control.checkpoint()
            bot.tap_match(m, jitter=2)
            time.sleep(0.07)
        taps += int(item.get("clicks", 1))
        time.sleep(0.25)
        frame = bot.shot()
    return taps


def _is_mine(bot, name):
    """A request is from one of your accounts if the name matches an account's Supercell ID name
    or its in-game player name (learned when the bot opens the account)."""
    from .account import same_name
    return any(same_name(a["name"], name) or (a.get("player") and same_name(a["player"], name))
               for a in bot.accounts)


def donate_all(bot, settings, max_requests=60):
    """Main account: donate to every open request in the chat, scrolling up through older
    messages until no new Donate buttons appear. Returns the number of units donated."""
    items = _donate_items(settings)
    if not items:
        raise BotError("Nothing to donate: add items in the Donate tab")
    only_mine = settings["donate"].get("donate_to", "all") == "mine"
    open_chat(bot)
    total, handled = 0, 0
    page, empty_pages = 0, 0
    tried, skipped, done_names, retries = set(), set(), set(), {}
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
            req = read_request(frame, b)
            who = req["name"] or "?"
            ident = re.sub(r"[^a-z0-9]", "", req["name"].lower()) or f"?{page}:{b.y}"
            if ident in done_names:
                handled -= 1
                continue                               # already handled this requester in this pass
            if only_mine and req["name"] and not _is_mine(bot, req["name"]):
                if req["name"] not in skipped:
                    log.info("Skipping %s's request (not one of your accounts)", who)
                    skipped.add(req["name"])
                handled -= 1
                continue
            order, left, asked = plan(req, items)
            log.info("Request from %s%s - space left: troops %s, spells %s, siege %s", who,
                     f' ("{req["message"]}")' if req["message"] else "",
                     *(("?" if left[c] is None else left[c]) for c in ("troop", "spell", "siege")))
            if not order:
                log.info("Nothing to give %s: request full or nothing fits", who)
                done_names.add(ident)
                continue
            if asked:
                log.info("%s asks for: %s", who,
                         ", ".join(i["name"] for i in order if troops.wants(req["message"], i)))
            # the chat may have moved while reading (a filled request disappears): re-find the button
            now = [m for m in donate_buttons(bot.shot()) if abs(m.y - b.y) < 14]
            if not now:
                tried.discard((page, b.y // 12))
                handled -= 1
                bot.sleep(0.6)
                continue
            bot.tap_match(now[0])
            if not bot.wait("donate/window_title", 4):
                retries[ident] = retries.get(ident, 0) + 1
                if retries[ident] >= 2:
                    log.info("The donate window for %s did not open; skipping it", who)
                    done_names.add(ident)
                else:
                    tried.discard((page, b.y // 12))
                continue
            done_names.add(ident)
            if settings["donate"].get("method", "fast") == "fast":
                g = bot.shot()
                dy = _window_dy(g) or 0
                big = is_big_request(g, dy, settings)
                n = fill_fast(bot, order, dy, big)
                if big:
                    log.info("%s: big request (Super Wizard available)", who)
            else:
                n = fill_request(bot, order, left)
            total += n
            bot.stats["donated"] = bot.stats.get("donated", 0) + n
            log.info("Donated %d unit(s) to %s", n, who)
            if bot.exists("donate/window_title"):
                bot.tap_point("donate.close")          # tap beside the window to close it
                bot.sleep(0.6)
            bot.sleep(0.4)
    finally:
        close_chat(bot)
        go_home(bot)
    log.info("Donating done: %d unit(s) to %d request(s)", total, handled)
    return total


# --- army recipes ------------------------------------------------------------------------

ARMY_UNITS = {"edrag": "army/edrag", "clone": "army/clone"}


def army_has(frame, units):
    """Which of the required units are NOT in the army screen."""
    return [u for u in units if ARMY_UNITS.get(u) and vision.templates.has(ARMY_UNITS[u])
            and not vision.find(frame, ARMY_UNITS[u], region=bot_army_region())]


def bot_army_region():
    return space.region(840, 300, 960, 420)      # troops + spells rows of the army screen


def use_recipe(bot, name, check=()):
    """Switch the army to the Saved Recipe called `name` (e.g. your E-Dragon + Clone "loot"
    recipe). Any confirmation the game asks (Clan Castle troops present, a request still open,
    ...) is accepted with Okay. Returns (applied, missing_units)."""
    from .account import same_name
    if not name:
        return False, []
    open_army(bot)
    try:
        bot.tap_point("army.recipes_arrow")
        bot.sleep(0.8)
        frame = bot.shot()
        rows = vision.text_reader.read(frame, bot.layout.region("army.recipe_list"))
        target = None
        for text, conf, (x, y, w, h) in rows:
            if conf > 0.5 and (same_name(text, name) or text.strip().lower() == name.strip().lower()):
                target = (x + w // 2, y + h // 2)
                break
        if not target:
            log.info("No saved recipe named '%s' on this account (found: %s)", name,
                     ", ".join(t for t, c, _ in rows if c > 0.5) or "none")
            bot.tap_point("army.recipes_arrow")          # close the list
            bot.sleep(0.4)
            return False, []
        bot.tap(*target, jitter=4)
        # a confirmation may follow ("Use Army Recipe?": Clan Castle troops / open request): Okay
        end = time.monotonic() + 2.5
        while time.monotonic() < end:
            f = bot.shot()
            if vision.find(f, "army/use_recipe_title") or vision.find(f, "battle/confirm_okay"):
                m = vision.find(f, "battle/confirm_okay")
                if m:
                    bot.tap_match(m)
                    bot.sleep(0.7)
                    log.info("Confirmed the army recipe change")
                    break
            bot.sleep(0.25)
        bot.sleep(0.6)
        missing = army_has(bot.shot(), check)
        log.info("Army set to recipe '%s'%s", name, f" (missing: {', '.join(missing)})" if missing else "")
        return True, missing
    finally:
        close_army(bot)
        go_home(bot)


# --- joining a clan ---------------------------------------------------------------------------

def _norm_tag(t):
    return "#" + re.sub(r"[^0-9A-Z]", "", (t or "").upper().replace("O", "0")).lstrip("#")


def join_clan(bot, tag):
    """Join the clan with this tag (only for an account that has no clan). The clan's tag is
    checked on its details page before Join is pressed. Returns True if the account is now in a clan."""
    tag = (tag or "").strip()
    if not tag:
        return False
    status = in_clan(bot)
    if status is not False:
        return bool(status)
    bot.tap_point("home.profile")                    # level badge, top left -> profile / clans window
    if not bot.wait("clan/join_tab", 5, interval=0.25):
        log.warning("Clan window did not open")
        go_home(bot)
        return False
    try:
        bot.tap_template("clan/join_tab", timeout=3, after=0.8)
        bot.tap_template("clan/search_clans_tab", timeout=4, after=0.8)
        typed = ""
        for attempt in range(3):                      # the text box needs a moment; check and retype
            bot.tap_point("clan.search_box")
            bot.sleep(1.0)
            for _ in range(16):
                bot.key("backspace")
                bot.sleep(0.03)
            bot.sleep(0.4)
            bot.device.type_text(tag)
            bot.sleep(0.6)
            typed, _ = vision.text_reader.read_line(bot.shot(), bot.layout.region("clan.search_box"))
            if _norm_tag(typed) == _norm_tag(tag):
                break
        else:
            log.warning("Typing the clan tag failed (read '%s')", typed)
            return False
        bot.key("enter")
        bot.sleep(0.3)
        bot.tap_template("clan/search_button", timeout=3, after=2.0)
        bot.tap_point("clan.first_result")
        if not bot.wait("clan/join_button", 5, interval=0.25):
            log.warning("No Join button for %s (clan full, closed, or invite only?)", tag)
            return False
        shown, _ = vision.text_reader.read_line(bot.shot(), bot.layout.region("clan.details_tag"))
        if _norm_tag(shown) != _norm_tag(tag):
            log.warning("Search found clan %s instead of %s: not joining", shown, tag)
            return False
        bot.tap_template("clan/join_button", timeout=2, after=2.0)
    finally:
        m = bot.find("clan/info_close")
        if m:
            bot.tap_match(m, jitter=1)
            bot.sleep(0.5)
        bot.tap_point("home.safe", jitter=5)          # deselect anything a stray tap selected
        go_home(bot)
    ok = in_clan(bot) is True
    log.info("Joined clan %s" if ok else "Could not join clan %s", tag)
    return ok

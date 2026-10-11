"""Switch accounts through Settings -> Supercell ID, by reading the account names."""

import difflib
import logging
import re
import time

import numpy as np

from .. import config
from ..core import vision
from ..core.space import space
from ..core.context import BotError
from ..states import go_home

log = logging.getLogger("bot")

def normalise(name):
    """Lower-case, no spaces/punctuation; 'o'/'l'/'i' next to a digit become '0'/'1' (OCR mix-ups)."""
    s = re.sub(r"[^0-9a-z]", "", name.lower())
    s = re.sub(r"^0(?=[a-z])", "o", s)              # a leading 'O' read as zero
    for _ in range(2):
        s = re.sub(r"(?<=\d)o|o(?=\d)", "0", s)
        s = re.sub(r"(?<=\d)[il]|[il](?=\d)", "1", s)
    return s


def same_name(a, b):
    """True if two account names match. Numbers must be identical (Buggu1 != Buggu01 != Buggu10);
    the letters may differ a little (OCR reading 'Buaau20' still matches 'Buggu20')."""
    a, b = normalise(a), normalise(b)
    if a == b:
        return True
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    la, lb = re.sub(r"\d", "", a), re.sub(r"\d", "", b)
    return difflib.SequenceMatcher(None, la, lb).ratio() >= 0.6


NOT_ACCOUNTS = ("login", "supercellid")


def _name_lines(frame, region):
    """Rows of near-black text in the name column = account names (clan/TH lines are grey)."""
    x, y, w, h = region
    dark = frame[y:y + h, x:x + w].max(axis=2) < 90
    rows = dark.sum(axis=1)
    lines, r = [], 0
    while r < len(rows):
        if rows[r] >= 3:
            start = r
            while r < len(rows) and rows[r] >= 1:
                r += 1
            if r - start >= 12:
                cols = np.where(dark[start:r].any(axis=0))[0]
                width = cols.max() - cols.min()
                if width > 45:                      # skip the small clan badge
                    lines.append((x + cols.min() - 6, y + start - 6, width + 12, r - start + 12))
        r += 1
    return lines


def read_switcher(bot, frame=None):
    """Visible accounts in the panel: [(name, (x, y) to tap, name_box)]."""
    frame = bot.shot() if frame is None else frame
    out = []
    for box in _name_lines(frame, bot.layout.region("sid.name_column")):
        text, conf = vision.text_reader.read_line(frame, box)
        if text and conf > 0.5 and not any(w in normalise(text) for w in NOT_ACCOUNTS):
            out.append((text, (box[0] + box[2] // 2, box[1] + box[3] // 2), box))
    return out


def read_town_hall(frame, name_box):
    """'Town Hall: 17' is two lines below the name."""
    x, y, w, h = name_box
    off = space.s(56)
    if y + off + h + 4 > frame.shape[0]:
        return 0                                   # card cut off at the bottom of the panel
    text, _ = vision.text_reader.read_line(frame, (x, y + off, space.s(200), h + 4))
    m = re.search(r"(\d{1,2})\s*$", text)
    return int(m.group(1)) if m else 0


def open_switcher(bot):
    if not go_home(bot):
        raise BotError("Not on the home village")
    for attempt in range(2):                      # a tap during an animation can be lost: tap again
        bot.tap_point("home.settings")
        if bot.wait("settings/title", 4, interval=0.15):
            break
        if not go_home(bot, 10):
            raise BotError("Not on the home village")
    else:
        raise BotError("Settings did not open")
    bot.tap_point("settings.switch_id")
    if not bot.wait("sid/switch_id_label", 10, interval=0.15):
        raise BotError("Supercell ID panel did not open")
    # the list slides in: wait until the name column stops moving (max 1.2 s)
    prev = None
    for _ in range(12):
        f = bot.shot()
        x, y, w, h = bot.layout.region("sid.name_column")
        cur = f[y:y + h, x:x + w].astype("int16")
        if prev is not None and abs(cur - prev).mean() < 1.0:
            break
        prev = cur
        bot.sleep(0.1)


ROWS_PER_PAGE = 4       # one page drag moves the list exactly 4 accounts (measured; same as completeid)


def _page(bot, down=True):
    """One page of the account list, scrolled the way completeid/XpIncrease do it: a 0.5 s drag
    released while still moving. The list moves exactly 4 accounts and is still right away."""
    if down:
        bot.drag(bot.layout.point("sid.page_from"), bot.layout.point("sid.page_to"), 500)
    else:
        bot.drag(bot.layout.point("sid.page_up_from"), bot.layout.point("sid.page_up_to"), 500)


def _scroll(bot, down=True):
    _page(bot, down)
    bot.sleep(0.25)


def _list_index(bot, name):
    """Where the account is on the Accounts page (keep it in the game's list order)."""
    for i, a in enumerate(bot.accounts):
        if same_name(a["name"], name):
            return i
    return None


def read_player(bot, frame=None):
    """The in-game player name at the top left of the village ("" if unreadable)."""
    frame = bot.shot() if frame is None else frame
    text, conf = vision.text_reader.read_line(frame, bot.layout.region("home.player_name"))
    return text.strip() if text and conf > 0.6 else ""


def on_account(bot, account):
    """True if the village on screen is this account: its in-game name matches the one learned on
    an earlier visit; without a learned name, the account the bot last switched to."""
    player = account.get("player")
    unique = player and not any(a is not account and a.get("player") and same_name(a["player"], player)
                                for a in bot.accounts)
    if unique:
        seen = read_player(bot)
        if not seen:
            bot.sleep(0.6)                            # the name appears a moment after the village
            seen = read_player(bot)
        if seen:
            return same_name(seen, player)
    return bot.current_account == account["name"]


def switch_to(bot, account, state=None):
    """Switch to `account` (dict with "name"). Learns its Town Hall level. Returns True."""
    name = account["name"]
    if go_home(bot, 30) and on_account(bot, account):
        log.info("Already on %s", name)
        bot.current_account, bot.current_acc = name, account
        return True
    log.info("Switching to %s", name)
    started = time.monotonic()
    for k in [k for k in account if k.startswith("_")]:
        account.pop(k)                                # per-visit flags (army recipe set, ...)
    bot.status(account=name, action="Switching account")
    open_switcher(bot)
    save = state is not None or bot.state is not None   # (a test without a run has nothing to save to)
    if state is None:
        state = bot.state if bot.state is not None else {}
    state.pop("switcher_pages", None)                 # from the older, shorter scroll
    # each screen scrolls the list its own amount per drag: remember the pages per screen size
    native = space.native or (1920, 1080)
    pages = state.setdefault("switcher_at" if native == (1920, 1080) else f"switcher_at_{native[0]}x{native[1]}", {})

    def try_page():
        frame = bot.shot()
        visible = read_switcher(bot, frame)
        exact = [v for v in visible if normalise(v[0]) == normalise(name)]
        for text, pt, box in exact or visible:
            if same_name(text, name):
                th = read_town_hall(frame, box)
                if th:
                    account["th"] = th
                bot.tap(*pt, jitter=4)
                return True, visible
        return False, visible

    # 1) straight to its page: learned on an earlier visit, else from its place on the Accounts page
    index = _list_index(bot, name)
    # accounts per page drag: 4 on the PC; on other screens estimated from the accounts found there
    ratios = sorted(_list_index(bot, n) / p for n, p in pages.items() if p and _list_index(bot, n) is not None)
    per_page = ratios[len(ratios) // 2] if ratios and native != (1920, 1080) else ROWS_PER_PAGE
    target = pages.get(name, int(index // per_page) if index is not None else 0)
    for _ in range(target):
        _page(bot)                                    # the list stops at once: no wait in between
    if target:
        bot.sleep(0.25)
    found, visible = try_page()
    scrolled, went_up = target, False

    # 2) not there (list changed): search towards it, then the whole list
    if not found:
        seen = [i for i in (_list_index(bot, t) for t, _, _ in visible) if i is not None]
        first = (index is None or not seen or index > max(seen))
        for down in ((True, False) if first else (False, True)):
            last = None
            for _ in range(40):
                sig = tuple(t for t, _, _ in visible)
                if sig == last:
                    break                      # list stopped moving: reached the end
                last = sig
                _scroll(bot, down=down)
                scrolled += 1 if down else 0
                went_up = went_up or not down
                found, visible = try_page()
                if found:
                    break
            if found:
                break
    if not found:
        bot.save_error("account-not-found")
        go_home(bot)
        raise BotError(f"Account '{name}' not found in the Supercell ID list")

    if went_up:
        pages.pop(name, None)                         # up-drags are shorter: guess from the list next time
    else:
        pages[name] = scrolled                        # page drags from the top to reach it
    if save:
        config.save_state(state)
    if not go_home(bot, timeout=90):
        raise BotError(f"'{name}' did not finish loading")
    player = read_player(bot)
    if player and account.get("player") and not same_name(player, account["player"]):
        log.warning("%s shows the name '%s' (was '%s' last time)", name, player, account["player"])
    bot.current_account, bot.current_acc = name, account
    if player:
        account["player"] = player                    # in-game name, as shown in clan chat
    log.info("Now on %s (Town Hall %s) in %.0f s", name, account.get("th") or "?", time.monotonic() - started)
    return True


def scan_accounts(bot, max_pages=40):
    """Read every account name (and Town Hall) in the Supercell ID list, top to bottom."""
    open_switcher(bot)
    found = {}
    order = []
    last = None
    for _ in range(max_pages):
        frame = bot.shot()
        visible = read_switcher(bot, frame)
        for text, _, box in visible:
            key = next((k for k in order if same_name(found[k][0], text)), normalise(text))
            if key not in found:
                found[key] = (text, read_town_hall(frame, box))
                order.append(key)
            elif not found[key][1]:
                found[key] = (found[key][0], read_town_hall(frame, box))
        sig = tuple(t for t, _, _ in visible)
        if sig == last:
            break
        last = sig
        _scroll(bot, down=True)
    go_home(bot)
    return [found[k] for k in order]

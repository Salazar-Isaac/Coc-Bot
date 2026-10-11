"""Switch accounts through Settings -> Supercell ID, by reading the account names."""

import difflib
import logging
import re

import numpy as np

from .. import config
from ..core import vision
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
    if y + 56 + h + 4 > frame.shape[0]:
        return 0                                   # card cut off at the bottom of the panel
    text, _ = vision.text_reader.read_line(frame, (x, y + 56, 200, h + 4))
    m = re.search(r"(\d{1,2})\s*$", text)
    return int(m.group(1)) if m else 0


def open_switcher(bot):
    if not go_home(bot):
        raise BotError("Not on the home village")
    bot.tap_point("home.settings")
    if not bot.wait("settings/title", 8, interval=0.25):
        raise BotError("Settings did not open")
    bot.tap_point("settings.switch_id")
    if not bot.wait("sid/switch_id_label", 10, interval=0.25):
        raise BotError("Supercell ID panel did not open")
    # the list slides in: wait until the name column stops moving (max 1.2 s)
    prev = None
    for _ in range(8):
        f = bot.shot()
        x, y, w, h = bot.layout.region("sid.name_column")
        cur = f[y:y + h, x:x + w].astype("int16")
        if prev is not None and abs(cur - prev).mean() < 1.0:
            break
        prev = cur
        bot.sleep(0.15)


def _scroll(bot, down=True):
    a, b = bot.layout.point("sid.scroll_from"), bot.layout.point("sid.scroll_to")
    bot.swipe(a, b, 700) if down else bot.swipe(b, a, 700)
    bot.sleep(0.45)


def switch_to(bot, account, state=None):
    """Switch to `account` (dict with "name"). Learns its Town Hall level. Returns True."""
    name = account["name"]
    log.info("Switching to %s", name)
    for k in [k for k in account if k.startswith("_")]:
        account.pop(k)                                # per-visit flags (army recipe set, ...)
    bot.status(account=name, action="Switching account")
    open_switcher(bot)
    state = state if state is not None else {}
    pages = state.setdefault("switcher_pages", {})

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

    # 1) jump straight to the page where we found this account last time
    cached = pages.get(name, 0)
    for _ in range(cached):
        _scroll(bot, down=True)
    found, visible = try_page()
    scrolled = cached

    # 2) otherwise search down to the end, then up to the top
    if not found:
        for down in (True, False):
            last = None
            for _ in range(40):
                sig = tuple(t for t, _, _ in visible)
                if sig == last:
                    break                      # list stopped moving: reached the end
                last = sig
                _scroll(bot, down=down)
                scrolled += 1 if down else -1
                found, visible = try_page()
                if found:
                    break
            if found:
                break
    if not found:
        bot.save_error("account-not-found")
        go_home(bot)
        raise BotError(f"Account '{name}' not found in the Supercell ID list")

    pages[name] = max(0, scrolled)
    config.save_state(state)
    if not go_home(bot, timeout=90):
        raise BotError(f"'{name}' did not finish loading")
    bot.current_account = name
    log.info("Now on %s (Town Hall %s)", name, account.get("th") or "?")
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

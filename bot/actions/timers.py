"""When each account's builders and laboratories are free again.

The builder and lab menus list the upgrades in progress with the time they still need ("2d 4h",
"45m 10s"). After the flow has put an account's builders (or lab) to work, the shortest of these
times is remembered, so the flow can come back to that account as soon as one is free - also in
the middle of looting other accounts.
"""

import logging
import re
import time

from .. import config
from ..core import vision
from ..core.space import space

log = logging.getLogger("bot")

KINDS = ("builders", "lab", "builder_builders", "builder_lab")
_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_time(text):
    """Seconds in a game time like "2d 4h", "45m 10s", "3h" (None if it is not a time)."""
    t = re.sub(r"[^0-9a-z]", "", (text or "").lower())    # read as "11H-26M", "7d19H", "3d 15h"
    parts = re.findall(r"(\d+)([dhms])", t)
    if not parts or re.sub(r"\d+[dhms]", "", t):
        return None
    return sum(int(n) * _UNITS[u] for n, u in parts)


def progress_times(frame, cx=None):
    """Times of the upgrades in progress at the top of the open builder / lab side panel (above its
    "Suggested upgrades" / "Other upgrades"; since the 2026-10 UI they have no header of their own)."""
    from .upgrades import PANEL
    lines = sorted(vision.text_reader.read(frame, space.region(*PANEL)), key=lambda t: (t[2][1], t[2][0]))
    out = []
    for text, conf, box in lines:
        low = text.lower().replace(" ", "").rstrip(":")
        if low.endswith("upgrades") or low.endswith("research"):
            break                                       # the upgradable rows start here
        secs = parse_time(text)
        if secs:
            out.append(secs)
    return out


def _timers(bot):
    return bot.state.setdefault("timers", {}) if bot.state is not None else {}


def note_busy(bot, account, kind, where):
    """Everything of this kind is busy: open its menu, read when the first one is done, remember it."""
    from .panel import open_menu, read_page
    from .village import close_menu
    from .panel import note_builds
    times = read_page(bot.shot(), want_name=lambda r: False)[1] if open_menu(bot, where) else []
    close_menu(bot, where["safe"])
    note_builds(bot, account, kind, times, free=0)
    t = _timers(bot).setdefault(account["name"], {})
    if times:
        t[kind] = time.time() + min(times) + 20          # a little later: the game needs a moment
        log.info("%s: %s free again in %s", account["name"], kind.replace("_", " "), _fmt(min(times)))
    else:
        t.pop(kind, None)
    if bot.state is not None:
        config.save_state(bot.state)


def clear(bot, account, kind):
    """Nothing to start (nothing affordable): no reason to come back for it."""
    t = _timers(bot).get(account["name"], {})
    if t.pop(kind, None) is not None and bot.state is not None:
        config.save_state(bot.state)


def later(bot, account, kind, secs):
    """Look at this account's builders / lab again in `secs` (a visit that could not be done)."""
    _timers(bot).setdefault(account["name"], {})[kind] = time.time() + secs
    if bot.state is not None:
        config.save_state(bot.state)


def due(bot, names, kinds, unknown=False):
    """[(name, kind)] whose builders / lab are free by now, earliest first. unknown: an account whose
    builders were never looked at (no time remembered) counts as due too - first."""
    now = time.time()
    out = []
    for name in names:
        t = _timers(bot).get(name, {})
        for kind in kinds:
            at = t.get(kind)
            if at is None and unknown:
                out.append((0, name, kind))
            elif at is not None and at <= now:
                out.append((at, name, kind))
    return [(n, k) for _, n, k in sorted(out)]


def _fmt(secs):
    d, r = divmod(int(secs), 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return " ".join(p for p in (f"{d}d" if d else "", f"{h}h" if h else "", f"{m}m" if m and not d else "") if p) or "<1m"

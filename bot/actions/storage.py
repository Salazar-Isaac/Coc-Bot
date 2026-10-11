"""Storage capacity from the resource bars, and the "is this account full?" rule.

The bar next to each resource fills in proportion to amount / capacity (from the right,
by the icon). Measuring the filled length gives the capacity: capacity = amount / fill.
Measured on your accounts this is within about 0.1-1 % (best when the bar is nearly full,
which is exactly when the decision matters). The estimate is remembered per account
and refined whenever the bar is fuller, so an account whose storages are lower than its
Town Hall suggests is handled correctly: it is full when ITS storages are full.
"""

import logging

from ..core.space import space

log = logging.getLogger("bot")

# Base-screen geometry (1920x1080): bar left/right ends and two clean rows below the number.
BARS = {
    "gold":   {"left": 1585, "right": 1898, "rows": (64, 65)},
    "elixir": {"left": 1585, "right": 1898, "rows": (149, 150)},
    "dark":   {"left": 1666, "right": 1898, "rows": (232, 233)},
}
# Builder Base: same bars (no dark elixir); same geometry on the 1920x1080 screen.
BB_BARS = {"gold": BARS["gold"], "elixir": BARS["elixir"]}
SCAN_FROM = 1825          # just left of the resource icon


def _filled(px, res):
    b, g, r = int(px[0]), int(px[1]), int(px[2])
    if res == "gold":
        return r > 170 and g > 130 and b < 110
    if res == "elixir":
        return r > 140 and b > 140 and g < 130
    return g < 25 and b > g + 25 and r > g + 12          # dark purple


def fill_fraction(frame, res, bars=None):
    """How full the bar is (0..1), or None if it cannot be measured."""
    geo = (bars or BARS)[res]
    left = space.point(geo["left"], 0)[0]
    right = space.point(geo["right"], 0)[0]
    x0 = space.point(SCAN_FROM, 0)[0]
    rows = [space.point(0, r)[1] for r in geo["rows"]]
    h, w = frame.shape[:2]
    if not (0 < left < x0 < right <= w) or max(rows) >= h:
        return None
    start, miss, x = None, 0, x0
    while x > left - 3:
        if all(_filled(frame[y, x], res) for y in rows):
            start, miss = x, 0
        else:
            miss += 1
            if miss >= 4:
                break
        x -= 1
    if start is None:
        return 0.0
    return max(0.0, min(1.0, (right - start) / (right - left)))


def estimate(frame, res, amount, bars=None):
    """(capacity, fill) from this frame, or (None, fill)."""
    f = fill_fraction(frame, res, bars)
    if not amount or not f or f < 0.08:            # too little bar to measure reliably
        return None, f
    return int(round(amount / f)), f


def update_capacity(account, frame, amounts):
    """Refine the account's remembered capacities from the current bars. Returns {res: cap}."""
    caps = account.setdefault("capacity", {})
    fills = account.setdefault("capacity_fill", {})
    for res, amount in amounts.items():
        if amount is None:
            continue
        cap, f = estimate(frame, res, amount)
        if cap is None:
            continue
        old, old_f = caps.get(res), fills.get(res, 0)
        if f >= 0.995:
            cap = amount                               # bar completely full: amount is the capacity
        changed = old and abs(cap - old) / old > 0.03 and f >= 0.3   # storages upgraded / changed
        if old is None or f >= old_f or changed:
            if old is None or changed:
                log.info("%s %s storage capacity: about %s", account.get("name", "?"), res, f"{cap:,}")
            caps[res], fills[res] = cap, f
    return caps


def remaining(account, res, amount):
    cap = (account.get("capacity") or {}).get(res)
    if cap is None or amount is None:
        return None
    return max(0, cap - amount)

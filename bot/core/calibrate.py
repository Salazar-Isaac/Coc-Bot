"""How does this screen draw the game's interface?

Phones draw buttons bigger than the PC (e.g. 1.2x) and keep a margin at the sides for the
camera cut-out. On the home screen the bot finds the Attack button (bottom left) and the
Settings button (bottom right) at any size; their size gives the UI scale and their place
the side margins. The result is applied to the game space (space.set_ui) and remembered per
screen size in the run's state, so the next start works on any screen straight away.
"""

import logging
import time

import cv2

from . import vision
from .control import control
from .space import space

log = logging.getLogger("bot")

LEFT_REF = "home/attack_button"         # pinned bottom-left
RIGHT_REF = "home/settings_button"      # pinned bottom-right


def _best_scale(area, x0, y0, key, scales, shrink=1.0):
    """(score, scale, centre x, centre y) of the best match of any variant of key in `area`
    (whose top-left is x0, y0). shrink < 1 matches a smaller copy (fast first pass)."""
    best = (0.0, None, 0, 0)
    for k in vision.templates.variants(key) or [key]:
        base = vision.templates.image(k)
        for sc in scales:
            f = sc * shrink
            tpl = cv2.resize(base, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
            if tpl.shape[0] > area.shape[0] or tpl.shape[1] > area.shape[1]:
                continue
            res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
            _, s, _, loc = cv2.minMaxLoc(res)
            if s > best[0]:
                best = (float(s), sc, x0 + (loc[0] + tpl.shape[1] / 2) / shrink,
                        y0 + (loc[1] + tpl.shape[0] / 2) / shrink)
    return best


def _find(frame, key, region):
    """Half-size search over the scales, then full size around the best one."""
    x0, y0, w, h = region
    area = frame[y0:y0 + h, x0:x0 + w]
    small = cv2.resize(area, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    coarse = _best_scale(small, x0, y0, key, [0.7 + 0.05 * i for i in range(19)], shrink=0.5)
    if coarse[1] is None or coarse[0] < 0.6:
        return coarse
    _, c, cx, cy = coarse
    bw_, bh_ = vision.templates.image(key).shape[1::-1]
    m = int(max(bw_, bh_) * c * 0.8) + 20                 # look again only around that spot
    rx0, ry0 = max(0, int(cx - m)), max(0, int(cy - m))
    sub = frame[ry0:int(cy + m), rx0:int(cx + m)]
    return _best_scale(sub, rx0, ry0, key, [round(c + 0.01 * i, 2) for i in range(-4, 5)])


def measure(frame):
    """(ui, left, right) from a picture of the home village, or None if it is not one."""
    H, W = frame.shape[:2]
    bw, bh = space.base
    sl, kl, xl, yl = _find(frame, LEFT_REF, (0, int(H * 0.5), int(W * 0.35), H - int(H * 0.5)))
    sr, kr, xr, yr = _find(frame, RIGHT_REF, (int(W * 0.65), int(H * 0.35), W - int(W * 0.65), int(H * 0.6)))
    if sl < 0.75 or sr < 0.75 or abs(kl - kr) > 0.08:
        return None
    ui = round((kl + kr) / 2, 2)
    lx, ly, lw, lh = vision.templates.meta(LEFT_REF)["box"]
    rx, ry, rw, rh = vision.templates.meta(RIGHT_REF)["box"]
    left = xl - (lx + lw / 2) * ui
    right = W - xr - (bw - (rx + rw / 2)) * ui
    # both are pinned to the bottom: their height above it must fit the same scale
    for y, (by, bhh) in ((yl, (ly, lh)), (yr, (ry, rh))):
        if abs((H - y) - (bh - (by + bhh / 2)) * ui) > 25:
            return None
    if abs(ui - 1) < 0.03 and abs(left) < 10 and abs(right) < 10:
        return 1.0, 0, 0                                   # the profile's own look (PC)
    return ui, max(0, int(round(left))), max(0, int(round(right)))


def calibrate(bot, timeout=60):
    """Measure the interface on the home screen and apply it. Uses what was measured before for
    this screen size if the home screen does not show up. Returns (ui, left, right)."""
    bot.shot()
    key = f"{space.native[0]}x{space.native[1]}"
    known = (bot.state or {}).get("screens", {}).get(key)
    end = time.monotonic() + timeout
    while True:
        result = measure(bot.shot())
        if result:
            break
        if time.monotonic() > end:
            if known:
                result = tuple(known)
                log.info("Home screen not visible: using the interface size measured before for %s", key)
                break
            log.warning("Could not measure the interface size (home screen not visible); assuming the PC's")
            result = (1.0, 0, 0)
            break
        control.sleep(1.0)
    space.set_ui(*result)
    if bot.state is not None:                         # window sizes learned on this screen before
        space.windows = bot.state.setdefault("windows", {}).setdefault(key, space.windows or {})
    if result != (1.0, 0, 0) or known:
        log.info("Interface on this %s screen: %.2fx the PC's size, side margins %d / %d px", key, *result)
    if bot.state is not None:
        bot.state.setdefault("screens", {})[key] = list(result)
    return result

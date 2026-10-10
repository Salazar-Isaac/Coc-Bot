"""Find where troops can be dropped around the scouted base.

CoC forbids deploying on and right next to buildings (the "red zone"). We find
the base footprint (big non-grass blobs: buildings and walls) inside the map
diamond, cast rays from its centre, and put a deploy point a safety margin
beyond the farthest building on each ray. Points are kept inside the map
diamond (measured from the old bot's edge points, which are known to work) and
away from the on-screen buttons.

All coordinates are game space at full zoom-out; the village is centred, so the
base-screen geometry below is shifted with space.center().
"""

import math

import cv2
import numpy as np

from ..core.space import space

# Building grid diamond at full zoom-out on the 1920x1080 base screen (bottom half is taller:
# perspective). Bases can sit a little differently, so searches use it grown by MAP_GROW.
DIAMOND = {"cx": 974, "cy": 525, "half_w": 734, "half_h_top": 515, "half_h_bottom": 580}
MAP_GROW = 0.14

# Screen areas covered by UI during a battle (base-screen coordinates).
UI_BOXES = [
    (0, 0, 330, 260),        # attacker name + available loot
    (1640, 0, 280, 190),     # own resources
    (820, 0, 290, 95),       # battle timer
    (0, 800, 760, 110),      # End Battle / boost buttons
    (1640, 750, 280, 160),   # Next button / damage
    (0, 905, 1920, 175),     # troop bar
]


def valid_spot(frame, x, y):
    """Somewhere a tap can deploy: on screen, on the map, and not on a button."""
    h, w = frame.shape[:2]
    if not (0 <= x < w and 0 <= y < h) or not in_diamond(x, y, inset=-MAP_GROW + 0.02):
        return False
    for bx, by, bw, bh in UI_BOXES:
        rx, ry, rw, rh = space.region(bx, by, bw, bh)
        if rx - 15 <= x < rx + rw + 15 and ry - 15 <= y < ry + rh + 15:
            return False
    return True


def in_diamond(x, y, inset=0.0):
    d = DIAMOND
    cx, cy = space.center(d["cx"], d["cy"])
    hh = d["half_h_top"] if y < cy else d["half_h_bottom"]
    return abs(x - cx) / d["half_w"] + abs(y - cy) / hh <= 1.0 - inset


def _ui_mask(h, w):
    mask = np.zeros((h, w), np.uint8)
    for x, y, bw, bh in UI_BOXES:
        rx, ry, rw, rh = space.region(x, y, bw, bh)
        mask[max(0, ry):ry + rh, max(0, rx):rx + rw] = 255
    return mask


def _diamond_mask(h, w, inset=0.0):
    d = DIAMOND
    cx, cy = space.center(d["cx"], d["cy"])
    k = 1.0 - inset
    pts = np.array([[cx - d["half_w"] * k, cy], [cx, cy - d["half_h_top"] * k],
                    [cx + d["half_w"] * k, cy], [cx, cy + d["half_h_bottom"] * k]], np.int32)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [pts], 255)
    return mask


def building_mask(frame):
    """Pixels of the scouted base: the walled base (largest blob) plus buildings close to it.
    Grass, forest, and far-away scenery (cliffs, water, decorations) are left out."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue, sat = hsv[:, :, 0], hsv[:, :, 1]
    grass = (hue >= 28) & (hue <= 85) & (sat >= 60)          # lawn, tiles and forest (any brightness)
    mask = (~grass).astype(np.uint8) * 255
    mask &= _diamond_mask(h, w, inset=-MAP_GROW)
    mask &= cv2.bitwise_not(_ui_mask(h, w))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return np.zeros_like(mask)
    main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    # region around the main base: its bounding box grown by ~5 tiles
    mx, my, mw, mh = stats[main, :4]
    grow = 170
    keep = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 900:              # rocks, bushes, small decorations
            continue
        cx, cy = cents[i]
        if i == main or (mx - grow <= cx <= mx + mw + grow and my - grow <= cy <= my + mh + grow):
            keep[labels == i] = 255
    return keep


def deploy_line(frame, count=24, margin=70):
    """`count` points around the base, evenly by angle, just outside the red zone.
    Returns [] if no base was found."""
    mask = building_mask(frame)
    ys, xs = np.nonzero(mask)
    if len(xs) < 2000:
        return []
    cx, cy = float(np.median(xs)), float(np.median(ys))
    h, w = mask.shape
    ui = _ui_mask(h, w)
    max_r = int(math.hypot(w, h))
    points = []
    for i in range(count):
        a = 2 * math.pi * i / count
        dx, dy = math.cos(a), math.sin(a) * 0.75      # isometric view: flatter vertically
        far = 0
        for r in range(0, max_r, 4):
            x, y = int(cx + dx * r), int(cy + dy * r)
            if not (0 <= x < w and 0 <= y < h) or not in_diamond(x, y, inset=-MAP_GROW):
                break
            if mask[y, x]:
                far = r
        r = far + margin
        # walk back toward the base if the point left the map or sits under a button,
        # but never closer than most of the margin (that would be the red zone): then skip the ray
        while r >= far + margin * 0.7:
            x, y = int(cx + dx * r), int(cy + dy * r)
            if 0 <= x < w and 0 <= y < h and in_diamond(x, y, inset=-MAP_GROW + 0.02) and not ui[y, x]:
                points.append((x, y))
                break
            r -= 6
    return points


def draw(frame, points):
    """Debug image: building mask in red, deploy points in green."""
    out = frame.copy()
    m = building_mask(frame)
    out[m > 0] = (out[m > 0] * 0.5 + np.array([0, 0, 255]) * 0.5).astype(np.uint8)
    for x, y in points:
        cv2.circle(out, (x, y), 9, (0, 255, 0), 3)
    d = DIAMOND
    cx, cy = space.center(d["cx"], d["cy"])
    k = 1 + MAP_GROW
    pts = np.array([[cx - d["half_w"] * k, cy], [cx, cy - d["half_h_top"] * k], [cx + d["half_w"] * k, cy],
                    [cx, cy + d["half_h_bottom"] * k]], np.int32)
    cv2.polylines(out, [pts], True, (255, 255, 0), 2)
    return out

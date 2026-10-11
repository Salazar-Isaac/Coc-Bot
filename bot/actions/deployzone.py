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



import cv2
import numpy as np

from ..core.space import space

# Building grid diamond at full zoom-out on the 1920x1080 base screen (bottom half is taller:
# perspective). Bases can sit a little differently, so searches use it grown by MAP_GROW.
DIAMOND = {"cx": 974, "cy": 525, "half_w": 734, "half_h_top": 515, "half_h_bottom": 580}
MAP_GROW = 0.14
GROUND_TOLERANCE = 16     # Lab colour distance: closer than this to a ground colour = ground

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
    """Pixels of the scouted base, for ANY scenery: the ground's colours are learned from a strip
    along the inside of the map edge (almost always empty ground: grass, stone, sand, purple...),
    then everything that does not look like ground counts as buildings/walls. Only the main base
    blob and buildings near it are kept; far scenery and decorations are dropped."""
    h, w = frame.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    ui = _ui_mask(h, w)
    strip = (_diamond_mask(h, w, inset=0.0) > 0) & (_diamond_mask(h, w, inset=0.16) == 0) & (ui == 0)
    samples = lab[strip][::5]
    if len(samples) < 500:
        return np.zeros((h, w), np.uint8)
    k = 6
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(samples, k, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=k)
    ground = centers[counts > 0.08 * len(samples)]           # big colour groups = ground shades
    dist = np.min(np.stack([np.linalg.norm(lab - c, axis=2) for c in ground]), axis=0)
    mask = ((dist > GROUND_TOLERANCE) * 255).astype(np.uint8)
    mask &= _diamond_mask(h, w, inset=0.03)          # buildings stand inside the building grid
    mask &= cv2.bitwise_not(ui)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, labels_, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return np.zeros_like(mask)
    main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mx, my, mw, mh = stats[main, :4]
    grow = 150
    keep = labels_ == main
    for i in range(1, n):
        if i != main and stats[i, cv2.CC_STAT_AREA] >= 900:
            cx, cy = cents[i]
            if mx - grow <= cx <= mx + mw + grow and my - grow <= cy <= my + mh + grow:
                keep |= labels_ == i
    return (keep * 255).astype(np.uint8)


def deploy_line(frame, count=24, margin=70):
    """`count` points spread evenly on a line around the whole base, `margin` px (about two
    tiles) outside its outline, so they are just outside the no-deploy (red) area. Points that
    would be off the map or under a button are pulled back toward the base, never closer than
    most of the margin. Returns [] if no base was found."""
    mask = building_mask(frame)
    pts = cv2.findNonZero(mask)
    if pts is None or len(pts) < 2000:
        return []
    h, w = mask.shape
    hull = cv2.convexHull(pts)
    filled = np.zeros_like(mask)
    cv2.fillPoly(filled, [hull], 255)
    kx, ky = margin, int(margin * 0.75)                  # isometric view: flatter vertically
    grown = cv2.dilate(filled, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * kx + 1, 2 * ky + 1)))
    contours, _ = cv2.findContours(grown, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return []
    outline = max(contours, key=cv2.contourArea)[:, 0, :]
    m = cv2.moments(hull)
    cx, cy = (m["m10"] / m["m00"], m["m01"] / m["m00"]) if m["m00"] else (w / 2, h / 2)
    keep_out = cv2.dilate(filled, cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * int(kx * 0.7) + 1, 2 * int(ky * 0.7) + 1)))
    ui = _ui_mask(h, w)
    step = max(1, len(outline) // count)
    points = []
    for i in range(0, len(outline), step):
        x, y = int(outline[i][0]), int(outline[i][1])
        # pull back toward the base until the point is on the map and off the buttons
        for t in np.linspace(0, 0.6, 25):
            px, py = int(x + (cx - x) * t), int(y + (cy - y) * t)
            if not (0 <= px < w and 0 <= py < h) or keep_out[py, px]:
                break                                     # would be inside the red area: give up
            if in_diamond(px, py, inset=-MAP_GROW + 0.02) and not ui[py, px]:
                points.append((px, py))
                break
    return points[:count]


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

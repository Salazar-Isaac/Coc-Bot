"""Image recognition: template matching, digit reading and text OCR.

Templates live in assets/profiles/<profile>/templates/<group>/<name>.png. Their
search region and threshold are stored next to them in index.json, written by the
capture tool.
Matching uses OpenCV directly on one frame (the same algorithm pyautogui uses
with confidence=, without re-taking a screenshot for every image).
"""

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from .profile import profile
from .space import space

log = logging.getLogger("bot")

DEFAULT_THRESHOLD = 0.85


@dataclass
class Match:
    x: int          # centre, game space
    y: int
    score: float
    box: tuple      # (left, top, w, h)

    @property
    def center(self):
        return self.x, self.y


class TemplateStore:
    def __init__(self):
        self._lock = threading.RLock()       # re-entrant: image() -> path() -> _screen()
        self._images = {}
        self._scaled = {}
        self._variants = {}
        self.index = {}
        self.reload()

    def reload(self):
        with self._lock:
            self._images.clear()
            self._scaled = {}
            self._variants = {}
            if os.path.exists(profile.template_index):
                with open(profile.template_index, encoding="utf-8") as f:
                    self.index = json.load(f)
            else:
                self.index = {}

    def _screen(self):
        """(folder, index) of the overrides for the current screen size, or (None, {})."""
        native = space.native
        if native != getattr(self, "_screen_for", "?"):
            d = profile.screen_dir(native)
            idx = {}
            if d and os.path.exists(os.path.join(d, "index.json")):
                with open(os.path.join(d, "index.json"), encoding="utf-8") as f:
                    idx = json.load(f)
            with self._lock:
                self._screen_for, self._screen_dir, self._screen_index = native, d, idx
                self._images.clear()
                self._scaled = {}
                self._variants = {}
        return self._screen_dir, self._screen_index

    def absolute(self, key):
        """True if this template was captured on this very screen (no scaling or edge mapping)."""
        return self._screen()[1].get(key.split("~")[0]) is not None and key in self._screen()[1]

    def path(self, key):
        d, idx = self._screen()
        if d and key in idx:
            return os.path.join(d, *key.split("/")) + ".png"
        return os.path.join(profile.templates, *key.split("/")) + ".png"

    def has(self, key):
        return os.path.exists(self.path(key))

    def variants(self, key):
        """The template and its extra looks (e.g. another scenery): key, key~2, key~3 ..."""
        v = self._variants.get(key)
        if v is None:
            p = self.path(key)
            folder, base = os.path.dirname(p), os.path.basename(p)[:-4]
            v = [key] if os.path.exists(p) else []
            if os.path.isdir(folder):
                for f in sorted(os.listdir(folder)):
                    if f.startswith(base + "~") and f.endswith(".png"):
                        v.append(key + f[len(base):-4])
            self._variants[key] = v
        return v

    def next_variant(self, key):
        n = 2
        while os.path.exists(self.path(f"{key}~{n}")):
            n += 1
        return f"{key}~{n}"

    def image(self, key):
        with self._lock:
            img = self._images.get(key)
            if img is None:
                p = self.path(key)
                if not os.path.exists(p):
                    raise FileNotFoundError(f"Template not captured yet: {key}")
                img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
                self._images[key] = img
            return img

    def scaled(self, key):
        """The template at the size the game draws it on this screen (phones: bigger)."""
        k = 1.0 if self.absolute(key) else space.scale_of(key)
        if k == 1:
            return self.image(key)
        ck = (key, round(k, 3))
        with self._lock:
            img = self._scaled.get(ck)
        if img is None:
            base = self.image(key)
            img = cv2.resize(base, None, fx=k, fy=k, interpolation=cv2.INTER_LINEAR if k > 1 else cv2.INTER_AREA)
            with self._lock:
                self._scaled[ck] = img
        return img

    def meta(self, key):
        """A variant without its own settings uses the main template's (region, threshold)."""
        idx = self._screen()[1]
        if key in idx:
            return idx[key]
        return self.index.get(key) or self.index.get(key.split("~")[0], {})

    def region(self, key):
        """Where to look for the template on the current screen (game space), or None."""
        meta = self.meta(key)
        if not meta.get("region"):
            return None
        return tuple(meta["region"]) if self.absolute(key) else space.region(*meta["region"], name=key)

    def save(self, key, frame, box, region=None, threshold=DEFAULT_THRESHOLD, pad=60):
        """Cut `box` out of `frame` and store it as template `key`.

        The search region defaults to the box grown by `pad` pixels, so the bot
        only looks where the button actually appears.
        """
        x, y, w, h = [int(v) for v in box]
        crop = frame[y:y + h, x:x + w].copy()
        if space.ui != 1:                                  # stored at the profile's size
            crop = cv2.resize(crop, None, fx=1 / space.ui, fy=1 / space.ui, interpolation=cv2.INTER_AREA)
        p = self.path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        cv2.imencode(".png", crop)[1].tofile(p)
        if region is None:
            rx, ry = max(0, x - pad), max(0, y - pad)
            region = [rx, ry, min(frame.shape[1], x + w + pad) - rx, min(frame.shape[0], y + h + pad) - ry]
        # stored in base-screen coordinates so they work at any window size
        box_b, region_b = space.region_to_base(x, y, w, h), space.region_to_base(*region)
        with self._lock:
            self.index[key] = {"box": box_b, "region": region_b, "threshold": threshold}
            self._images.pop(key, None)
            self._scaled = {}
            self._variants = {}
            with open(profile.template_index, "w", encoding="utf-8") as f:
                json.dump(self.index, f, indent=2, sort_keys=True)

    def set_meta(self, key, **fields):
        with self._lock:
            self.index.setdefault(key, {}).update(fields)
            with open(profile.template_index, "w", encoding="utf-8") as f:
                json.dump(self.index, f, indent=2, sort_keys=True)


templates = TemplateStore()


def _crop(frame, region):
    if not region:
        return frame, 0, 0
    x, y, w, h = region
    x, y = max(0, int(x)), max(0, int(y))
    return frame[y:y + int(h), x:x + int(w)], x, y


def match_map(frame, key, region=None):
    """Return (score map, offset_x, offset_y, template) for `key` searched in `region`."""
    tpl = templates.scaled(key)
    meta = templates.meta(key)
    if region is None and meta.get("region"):
        region = templates.region(key)
    area, ox, oy = _crop(frame, region)
    if area.shape[0] < tpl.shape[0] or area.shape[1] < tpl.shape[1]:
        area, ox, oy = frame, 0, 0
    res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
    return res, ox, oy, tpl


def _brightness_ok(frame, box, tpl):
    """Popups dim the screen behind them, but TM_CCOEFF_NORMED ignores brightness,
    so a button behind a popup still "matches". Reject matches much darker or
    brighter than the template."""
    x, y, w, h = box
    ratio = (frame[y:y + h, x:x + w].mean() + 1) / (tpl.mean() + 1)
    return 0.75 <= ratio <= 1.3


COARSE_AREA = 250_000      # areas bigger than this are searched coarse-to-fine


def _coarse_fine(frame, key, region):
    """Same result as match_map + minMaxLoc, ~4x faster on big areas: find the best spot at half
    size, then measure the exact score at full size around it."""
    tpl = templates.scaled(key)
    meta = templates.meta(key)
    if region is None and meta.get("region"):
        region = templates.region(key)
    area, ox, oy = _crop(frame, region)
    th, tw = tpl.shape[:2]
    if area.shape[0] < th or area.shape[1] < tw:
        area, ox, oy = frame, 0, 0
    if area.shape[0] * area.shape[1] < COARSE_AREA or min(th, tw) < 24:
        res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        return score, loc, ox, oy, tpl
    small = cv2.resize(area, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    tsmall = cv2.resize(tpl, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    res = cv2.matchTemplate(small, tsmall, cv2.TM_CCOEFF_NORMED)
    best = None
    # refine the 3 best coarse spots (a near-miss at half size can win at full size)
    for _ in range(3):
        _, s, _, loc = cv2.minMaxLoc(res)
        x, y = loc[0] * 2, loc[1] * 2
        x0, y0 = max(0, x - 6), max(0, y - 6)
        sub = area[y0:y0 + th + 12, x0:x0 + tw + 12]
        if sub.shape[0] >= th and sub.shape[1] >= tw:
            r2 = cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED)
            _, s2, _, l2 = cv2.minMaxLoc(r2)
            if best is None or s2 > best[0]:
                best = (s2, (x0 + l2[0], y0 + l2[1]))
        lx, ly = loc
        res[max(0, ly - 4):ly + 5, max(0, lx - 4):lx + 5] = -1
    return best[0], best[1], ox, oy, tpl


def _find_one(frame, key, threshold, region, any_brightness):
    score, loc, ox, oy, tpl = _coarse_fine(frame, key, region)
    thr = threshold if threshold is not None else templates.meta(key).get("threshold", DEFAULT_THRESHOLD)
    if score < thr:
        return None
    h, w = tpl.shape[:2]
    x, y = loc[0] + ox, loc[1] + oy
    if not any_brightness and not _brightness_ok(frame, (x, y, w, h), tpl):
        return None
    return Match(x + w // 2, y + h // 2, float(score), (x, y, w, h))


def find(frame, key, threshold=None, region=None, any_brightness=False, learn=False):
    """Best match of template `key` (or any of its variants), or None if below the
    threshold (or dimmed behind a popup). learn=True (waiting for a window on a phone): if the
    window's size on this screen is not known yet, look for it at several sizes and remember it."""
    best = None
    for k in templates.variants(key) or [key]:
        m = _find_one(frame, k, threshold, region, any_brightness)
        if m and (best is None or m.score > best.score):
            best = m
    if best is None and learn and region is None:
        best = learn_window(frame, key, threshold)
    return best


_learn_tried = {}
_learn_seen = {}


def learn_window(frame, key, threshold=None):
    """A centred window's size on a phone: find its template at several sizes around the screen
    centre; the best size becomes the scale of every template and point of that window."""
    from .space import group_of
    g = group_of(key)
    if space.ui == 1 or not g or g in space.windows:
        return None
    now = time.monotonic()
    if now - _learn_tried.get(key, 0) < 0.8:
        return None
    _learn_tried[key] = now
    meta = templates.meta(key)
    thr = threshold if threshold is not None else meta.get("threshold", DEFAULT_THRESHOLD)
    best = None
    for sc in [0.85 + 0.03 * i for i in range(17)]:                  # 0.85 .. 1.33
        space.windows[g] = sc
        region = space.region(*meta["region"], name=key) if meta.get("region") else None
        if region:
            x, y, w, h = region
            pad_x, pad_y = int(w * 0.3) + 40, int(h * 0.3) + 40      # a little room for rounding
            region = (max(0, x - pad_x), max(0, y - pad_y), w + 2 * pad_x, h + 2 * pad_y)
        tpl = cv2.resize(templates.image(key), None, fx=sc, fy=sc, interpolation=cv2.INTER_LINEAR)
        area, ox, oy = _crop(frame, region)
        if area.shape[0] < tpl.shape[0] or area.shape[1] < tpl.shape[1]:
            continue
        _, s, _, loc = cv2.minMaxLoc(cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED))
        if s >= thr and (best is None or s > best[0]):
            h, w = tpl.shape[:2]
            best = (s, sc, Match(ox + loc[0] + w // 2, oy + loc[1] + h // 2, float(s), (ox + loc[0], oy + loc[1], w, h)))
    space.windows.pop(g, None)
    if not best:
        return None
    # windows zoom in when they open: only a size seen twice in a row is the real one
    sc = round(best[1], 2)
    seen = _learn_seen.get(g)
    _learn_seen[g] = sc
    if seen is not None and abs(seen - sc) <= 0.03:
        space.windows[g] = sc
        with templates._lock:
            templates._scaled = {}
        log.info("Window '%s' is drawn at %.2fx on this screen", g, sc)
    return best[2]


def find_scaled(frame, key, scales=None, threshold=None, region=None):
    """Like find(), but tries the template at several sizes (for things drawn at different
    zoom levels, e.g. the boat icon). Returns (Match, scale) or (None, None)."""
    tpl0 = templates.scaled(key)
    meta = templates.meta(key)
    if region is None and meta.get("region"):
        region = templates.region(key)
    area, ox, oy = _crop(frame, region)
    thr = threshold if threshold is not None else meta.get("threshold", DEFAULT_THRESHOLD)
    best = (None, None)
    for sc in scales or [0.6 + 0.05 * i for i in range(17)]:
        tpl = cv2.resize(tpl0, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR)
        if area.shape[0] < tpl.shape[0] or area.shape[1] < tpl.shape[1]:
            continue
        res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
        _, s, _, loc = cv2.minMaxLoc(res)
        if s >= thr and (best[0] is None or s > best[0].score):
            h, w = tpl.shape[:2]
            x, y = loc[0] + ox, loc[1] + oy
            best = (Match(x + w // 2, y + h // 2, float(s), (x, y, w, h)), sc)
    return best


def score(frame, key, region=None):
    return max(float(_coarse_fine(frame, k, region)[0]) for k in (templates.variants(key) or [key]))


def find_all(frame, key, threshold=None, region=None, max_results=20, any_brightness=False):
    """All non-overlapping matches above threshold, top to bottom."""
    res, ox, oy, tpl = match_map(frame, key, region)
    thr = threshold if threshold is not None else templates.meta(key).get("threshold", DEFAULT_THRESHOLD)
    h, w = tpl.shape[:2]
    res = res.copy()
    out = []
    while len(out) < max_results:
        _, s, _, loc = cv2.minMaxLoc(res)
        if s < thr:
            break
        x, y = loc[0] + ox, loc[1] + oy
        if any_brightness or _brightness_ok(frame, (x, y, w, h), tpl):
            out.append(Match(x + w // 2, y + h // 2, float(s), (x, y, w, h)))
        x0, y0 = max(0, loc[0] - w // 2), max(0, loc[1] - h // 2)
        res[y0:loc[1] + h // 2 + 1, x0:loc[0] + w // 2 + 1] = -1
    out.sort(key=lambda m: (m.y, m.x))
    return out


# --- digit reader (resource numbers) -----------------------------------------------

class DigitReader:
    """Reads Clash of Clans numbers by comparing each digit with saved digit images.

    The game draws numbers in one fixed font (white / cream / pink fill with a dark
    outline), so this is faster and more reliable than general OCR.
    Digit images: assets/profiles/<profile>/digits/<digit>_<anything>.png
    """

    SIZE = (24, 30)      # every glyph is normalised to this (w, h)
    ASPECT = 0.8         # glyphs are padded to this width/height ratio first
    MIN_LEVEL = 170      # a pixel is "text" when all three colour channels are this bright

    def __init__(self):
        self._templates = None

    def reload(self):
        self._templates = None

    def _load(self):
        out = []
        if os.path.isdir(profile.digits):
            for name in sorted(os.listdir(profile.digits)):
                if name.endswith(".png") and (name[0].isdigit() or name.startswith("slash")):
                    img = cv2.imdecode(np.fromfile(os.path.join(profile.digits, name), dtype=np.uint8),
                                       cv2.IMREAD_GRAYSCALE)
                    out.append(("/" if name.startswith("slash") else name[0], cv2.resize(img, self.SIZE)))
        self._templates = out

    @property
    def ready(self):
        if self._templates is None:
            self._load()
        return len({d for d, _ in self._templates if d.isdigit()}) == 10

    def _normalise(self, glyph):
        h, w = glyph.shape
        target_w = max(w, int(round(h * self.ASPECT)))
        pad = target_w - w
        glyph = cv2.copyMakeBorder(glyph, 0, 0, pad // 2, pad - pad // 2, cv2.BORDER_CONSTANT, value=0)
        return cv2.resize(glyph, self.SIZE, interpolation=cv2.INTER_AREA)

    def glyphs(self, frame, region, min_level=None, color="white"):
        """Cut out each digit in `region`, left to right. Returns [(image, box)].
        color "white": white/cream/pink game numbers; "sale": the bright green discounted prices."""
        area, ox, oy = _crop(frame, region)
        level = min_level or self.MIN_LEVEL
        if color == "sale":                     # bright saturated green (hue ~47), any shade of it
            hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
            h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
            binary = (((h >= 35) & (h <= 62) & (s >= 170) & (v >= 190)) * 255).astype(np.uint8)
        else:
            binary = ((area.min(axis=2) >= level) * 255).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        comps = [stats[i] for i in range(1, n)
                 if stats[i][cv2.CC_STAT_AREA] >= 12 and stats[i][cv2.CC_STAT_WIDTH] >= 4]
        if not comps:
            return []
        median_h = float(np.median([s[cv2.CC_STAT_HEIGHT] for s in comps]))
        median_cy = float(np.median([s[cv2.CC_STAT_TOP] + s[cv2.CC_STAT_HEIGHT] / 2 for s in comps]))
        keep = []
        for l, t, w, h, _ in comps:
            # same height as the other digits and on the same baseline -> a digit, else noise
            if abs(h - median_h) <= 0.25 * median_h and abs(t + h / 2 - median_cy) <= 0.3 * median_h:
                keep.append((l, t, w, h))
        keep.sort()
        return [(self._normalise(binary[t:t + h, l:l + w]), (l + ox, t + oy, w, h)) for l, t, w, h in keep]

    def classify(self, glyph):
        if self._templates is None:
            self._load()
        best, best_score = None, -1.0
        for digit, tpl in self._templates:
            s = float(cv2.matchTemplate(glyph, tpl, cv2.TM_CCOEFF_NORMED)[0][0])
            if s > best_score:
                best, best_score = digit, s
        return best, best_score

    def read(self, frame, region, min_score=0.6, min_level=None, color="white"):
        """The number in `region`, or None if it could not be read confidently."""
        if not self.ready:
            raise RuntimeError("Digit images missing: capture them in the Templates tab")
        found = [self.classify(g) for g, _ in self.glyphs(frame, region, min_level, color)]
        # a weak glyph at either end is usually a speck of background: drop it
        while found and found[0][1] < min_score:
            found.pop(0)
        while found and found[-1][1] < min_score:
            found.pop()
        if not found or any(s < min_score for _, s in found) or any(d == "/" for d, _ in found):
            return None
        return int("".join(d for d, _ in found))

    def read_fraction(self, frame, region, min_score=0.6, min_level=None):
        """'34/50' -> (34, 50), or None."""
        if not self.ready:
            return None
        found = [self.classify(g) for g, _ in self.glyphs(frame, region, min_level)]
        text = "".join(d for d, s in found if s >= min_score)
        m = re.fullmatch(r"(\d+)/(\d+)", text)
        return (int(m.group(1)), int(m.group(2))) if m else None


digits = DigitReader()


# --- text OCR (account names etc.) ------------------------------------------------

class TextReader:
    """RapidOCR (PaddleOCR models on ONNX Runtime). Loaded on first use."""

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def _get(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()
        return self._engine

    def read(self, frame, region=None):
        """Find and read all text in `region`. Returns [(text, score, (x, y, w, h))] in game space."""
        area, ox, oy = _crop(frame, region)
        if area.shape[0] < 8 or area.shape[1] < 8:
            return []
        with self._lock:
            result, _ = self._get()(area)
        out = []
        for pts, text, conf in result or []:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x, y = int(min(xs)) + ox, int(min(ys)) + oy
            out.append((text, float(conf), (x, y, int(max(xs) - min(xs)), int(max(ys) - min(ys)))))
        return out

    def read_line(self, frame, region):
        """Read a single known line of text (no detection step: faster)."""
        area, _, _ = _crop(frame, region)
        if area.shape[0] < 8 or area.shape[1] < 8:
            return "", 0.0
        with self._lock:
            result, _ = self._get()(area, use_det=False, use_cls=False, use_rec=True)
        if not result:
            return "", 0.0
        text, conf = result[0][0], result[0][1]
        return text, float(conf)


text_reader = TextReader()

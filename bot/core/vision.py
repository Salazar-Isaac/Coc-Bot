"""Image recognition: template matching, digit reading and text OCR.

Templates live in assets/profiles/<profile>/templates/<group>/<name>.png. Their
search region and threshold are stored next to them in index.json, written by the
capture tool.
Matching uses OpenCV directly on one frame (the same algorithm pyautogui uses
with confidence=, without re-taking a screenshot for every image).
"""

import json
import os
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from .profile import profile

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
        self._lock = threading.Lock()
        self._images = {}
        self.index = {}
        self.reload()

    def reload(self):
        with self._lock:
            self._images.clear()
            if os.path.exists(profile.template_index):
                with open(profile.template_index, encoding="utf-8") as f:
                    self.index = json.load(f)
            else:
                self.index = {}

    def path(self, key):
        return os.path.join(profile.templates, *key.split("/")) + ".png"

    def has(self, key):
        return os.path.exists(self.path(key))

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

    def meta(self, key):
        return self.index.get(key, {})

    def save(self, key, frame, box, region=None, threshold=DEFAULT_THRESHOLD, pad=60):
        """Cut `box` out of `frame` and store it as template `key`.

        The search region defaults to the box grown by `pad` pixels, so the bot
        only looks where the button actually appears.
        """
        x, y, w, h = [int(v) for v in box]
        crop = frame[y:y + h, x:x + w]
        p = self.path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        cv2.imencode(".png", crop)[1].tofile(p)
        if region is None:
            rx, ry = max(0, x - pad), max(0, y - pad)
            region = [rx, ry, min(frame.shape[1], x + w + pad) - rx, min(frame.shape[0], y + h + pad) - ry]
        with self._lock:
            self.index[key] = {"box": [x, y, w, h], "region": [int(v) for v in region], "threshold": threshold}
            self._images.pop(key, None)
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
    tpl = templates.image(key)
    meta = templates.meta(key)
    if region is None:
        region = meta.get("region")
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


def find(frame, key, threshold=None, region=None, any_brightness=False):
    """Best match of template `key`, or None if below its threshold (or dimmed)."""
    res, ox, oy, tpl = match_map(frame, key, region)
    _, score, _, loc = cv2.minMaxLoc(res)
    thr = threshold if threshold is not None else templates.meta(key).get("threshold", DEFAULT_THRESHOLD)
    if score < thr:
        return None
    h, w = tpl.shape[:2]
    x, y = loc[0] + ox, loc[1] + oy
    if not any_brightness and not _brightness_ok(frame, (x, y, w, h), tpl):
        return None
    return Match(x + w // 2, y + h // 2, float(score), (x, y, w, h))


def score(frame, key, region=None):
    res, *_ = match_map(frame, key, region)
    return float(res.max())


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
                if name.endswith(".png") and name[0].isdigit():
                    img = cv2.imdecode(np.fromfile(os.path.join(profile.digits, name), dtype=np.uint8),
                                       cv2.IMREAD_GRAYSCALE)
                    out.append((name[0], cv2.resize(img, self.SIZE)))
        self._templates = out

    @property
    def ready(self):
        if self._templates is None:
            self._load()
        return len({d for d, _ in self._templates}) == 10

    def _normalise(self, glyph):
        h, w = glyph.shape
        target_w = max(w, int(round(h * self.ASPECT)))
        pad = target_w - w
        glyph = cv2.copyMakeBorder(glyph, 0, 0, pad // 2, pad - pad // 2, cv2.BORDER_CONSTANT, value=0)
        return cv2.resize(glyph, self.SIZE, interpolation=cv2.INTER_AREA)

    def glyphs(self, frame, region, min_level=None):
        """Cut out each digit in `region`, left to right. Returns [(image, box)]."""
        area, ox, oy = _crop(frame, region)
        level = min_level or self.MIN_LEVEL
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
        best, best_score = None, -1.0
        for digit, tpl in self._templates:
            s = float(cv2.matchTemplate(glyph, tpl, cv2.TM_CCOEFF_NORMED)[0][0])
            if s > best_score:
                best, best_score = digit, s
        return best, best_score

    def read(self, frame, region, min_score=0.6, min_level=None):
        """The number in `region`, or None if it could not be read confidently."""
        if not self.ready:
            raise RuntimeError("Digit images missing: capture them in the Templates tab")
        found = [self.classify(g) for g, _ in self.glyphs(frame, region, min_level)]
        # a weak glyph at either end is usually a speck of background: drop it
        while found and found[0][1] < min_score:
            found.pop(0)
        while found and found[-1][1] < min_score:
            found.pop()
        if not found or any(s < min_score for _, s in found):
            return None
        return int("".join(d for d, _ in found))


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

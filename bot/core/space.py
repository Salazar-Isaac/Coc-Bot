"""Game space: the screen as the bot sees it, for any window size or aspect ratio.

Templates, click points and read regions are measured on the profile's base
screen (1920x1080 by default). Clash of Clans scales its interface uniformly
(by the smaller of width/1920 and height/1080) and pins buttons to the screen
edges, while the village stays centred. So the bot:

  1. scales the device image uniformly so it is 1080 tall (or 1920 wide),
     giving a game space of e.g. 1920x1080, 2400x1080 (phone) or 1920x1200 (16:10);
  2. moves edge-pinned coordinates by the extra width/height: things in the left
     third stay, the right third moves right, the middle moves half;
  3. keeps battlefield points (deploy positions) centred.

Phones draw the interface bigger than the PC does (the "UI scale", e.g. 1.2) and keep a
margin at the sides for the camera cut-out. Both are measured on the home screen when a
run starts (see calibrate.py) and applied here: buttons, regions and templates are scaled
by `ui` and pinned to the edges of the safe area. With the PC's 16:9 screen all of this
is the identity, so nothing changes there.
"""

import logging

from .profile import profile

log = logging.getLogger("bot")

# Windows drawn in the middle of the screen (Settings, army, popups ...). On a phone each one has
# its own size (e.g. Settings 1.0x, army 1.15x the PC's), learned the first time it is waited for.
WINDOW_GROUPS = {"settings", "army", "popup", "request", "shop", "results", "chest", "lab", "upgrade", "clan",
                 "dialog", "attack_menu"}
KIND_OVERRIDE = {"battle/confirm_okay": "settings"}     # the Okay dialog: a small centred window


def group_of(name):
    """'army/close' or 'army.close' -> 'army' (the window it belongs to), or None for the HUD."""
    if name in KIND_OVERRIDE:
        return KIND_OVERRIDE[name]
    g = name.replace(".", "/").split("/")[0]
    return g if g in WINDOW_GROUPS else None


class Space:
    def __init__(self):
        self.native = None          # (w, h) of the device in its own pixels
        self.scale = 1.0            # native pixels per game-space pixel
        self.w, self.h = profile.size
        self.ui = 1.0               # interface size relative to the profile (phones: bigger)
        self.left = 0               # safe-area margins at the sides (camera cut-out), game space
        self.right = 0
        self._calibrated = {}       # native size -> (ui, left, right)
        self.windows = {}           # window group -> its scale on this screen (phones; learned)

    @property
    def base(self):
        return profile.size

    def update(self, native_w, native_h):
        bw, bh = self.base
        s = min(native_w / bw, native_h / bh)
        w, h = round(native_w / s), round(native_h / s)
        if (native_w, native_h) != self.native:
            self.native = (native_w, native_h)
            self.scale, self.w, self.h = s, w, h
            self.ui, self.left, self.right = self._calibrated.get((native_w, native_h), (1.0, 0, 0))
            log.info("Game screen %dx%d (aspect %.2f) -> game space %dx%d, scale %.3f",
                     native_w, native_h, native_w / native_h, w, h, s)
        return w, h

    def set_ui(self, ui, left=0, right=0):
        """Interface scale and side margins for the current screen size (from calibrate.py)."""
        self.ui, self.left, self.right = float(ui), int(left), int(right)
        if self.native:
            self._calibrated[self.native] = (self.ui, self.left, self.right)

    @property
    def dx(self):
        return self.w - self.base[0]

    @property
    def dy(self):
        return self.h - self.base[1]

    def s(self, length):
        """A length measured on the base screen (button size, offset from a button) in game space."""
        return int(round(length * self.ui))

    def scale_of(self, name):
        """How much bigger than on the PC the game draws this template / point."""
        if self.ui == 1:
            return 1.0
        g = group_of(name)
        return self.windows.get(g, 1.0) if g else self.ui

    def _win(self, x, y, k):
        bw, bh = self.base
        return self.w / 2 + (x - bw / 2) * k, self.h / 2 + (y - bh / 2) * k

    # --- base -> game space ----------------------------------------------------------
    def _ax(self, x, ref=None):
        ref = x if ref is None else ref
        bw, k = self.base[0], self.ui
        if ref < bw / 3:
            return self.left + x * k
        if ref > 2 * bw / 3:
            return self.w - self.right - (bw - x) * k
        return (self.left + self.w - self.right) / 2 + (x - bw / 2) * k

    def _ay(self, y, ref=None):
        ref = y if ref is None else ref
        bh, k = self.base[1], self.ui
        if ref < bh / 3:
            return y * k
        if ref > 2 * bh / 3:
            return self.h - (bh - y) * k
        return self.h / 2 + (y - bh / 2) * k

    def point(self, x, y, name=None):
        """A UI point measured on the base screen, pinned to its nearest edge (a point of a centred
        window - name like "army.close" - stays centred, at that window's scale)."""
        if name and self.ui != 1 and group_of(name):
            px, py = self._win(x, y, self.scale_of(name))
            return round(px), round(py)
        return round(self._ax(x)), round(self._ay(y))

    def region(self, x, y, w, h, name=None):
        """A UI region measured on the base screen, pinned by its centre."""
        cx, cy = x + w / 2, y + h / 2
        if name and self.ui != 1 and group_of(name):
            k = self.scale_of(name)
            px, py = self._win(cx, cy, k)
            return round(px - w * k / 2), round(py - h * k / 2), int(round(w * k)), int(round(h * k))
        k = self.ui
        return (round(self._ax(cx) - w * k / 2), round(self._ay(cy) - h * k / 2),
                int(round(w * k)), int(round(h * k)))

    def center(self, x, y):
        """A battlefield/village point: stays centred."""
        return round(x + self.dx / 2), round(y + self.dy / 2)

    # --- game space -> base (when saving captures) ---------------------------------------
    def _bx(self, x):
        bw, k = self.base[0], self.ui
        if x < self.left + bw / 3 * k:
            return (x - self.left) / k
        if x > self.w - self.right - bw / 3 * k:
            return bw - (self.w - self.right - x) / k
        return bw / 2 + (x - (self.left + self.w - self.right) / 2) / k

    def _by(self, y):
        bh, k = self.base[1], self.ui
        if y < bh / 3 * k:
            return y / k
        if y > self.h - bh / 3 * k:
            return bh - (self.h - y) / k
        return bh / 2 + (y - self.h / 2) / k

    def region_to_base(self, x, y, w, h):
        if self.dx == 0 and self.dy == 0 and self.ui == 1 and not self.left and not self.right:
            return [int(x), int(y), int(w), int(h)]
        k = self.ui
        cx, cy = self._bx(x + w / 2), self._by(y + h / 2)
        bw, bh = w / k, h / k
        return [int(round(cx - bw / 2)), int(round(cy - bh / 2)), int(round(bw)), int(round(bh))]


space = Space()

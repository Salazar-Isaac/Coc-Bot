"""Screen profiles.

A profile is everything that depends on how the game looks on one screen size:
template images, digit images and the layout (click points and read regions).
The default profile is Google Play Games at 1920x1080. An emulator set to
1920x1080 can usually share it; a phone with another aspect ratio gets its own.

    assets/profiles/<name>/profile.json     {"width": 1920, "height": 1080}
    assets/profiles/<name>/templates/...    captured images + index.json
    assets/profiles/<name>/digits/0-9.png
    assets/profiles/<name>/layout.json      points and regions (overrides code defaults)
"""

import json
import os

from .. import paths

DEFAULT_PROFILE = "pc-1920x1080"


class Profile:
    def __init__(self, name=DEFAULT_PROFILE):
        self.use(name)

    def use(self, name):
        self.name = name
        self.dir = os.path.join(paths.PROFILES, name)
        self.templates = os.path.join(self.dir, "templates")
        self.template_index = os.path.join(self.templates, "index.json")
        self.digits = os.path.join(self.dir, "digits")
        self.layout_path = os.path.join(self.dir, "layout.json")
        for d in (self.templates, self.digits):
            os.makedirs(d, exist_ok=True)

        meta_path = os.path.join(self.dir, "profile.json")
        if not os.path.exists(meta_path):
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({"width": 1920, "height": 1080}, f, indent=2)
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        self.width, self.height = int(meta["width"]), int(meta["height"])

    @property
    def size(self):
        return self.width, self.height

    @staticmethod
    def available():
        return sorted(d for d in os.listdir(paths.PROFILES) if os.path.isdir(os.path.join(paths.PROFILES, d)))


profile = Profile()

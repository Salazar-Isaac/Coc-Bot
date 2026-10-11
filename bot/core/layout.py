"""Click points and read regions in game space (1920x1080 for the default profile).

Defaults below were measured on Google Play Games at 1920x1080. A profile can
override any entry in assets/profiles/<profile>/layout.json:
    {"points": {"home.attack": [105, 975]}, "regions": {...}}
"""

import copy
import json
import os

from .profile import profile
from .space import space

DEFAULT_LAYOUT = {
    "points": {
        "home.attack": [105, 975],
        "home.settings": [1855, 830],
        "home.chat": [65, 490],
        "home.army": [65, 830],
        "home.safe": [1830, 420],          # empty forest, safe to tap to close popups
        "attack_menu.find_match": [273, 745],
        "attack_menu.close": [1400, 540],  # tapping the village beside the menu closes it
        "army.attack": [1620, 918],
        "army.close": [1762, 147],
        "scout.next": [1775, 820],
        "scout.end_battle": [115, 848],
        "settings.switch_id": [1237, 228],
        "settings.close": [1545, 118],
        "sid.close": [1866, 53],
        "sid.scroll_from": [1620, 1010],
        "sid.scroll_to": [1620, 610],
        "chat.close": [655, 497],
        "chat.scroll_from": [300, 300],      # swipe down in the chat = older messages
        "chat.scroll_to": [300, 760],
        "donate.close": [300, 240],          # a spot in the chat beside the donate window
        "popup.close_x": [1615, 155],        # the X of big popups (daily reward, offers)
    },
    "regions": {
        "home.gold": [1600, 28, 230, 44],
        "home.elixir": [1600, 112, 230, 46],
        "home.dark": [1680, 196, 150, 44],
        "home.gems": [1700, 278, 140, 44],
        "scout.gold": [78, 122, 220, 34],
        "scout.elixir": [78, 170, 220, 34],
        "scout.dark": [78, 217, 220, 34],
        "sid.list": [1345, 520, 560, 560],
        "sid.name_column": [1460, 520, 320, 560],
        "battle.troop_bar": [260, 915, 1660, 160],
    },
}


class Layout:
    def __init__(self):
        self.reload()

    def reload(self):
        data = copy.deepcopy(DEFAULT_LAYOUT)
        if os.path.exists(profile.layout_path):
            with open(profile.layout_path, encoding="utf-8") as f:
                own = json.load(f)
            for section in ("points", "regions"):
                data[section].update(own.get(section, {}))
        self.points = data["points"]
        self.regions = data["regions"]

    def point(self, name):
        """A click point in the current game space (pinned to its screen edge)."""
        return space.point(*self.points[name])

    def region(self, name):
        """A read region in the current game space (pinned to its screen edge)."""
        return space.region(*self.regions[name])


layout = Layout()

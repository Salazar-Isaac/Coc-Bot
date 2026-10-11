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
        "home.safe": [1830, 420],          # home village: forest edge (NOT 330: that is the gems counter -> Shop)
        "bb.safe": [1450, 38],             # Builder Base: sky/cliff above the island (the boat can be at the right edge)
        "popup.shield_continue": [960, 902],
        "shop.close": [1857, 66],
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
        "sid.page_from": [1643, 1031],     # one drag 1031 -> 390 in 0.5 s = exactly 4 accounts down
        "sid.page_to": [1643, 390],
        "sid.page_up_from": [1643, 545],   # upwards the drag must start inside the list (about 3 accounts)
        "sid.page_up_to": [1643, 1078],
        "chat.close": [655, 497],
        "chat.scroll_from": [300, 300],      # swipe down in the chat = older messages
        "chat.scroll_to": [300, 760],
        "donate.close": [1660, 640],         # village right of the donate window (it moves up and down)
        "popup.close_x": [1615, 155],        # the X of big popups (daily reward, offers)
        "top.builders_menu": [960, 50],      # builder counter -> upgrades list
        "army.recipes_arrow": [1140, 155],   # Saved Recipes drop-down arrow in the army screen
        "home.boat": [450, 925],             # boat to the Builder Base (home village, zoomed out)
        "bb.boat": [1620, 120],              # boat back home (Builder Base, zoomed out; top right)
        "bb.attack": [105, 975],
        "bb.builders_menu": [1080, 50],
        "bb.lab_menu": [880, 50],
        "bb.army": [65, 830],                # Builder Base army button (left)
        "bb.army_clear": [1493, 575],        # red trash button in "Choose Army"
        "bb.army_close": [1600, 220],
        "dialog.cancel": [785, 668],         # orange Cancel of a two-button confirmation
        "request.cancel": [768, 722],        # Cancel of the request window
        "top.lab_menu": [760, 50],           # laboratory counter -> research list
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
        "top.builders": [950, 32, 66, 40],   # "1/5" free builders
        "army.recipe_list": [865, 210, 550, 560],   # the Saved Recipes drop-down list
        "bb.gold": [1600, 28, 230, 44],
        "bb.elixir": [1600, 112, 230, 46],
        "bb.stars": [75, 900, 100, 42],      # star bonus "4/8" on the Attack button
        "bb.builders": [1075, 32, 70, 40],
        "bb.lab": [875, 32, 70, 40],
        "home.player_name": [115, 14, 250, 32],      # in-game name next to the level badge
        "army.request_timer": [1688, 830, 112, 36],   # "10m" under the gem price while on cooldown
        "bb.reward_gold": [1140, 650, 150, 45],
        "top.lab": [752, 32, 66, 40],        # "0/1" free laboratory
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

    def _screen(self):
        """Points/regions measured on this very screen (screens/<W>x<H>/layout.json), if any."""
        native = space.native
        if native != getattr(self, "_screen_for", "?"):
            self._screen_for, self._own = native, {"points": {}, "regions": {}}
            d = profile.screen_dir(native)
            p = d and os.path.join(d, "layout.json")
            if p and os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    own = json.load(f)
                for section in ("points", "regions"):
                    self._own[section].update(own.get(section, {}))
        return self._own

    def point(self, name):
        """A click point in the current game space (pinned to its screen edge)."""
        own = self._screen()["points"].get(name)
        return tuple(own) if own else space.point(*self.points[name], name=name)

    def region(self, name):
        """A read region in the current game space (pinned to its screen edge)."""
        own = self._screen()["regions"].get(name)
        return tuple(own) if own else space.region(*self.regions[name], name=name)


layout = Layout()

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
        "home.settings": [85, 100],   # profile picture (top left): Settings is a tab of the profile menu since the 2026-10 UI
        "home.chat": [85, 545],   # clan chat (shield with a speech bubble, left)
        "home.army": [65, 830],
        "home.safe": [1830, 420],          # home village: forest edge (NOT 330: that is the gems counter -> Shop)
        "bb.safe": [1640, 470],            # Builder Base: forest right of the island (NOT the top: the boat is there)
        "popup.shield_continue": [960, 902],
        "shop.close": [1857, 66],
        "attack_menu.find_match": [273, 745],
        "attack_menu.close": [1400, 540],  # tapping the village beside the menu closes it
        "army.attack": [1620, 918],
        "army.close": [1762, 147],
        "scout.next": [1775, 820],
        "scout.end_battle": [115, 848],
        "settings.switch_id": [1237, 228],
        "settings.close": [1620, 122],
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
        "top.builders_menu": [1815, 975],   # Build button (bottom right) -> side panel, first tab = builders
        "army.recipes_arrow": [1140, 155],   # Saved Recipes drop-down arrow in the army screen
        "home.boat": [420, 945],   # boat to the Builder Base (bottom left, by the 2x / shield buttons)
        "bb.boat": [1620, 120],              # boat back home (Builder Base, zoomed out; top right)
        "bb.attack": [105, 975],
        "bb.builders_menu": [1815, 975],
        "bb.lab_menu": [1815, 975],
        "bb.army": [65, 830],                # Builder Base army button (left)
        "bb.army_clear": [1493, 575],        # red trash button in "Choose Army"
        "bb.army_close": [1600, 220],
        "dialog.cancel": [785, 668],         # orange Cancel of a two-button confirmation
        "request.cancel": [768, 722],        # Cancel of the request window
        "profile.settings_tab": [1475, 127],   # the Settings tab of the profile menu
        "attack_menu.edit_army": [190, 1030],   # Battle menu: Edit Army (the army screen; there is no army button)
        "build.close": [1888, 34],
        "build.filter": [1460, 34],   # the panel's filter / sorting button (top left of the panel)   # X of the Build side panel
        "build.tab_builders": [1468, 1010],   # Build panel tabs: builders
        "build.tab_lab": [1597, 1010],   # Build panel tabs: laboratory (Army Upgrades)
        "bb.build_tab_builders": [1530, 1010],   # Builder Base Build panel: builders
        "bb.build_tab_lab": [1790, 1010],   # Builder Base Build panel: Star Laboratory
        "bb.edit_army": [633, 852],   # Builder Base Battle window: Edit Army -> Choose Army
        "top.lab_menu": [1815, 975],   # the same Build button; the laboratory is the panel's second tab
    },
    "regions": {
        "home.gold": [1600, 28, 245, 40],
        "home.elixir": [1600, 90, 245, 40],
        "home.dark": [1680, 152, 165, 38],
        "home.gems": [1700, 216, 145, 36],
        "scout.gold": [78, 112, 230, 32],
        "scout.elixir": [78, 160, 230, 32],
        "scout.dark": [78, 208, 230, 32],
        "sid.list": [1345, 520, 560, 560],
        "sid.name_column": [1460, 520, 320, 560],
        "battle.troop_bar": [260, 915, 1660, 160],
        "top.builders": [1738, 845, 76, 50],   # "2/5" free builders, bottom right above the Build button
        "army.recipe_list": [865, 210, 550, 560],   # the Saved Recipes drop-down list
        "bb.gold": [1600, 28, 245, 40],
        "bb.elixir": [1600, 90, 245, 40],
        "bb.stars": [70, 846, 110, 46],   # star bonus "0/9" above the Battle button
        "bb.builders": [1738, 845, 76, 50],
        "bb.lab": [1815, 845, 80, 50],
        "home.player_name": [150, 66, 320, 40],   # in-game name next to the Town Hall picture
        "army.request_timer": [1688, 830, 112, 36],   # "10m" under the gem price while on cooldown
        "bb.reward_gold": [1140, 650, 150, 45],
        "top.lab": [1815, 845, 80, 50],   # "1/2" free laboratory (goblin icon), next to the builders
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

"""Deploying an army with an attack plan, then ending the battle.

Plans live in config/attack_plans.json. A step selects a troop (keyboard key on
PC, or troop-bar slot number on ADB where there is no keyboard) and taps it at a
list of points. Every point is tapped once per offset, like the old bot.
"""

import copy
import json
import logging
import os
import time

import cv2
import numpy as np

from .. import paths
from ..core import vision
from ..core.control import control
from ..states import detect, surrender

log = logging.getLogger("bot")

PLANS_PATH = os.path.join(paths.CONFIG, "attack_plans.json")

# The old bot's E-Dragon attack (typos in its third deploy pass fixed).
DEFAULT_PLANS = {
    "edrag_spread": {
        "description": "Spells on 3 sides, E-Dragons + Lava + Baby all round, heroes on 4 sides, siege last",
        "offsets": [[-15, -15], [0, 0], [15, 15]],
        "points": {
            "spells": [[240, 525], [913, 10], [1708, 520]],
            "ring": [[683, 876], [491, 714], [240, 525], [515, 312], [751, 137], [913, 10],
                     [1177, 125], [1438, 306], [1708, 520], [1539, 675], [1298, 848]],
            "king": [[491, 714]],
            "queen": [[751, 137]],
            "warden": [[1438, 306]],
            "champion": [[1298, 848]],
        },
        "steps": [
            {"key": "a", "slot": 9, "points": "spells"},
            {"key": "3", "slot": 3, "points": "ring"},
            {"key": "1", "slot": 1, "points": "ring"},
            {"key": "2", "slot": 2, "points": "ring"},
            {"key": "q", "slot": 5, "points": "king"},
            {"key": "w", "slot": 6, "points": "queen"},
            {"key": "e", "slot": 7, "points": "warden"},
            {"key": "r", "slot": 8, "points": "champion"},
            {"key": "z", "slot": 4, "points": "ring"},
        ],
    }
}


def load_plans():
    if not os.path.exists(PLANS_PATH):
        with open(PLANS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PLANS, f, indent=2)
    with open(PLANS_PATH, encoding="utf-8") as f:
        return json.load(f)


def detect_slots(frame, region=(0, 940, 1920, 120)):
    """X centres of the troop-bar cards, left to right (cards are ~108 px wide)."""
    x, y, w, h = region
    gray = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY).astype(np.float32)
    edge = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)) > 60
    cols = np.where(edge.mean(axis=0) > 0.6)[0]
    borders = []
    for c in cols:
        if borders and c - borders[-1][-1] <= 3:
            borders[-1].append(c)
        else:
            borders.append([c])
    borders = [int(np.mean(b)) for b in borders]
    cards, i = [], 0
    while i < len(borders):
        a = borders[i]
        pair = next((j for j in range(i + 1, len(borders)) if 98 <= borders[j] - a <= 120), None)
        if pair is None:
            i += 1
            continue
        cards.append(x + (a + borders[pair]) // 2)
        i = pair + 1
    return cards


def select(bot, step, slots):
    """Select the troop for a step: keyboard on PC, tap the card on ADB."""
    if bot.device.supports_keys and step.get("key"):
        bot.key(step["key"])
        return True
    n = step.get("slot")
    if n and 1 <= n <= len(slots):
        bot.tap(slots[n - 1], 1000, jitter=4)
        return True
    log.warning("Step %s: slot %s not on the troop bar", step, n)
    return False


def deploy(bot, plan):
    offsets = plan.get("offsets") or [[0, 0]]
    slots = [] if bot.device.supports_keys else detect_slots(bot.shot())
    for step in plan["steps"]:
        control.checkpoint()
        if not select(bot, step, slots):
            continue
        points = plan["points"][step["points"]] if isinstance(step["points"], str) else step["points"]
        for dx, dy in step.get("offsets", offsets):
            for px, py in points:
                bot.tap(px + dx, py + dy, jitter=2)
        time.sleep(0.15)


def finish_battle(bot, seconds):
    """Wait up to `seconds` for the battle to end by itself, then surrender.
    Returns once the results screen is showing (or after a timeout)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        state = detect(bot.shot())
        if state == "results":
            return True
        control.sleep(1.0)
    surrender(bot)
    for _ in range(20):
        if detect(bot.shot()) == "results":
            return True
        control.sleep(0.5)
    return False


def get_plan(name):
    plans = load_plans()
    if name not in plans:
        log.warning("Attack plan '%s' not found; using edrag_spread", name)
        return copy.deepcopy(DEFAULT_PLANS["edrag_spread"])
    return plans[name]


def has_results_templates():
    return vision.templates.has("results/return_home")

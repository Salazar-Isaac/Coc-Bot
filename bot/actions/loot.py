"""Looting: read storages, search for a base with enough loot, attack, come home."""

import logging
import time

from .. import config
from ..core import vision
from ..core.context import BotError
from ..core.control import control
from ..states import go_home
from . import attack, clan, storage

log = logging.getLogger("bot")


def watched(settings):
    w = settings["loot"]["watch"]
    return [r for r in config.RESOURCES if w.get(r)] or ["elixir"]


def home_resources(bot, account=None):
    """Current gold/elixir/dark on the home screen (None where unreadable). With an account,
    also refreshes its measured storage capacity from the resource bars."""
    frame = bot.shot()
    res = {r: bot.read_number(f"home.{r}", frame=frame) for r in config.RESOURCES}
    if account is not None:
        storage.update_capacity(account, frame, res)
    return res


def fullness(bot, account, res):
    """{resource: (value, full_at, is_full)} for the watched resources."""
    out = {}
    for r in watched(bot.settings):
        cap = config.full_at(bot.settings, account, r)
        v = res.get(r)
        out[r] = (v, cap, bool(cap and v is not None and v >= cap))
    return out


def is_full(bot, account, res):
    f = fullness(bot, account, res)
    flags = [full for _, _, full in f.values()]
    rule = bot.settings["loot"]["full_rule"]
    return (all(flags) if rule == "all" else any(flags)), f


def loot_is_good(settings, loot):
    """Is the scouted base worth attacking?"""
    mins = settings["loot"]["min_loot"]
    checks = [(loot.get(r) or 0) >= mins.get(r, 0) for r in watched(settings) if mins.get(r, 0) > 0]
    if not checks:
        return True
    return all(checks) if settings["loot"]["min_loot_rule"] == "all" else any(checks)


def start_search(bot):
    if not go_home(bot):
        raise BotError("Not on the home village")
    if bot.settings["loot"].get("zoom_out", True):
        bot.device.zoom_out()
        control.sleep(0.3)
    bot.tap_point("home.attack")
    if not bot.tap_template("attack_menu/find_match", timeout=8, after=1.0):
        raise BotError("Attack menu did not open")
    if not bot.tap_template("army/attack_button", timeout=8, after=0.5):
        bot.save_error("no-army-attack")
        raise BotError("Army 'Attack!' button not found (army not ready?)")


def stable_loot(bot, max_wait=2.0):
    """The scouted loot, read until two reads 0.25 s apart agree: the numbers count up for a
    moment when a base appears, so a single early read could be too low."""
    end = time.monotonic() + max_wait
    prev = None
    while True:
        frame = bot.shot()
        loot = {r: vision.digits.read(frame, bot.layout.region(f"scout.{r}")) for r in config.RESOURCES}
        if prev is not None and loot == prev and loot.get("gold") is not None:
            return loot
        if time.monotonic() > end:
            # still changing or unreadable: one last careful read
            return {r: bot.read_number(f"scout.{r}") for r in config.RESOURCES}
        prev = loot
        control.sleep(0.25)


def search(bot):
    """Press Next until a base meets the loot minimum. Returns the loot dict or None."""
    max_searches = bot.settings["loot"]["max_searches"]
    for n in range(1, max_searches + 1):
        if not bot.wait("scout/next", timeout=30):
            bot.save_error("no-scout")
            raise BotError("Scouting screen did not appear")
        loot = stable_loot(bot)
        bot.stats["searches"] += 1
        bot.status(action=f"Searching #{n}", loot=loot)
        if loot_is_good(bot.settings, loot):
            log.info("Search %d: %s -> attack", n, _fmt(loot))
            return loot
        log.debug("Search %d: %s -> next", n, _fmt(loot))
        bot.tap_point("scout.next")
        control.sleep(0.5)
    log.info("No base found in %d searches", max_searches)
    return None


def attack_once(bot):
    """One full attack from the home village back to the home village.
    Returns the scouted loot, or None if no good base was found."""
    start_search(bot)
    loot = search(bot)
    if loot is None:
        go_home(bot)
        return None
    plan = attack.get_plan(bot.settings["loot"]["attack_plan"])
    bot.status(action="Attacking")
    attack.deploy(bot, plan)
    attack.finish_battle(bot, bot.settings["loot"]["battle_seconds"])
    bot.stats["attacks"] += 1
    if not go_home(bot, timeout=90):          # results -> reward chest -> home
        raise BotError("Did not get home after the battle")
    return loot


def loot_until_full(bot, account):
    """Attack until the account's watched storages are full.
    Returns "full", "limit" (max attacks reached) or "stuck"."""
    s = bot.settings["loot"]
    if s.get("army_recipe") and account.get("_recipe_set") != s["army_recipe"]:
        if clan.use_recipe(bot, s["army_recipe"]):
            account["_recipe_set"] = s["army_recipe"]      # once per visit
    attacks = 0
    stuck = 0
    before = None
    while True:
        control.checkpoint()
        if not go_home(bot):
            raise BotError("Not on the home village")
        res = home_resources(bot, account)
        full, detail = is_full(bot, account, res)
        bot.status(account=account["name"], resources=res, fullness=detail)
        log.info("%s: %s", account["name"], _fmt_full(detail))
        if full:
            return "full"
        if s["max_attacks_per_account"] and attacks >= s["max_attacks_per_account"]:
            return "limit"
        if before is not None:
            grew = any((res.get(r) or 0) > (before.get(r) or 0) for r in watched(bot.settings))
            stuck = 0 if grew else stuck + 1
            if stuck >= s.get("stuck_attacks", 2):
                log.info("%s: storages stopped growing -> treating as full", account["name"])
                return "stuck"
        if before is not None:
            for r in config.RESOURCES:
                if res.get(r) is not None and before.get(r) is not None and res[r] > before[r]:
                    bot.stats["loot"][r] += res[r] - before[r]
        before = res
        if attack_once(bot) is not None:
            attacks += 1


def _fmt(d):
    return ", ".join(f"{k} {v:,}" if v is not None else f"{k} ?" for k, v in d.items())


def _fmt_full(detail):
    parts = []
    for r, (v, cap, full) in detail.items():
        vs = f"{v:,}" if v is not None else "?"
        cs = f"{cap:,}" if cap else "no limit set"
        parts.append(f"{r} {vs} / {cs}{' FULL' if full else ''}")
    return "; ".join(parts)

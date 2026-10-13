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


def min_loot(settings, account=None):
    """The loot a base needs: by the attacking account's Town Hall ("Base choice per Town Hall",
    like completeid.py: more for a higher Town Hall), else the same minimum for all."""
    lo = settings["loot"]
    table = lo.get("min_loot_th") or {}
    th = str((account or {}).get("th") or "")
    if lo.get("min_loot_mode", "th") == "th" and th in table:
        return table[th]
    return lo["min_loot"]


def loot_is_good(settings, loot, account=None):
    """Is the scouted base worth attacking?"""
    mins = min_loot(settings, account)
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


def search(bot, account=None):
    """Press Next until a base meets the loot minimum. Returns the loot dict or None."""
    max_searches = bot.settings["loot"]["max_searches"]
    for n in range(1, max_searches + 1):
        if not bot.wait("scout/next", timeout=30):
            bot.save_error("no-scout")
            raise BotError("Scouting screen did not appear")
        loot = stable_loot(bot)
        bot.stats["searches"] += 1
        bot.status(action=f"Searching #{n}", loot=loot)
        if loot_is_good(bot.settings, loot, account):
            log.info("Search %d: %s -> attack", n, _fmt(loot))
            return loot
        log.debug("Search %d: %s -> next", n, _fmt(loot))
        bot.tap_point("scout.next")
        control.sleep(0.5)
    log.info("No base found in %d searches", max_searches)
    return None


def attack_once(bot, account=None):
    """One full attack from the home village back to the home village.
    Returns the scouted loot, or None if no good base was found."""
    start_search(bot)
    loot = search(bot, account)
    if loot is None:
        go_home(bot)
        return None
    plan = attack.get_plan(bot.settings["loot"]["attack_plan"])
    bot.status(action="Attacking")
    started = time.monotonic()
    attack.deploy(bot, plan)
    attack.finish_battle(bot, bot.settings["loot"]["battle_seconds"], started)   # deploying counts too
    bot.stats["attacks"] += 1
    if not go_home(bot, timeout=90):          # results -> reward chest -> home
        raise BotError("Did not get home after the battle")
    return loot


def loot_until_full(bot, account, keep_going=False, between=None, max_attacks=None):
    """Attack until the account's watched storages are full.
    Returns "full", "limit" (max attacks reached) or "stuck".
    keep_going ("Loot current"): attack on even when full, until the attack limit or Stop.
    between(): called before each attack (the flow may visit another account's builders)."""
    s = bot.settings["loot"]
    limit = s["max_attacks_per_account"] if max_attacks is None else max_attacks
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
        if full and not keep_going:
            return "full"
        if limit and attacks >= limit:
            return "limit"
        if before is not None and not keep_going:
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
        if between is not None and between():
            before = None                            # been away: the storages are read afresh
            continue
        ensure_army(bot, account)                # only now: the account really is going to attack
        if attack_once(bot, account) is not None:
            attacks += 1


def ensure_army(bot, account):
    """Switch to the chosen Saved Recipe once per visit and check the army really has the units
    you require (Loot page). Done right before attacking, never for a full account."""
    s = bot.settings["loot"]
    name = s.get("army_recipe")
    if not name or account.get("_army_checked") == name:
        return
    account["_army_checked"] = name
    for attempt in range(2):
        applied, missing = clan.use_recipe(bot, name, check=s.get("army_must_have", ["edrag", "clone"]))
        if applied and not missing:
            return
        if not applied:
            log.warning("%s has no saved recipe called '%s': attacking with its current army",
                        account["name"], name)
            return
        if attempt == 0:
            log.info("%s: army is missing %s after the recipe, trying once more", account["name"], ", ".join(missing))
    log.warning("%s: recipe '%s' has no %s - edit that recipe in the game to include it. Attacking with it anyway.",
                account["name"], name, " / ".join(missing))


def _fmt(d):
    return ", ".join(f"{k} {v:,}" if v is not None else f"{k} ?" for k, v in d.items())


def _fmt_full(detail):
    parts = []
    for r, (v, cap, full) in detail.items():
        vs = f"{v:,}" if v is not None else "?"
        cs = f"{cap:,}" if cap else "no limit set"
        parts.append(f"{r} {vs} / {cs}{' FULL' if full else ''}")
    return "; ".join(parts)

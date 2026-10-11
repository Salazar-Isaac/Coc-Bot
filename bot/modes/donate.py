"""Donation modes.

Loot + Donate cycle (the XpIncrease way):
  1. On Main: donate to any request that is still open.
  2. If Main has enough elixir for a whole round ("Main keeps at least" + what one round
     cost last time): every requesting account (Looter, Loot + request, Feeder) empties
     its Clan Castle and requests, then Main donates to all of them. Back to 2.
  3. Not enough elixir: Main and the Looter account(s) loot until full, then back to 1.
Donate only: steps 1-2, until the elixir runs low (or for the set number of rounds).
"""

import logging
import math
import time

from .. import config
from ..core.context import BotError
from ..actions import account as account_actions
from ..actions import clan, loot
from . import register
from .common import StopRun, active_accounts, with_recovery
from .loot import _loot_account

log = logging.getLogger("bot")

REQUEST_ROLES = ("loot", "both", "feeder")   # Looters (e.g. your second account) request too
NO_CLAN_RECHECK = 3600          # an account found without a clan is skipped for an hour, then checked again


def _main_account(bot):
    mains = active_accounts(bot, ["main"])
    if not mains:
        raise StopRun("No Main account. Set one account's role to Main in the Accounts tab.")
    return mains[0]


def _switch(bot, acc, state):
    ok = with_recovery(bot, f"switch to {acc['name']}", lambda: account_actions.switch_to(bot, acc, state))
    if ok:
        config.save_accounts(bot.accounts)
    return ok


def _learn(state, key, value, weight=0.3):
    old = state.get(key)
    state[key] = round(value if not old else old * (1 - weight) + value * weight, 1)


def round_size(bot, state, total):
    """How many accounts a request round needs: just enough that by the time they have all
    requested and Main has donated to them, the first one's request cooldown (read from the game,
    10 min) is over again. More accounts would only make the round longer, not give more requests.
    "Accounts per round" on the Donate page overrides it."""
    fixed = bot.settings["donate"].get("round_accounts", 0)
    if fixed:
        return min(fixed, total)
    cooldown = state.get("request_cooldown") or 600
    per = (state.get("request_secs") or 20) + (state.get("donate_secs") or 8)
    return max(1, min(total, math.ceil(cooldown / per)))


def request_round(bot, state):
    """The first accounts (fewest scrolls in the account list) empty their Clan Castle and request,
    as many as fit the request cooldown (round_size). Returns requests sent."""
    requesters = active_accounts(bot, REQUEST_ROLES)
    if not requesters:
        raise StopRun("No requesting accounts (roles 'Looter', 'Loot + request' or 'Feeder') in the Accounts tab.")
    want = round_size(bot, state, len(requesters))
    log.info("Request round: %d account(s) (request cooldown %dm, about %ds per account + %ds donating each)",
             want, (state.get("request_cooldown") or 600) // 60, state.get("request_secs") or 20,
             state.get("donate_secs") or 8)
    sent = 0
    start = state.get("request_next", 0)              # continue where a stopped run left off
    if start:
        log.info("Continuing the request round at account %d of %d", start + 1, len(requesters))
    for i, acc in enumerate(requesters, 1):
        if i - 1 < start:
            continue
        if sent >= want:
            break
        state["request_next"] = i - 1
        config.save_state(state)
        no_clan = state.setdefault("no_clan", {})
        if time.time() - no_clan.get(acc["name"], 0) < NO_CLAN_RECHECK:
            continue                                   # had no clan recently: do not switch to it again

        bot.status(account=acc["name"], progress=f"request {sent + 1}/{want}", action="Requesting")
        started = time.monotonic()
        if not _switch(bot, acc, state):
            continue
        bot.request_cooldown = None
        result = with_recovery(bot, f"request on {acc['name']}", lambda a=acc: clan.feeder_turn(bot, a, bot.settings))
        if result:
            sent += 1
            _learn(state, "request_secs", time.monotonic() - started)
            if bot.request_cooldown:
                state["request_cooldown"] = bot.request_cooldown
        if acc.get("_no_clan"):
            state.setdefault("no_clan", {})[acc["name"]] = time.time()
            config.save_state(state)
    state["request_next"] = 0
    config.save_state(state)
    log.info("Requests sent: %d (round of %d)", sent, want)
    return sent


def main_elixir(bot):
    for _ in range(2):
        value = loot.home_resources(bot).get("elixir")
        if value is not None:
            return value
        bot.sleep(1.0)
    return None


def donate_round(bot, main, state, label="donate", learn=True):
    """Switch to Main and donate to every open request; learns what a round costs in elixir.
    Returns (units donated, Main's elixir afterwards or None)."""
    bot.status(account=main["name"], progress="", action="Donating")
    started = time.monotonic()
    if not _switch(bot, main, state):
        return 0, None
    before = main_elixir(bot)
    bot.last_donated_requests = 0
    donated = with_recovery(bot, label, lambda: clan.donate_all(bot, bot.settings)) or 0
    if learn and bot.last_donated_requests:
        _learn(state, "donate_secs", (time.monotonic() - started) / bot.last_donated_requests)
    after = main_elixir(bot)
    if learn and donated and before is not None and after is not None and 0 < before - after < before // 2:
        spent = before - after                         # (a bigger drop would be a misread number)
        old = state.get("round_elixir", 0)
        state["round_elixir"] = spent if not old else (old + spent) // 2
        config.save_state(state)
        log.info("This round cost %s elixir (%s left)", f"{spent:,}", f"{after:,}")
    return donated, after


def round_need(bot, state):
    """Elixir Main must have to start a round: what it keeps + what one round cost last time."""
    return bot.settings["donate"].get("min_elixir_keep", 0) + state.get("round_elixir", 0)


def donation_cycle(bot, main, state):
    """The XpIncrease way, always starting on Main (you may have spent its elixir meanwhile):
      1. not enough elixir for a whole round -> "low" (time to loot);
      2. donate to requests that are still open, then check the elixir again;
      3. while it covers a whole round: every requesting account requests, Main donates.
    Returns "low", "rounds" (round limit reached) or "idle" (nothing was donated)."""
    max_rounds = bot.settings["donate"].get("rounds", 0)
    if not _switch(bot, main, state):
        raise BotError(f"Could not open {main['name']}")
    elixir = main_elixir(bot)
    need = round_need(bot, state)
    if elixir is not None and elixir < need:
        log.info("%s has %s elixir; a round needs %s: time to loot", main["name"], f"{elixir:,}", f"{need:,}")
        return "low"
    log.info("%s has %s elixir: donating to requests that are still open first", main["name"],
             f"{elixir:,}" if elixir is not None else "?")
    _, elixir = donate_round(bot, main, state, "donate open requests", learn=False)
    n = 0
    while True:
        need = round_need(bot, state)
        if elixir is not None and elixir < need:
            log.info("%s has %s elixir; a round needs %s: time to loot", main["name"], f"{elixir:,}", f"{need:,}")
            return "low"
        n += 1
        log.info("Donation round %d%s (Main's elixir %s; a round needs %s)", n,
                 f" of {max_rounds}" if max_rounds else "", f"{elixir:,}" if elixir is not None else "?",
                 f"{need:,}")
        request_round(bot, state)
        donated, elixir = donate_round(bot, main, state)
        if max_rounds and n >= max_rounds:
            return "rounds"
        if donated == 0:
            log.info("Nothing was donated this round (no requests or nothing to give)")
            return "idle"


@register("loot_donate", "Loot + Donate cycle",
          "Like XpIncrease: Main first donates to open requests; while it has enough elixir for a round, "
          "every Looter / 'Loot + request' / Feeder account empties its Clan Castle and requests and Main "
          "donates. When the elixir runs low, Main and the Looter accounts loot until full, then it repeats.",
          order=3)
def run_loot_donate(bot, state):
    main = _main_account(bot)
    looters = [main] + active_accounts(bot, ["loot"])
    rounds = bot.settings.get("repeat_rounds", 1)
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        log.info("Cycle %d%s", n, f" of {rounds}" if rounds else "")
        if n == 1 and bot.settings["donate"].get("loot_before_donate", False):
            _loot_all(bot, looters, state)              # "Always loot to full first"
        donation_cycle(bot, main, state)
        _loot_all(bot, looters, state)


def _loot_all(bot, looters, state):
    for acc in looters:
        bot.status(account=acc["name"], progress="loot", action="Looting")
        _loot_account(bot, acc, state, cycle=True)


@register("donate_only", "Donate only",
          "Main first donates to open requests; then, while it has enough elixir for a round, every "
          "requesting account requests and Main donates.", order=4)
def run_donate_only(bot, state):
    main = _main_account(bot)
    rounds = bot.settings.get("repeat_rounds", 1)
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        if donation_cycle(bot, main, state) == "low":
            log.info("Main's elixir is low: Donate only is done")
            return

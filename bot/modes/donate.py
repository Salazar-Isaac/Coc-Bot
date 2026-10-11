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
import time

from .. import config
from ..actions import account as account_actions
from ..actions import clan, loot
from . import register
from .common import StopRun, active_accounts, chores, with_recovery
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


def request_round(bot, state):
    """Every requesting account empties its Clan Castle and requests. Returns requests sent."""
    requesters = active_accounts(bot, REQUEST_ROLES)
    if not requesters:
        raise StopRun("No requesting accounts (roles 'Loot + request' or 'Feeder') in the Accounts tab.")
    sent = 0
    start = state.get("request_next", 0)              # continue where a stopped run left off
    if start:
        log.info("Continuing the request round at account %d of %d", start + 1, len(requesters))
    for i, acc in enumerate(requesters, 1):
        if i - 1 < start:
            continue
        state["request_next"] = i - 1
        config.save_state(state)
        no_clan = state.setdefault("no_clan", {})
        if time.time() - no_clan.get(acc["name"], 0) < NO_CLAN_RECHECK:
            continue                                   # had no clan recently: do not switch to it again

        bot.status(account=acc["name"], progress=f"request {i}/{len(requesters)}", action="Requesting")
        if not _switch(bot, acc, state):
            continue
        chores(bot, acc, "arrive")
        result = with_recovery(bot, f"request on {acc['name']}", lambda a=acc: clan.feeder_turn(bot, a, bot.settings))
        if result:
            sent += 1
        if acc.get("_no_clan"):
            state.setdefault("no_clan", {})[acc["name"]] = time.time()
            config.save_state(state)
    state["request_next"] = 0
    config.save_state(state)
    log.info("Requests sent: %d of %d accounts", sent, len(requesters))
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
    if not _switch(bot, main, state):
        return 0, None
    before = main_elixir(bot)
    donated = with_recovery(bot, label, lambda: clan.donate_all(bot, bot.settings)) or 0
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


def donation_cycle(bot, main, state, check_open=True):
    """The XpIncrease way: on Main, first donate to requests that are still open; then, while Main
    has enough elixir for a whole round, every requesting account requests and Main donates.
    check_open=False right after looting (Main is full; the request round can start where we are).
    Returns "low" (not enough elixir: time to loot), "rounds" (round limit) or "idle"."""
    max_rounds = bot.settings["donate"].get("rounds", 0)
    resume = state.get("request_next", 0) > 0          # a stopped run was in the middle of a request round
    elixir = None
    if check_open and not resume:
        log.info("Main: donating to requests that are still open")
        _, elixir = donate_round(bot, main, state, "donate open requests", learn=False)
    n = 0
    while True:
        need = round_need(bot, state)
        if elixir is not None and elixir < need:
            log.info("%s has %s elixir; a round needs %s: time to loot", main["name"], f"{elixir:,}", f"{need:,}")
            return "low"
        n += 1
        log.info("Donation round %d%s (Main's elixir %s; a round needs %s)", n,
                 f" of {max_rounds}" if max_rounds else "", f"{elixir:,}" if elixir is not None else "full",
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
        if n == 1 and bot.settings["donate"].get("loot_before_donate", False) and not state.get("request_next"):
            _loot_all(bot, looters, state)              # "Always loot to full first"
        donation_cycle(bot, main, state, check_open=(n == 1))
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


@register("join_clan", "Join clan",
          "Visit every 'Loot + request' and Feeder account and join the clan from the Donate page "
          "(clan tag) when the account has no clan. Accounts already in a clan are left alone.", order=7)
def run_join_clan(bot, state):
    tag = bot.settings["donate"].get("clan_tag", "")
    if not tag:
        raise StopRun("Set the clan tag on the Donate page first (e.g. #2RPLP89CY).")
    accounts = active_accounts(bot, REQUEST_ROLES)
    joined, already, failed = [], 0, []
    for i, acc in enumerate(accounts, 1):
        bot.status(account=acc["name"], progress=f"{i}/{len(accounts)}", action="Joining clan")
        if not _switch(bot, acc, state):
            failed.append(acc["name"])
            continue
        if clan.in_clan(bot) is True:
            already += 1
        elif with_recovery(bot, f"join clan on {acc['name']}", lambda: clan.join_clan(bot, tag), attempts=2):
            joined.append(acc["name"])
            state.setdefault("no_clan", {}).pop(acc["name"], None)
            config.save_state(state)
        else:
            failed.append(acc["name"])
    log.info("Join clan done: %d joined (%s), %d already in a clan, %d failed%s", len(joined), ", ".join(joined),
             already, len(failed), f" ({', '.join(failed)})" if failed else "")

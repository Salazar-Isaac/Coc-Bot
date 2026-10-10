"""Donation modes.

Loot + Donate cycle (your flow):
  1. Main loots until full, then the Loot-only account(s) loot until full.
  2. Every requesting account (roles "Loot + request" and "Feeder") empties its
     Clan Castle and requests.
  3. Main donates to all those requests.
  4. Repeat 2-3 while Main still has more elixir than "Main keeps at least".
  5. Back to 1.
Donate only: steps 2-4, repeated (Repeat rounds / until elixir runs low).
"""

import logging

from .. import config
from ..actions import account as account_actions
from ..actions import clan, loot
from . import register
from .common import StopRun, active_accounts, with_recovery
from .loot import _loot_account

log = logging.getLogger("bot")

REQUEST_ROLES = ("both", "feeder")


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
    for i, acc in enumerate(requesters, 1):
        bot.status(account=acc["name"], progress=f"request {i}/{len(requesters)}", action="Requesting")
        if not _switch(bot, acc, state):
            continue
        if with_recovery(bot, f"request on {acc['name']}", lambda a=acc: clan.feeder_turn(bot, a, bot.settings)):
            sent += 1
    log.info("Requests sent: %d of %d accounts", sent, len(requesters))
    return sent


def main_elixir(bot):
    return loot.home_resources(bot).get("elixir")


def donate_round(bot, main, state):
    """Switch to Main and donate to every open request. Returns donations made."""
    bot.status(account=main["name"], progress="", action="Donating")
    if not _switch(bot, main, state):
        return 0
    return with_recovery(bot, "donate", lambda: clan.donate_all(bot, bot.settings)) or 0


def donation_cycle(bot, main, state):
    """Request + donate rounds while Main has elixir (or for the configured rounds)."""
    d = bot.settings["donate"]
    keep, max_rounds = d.get("min_elixir_keep", 0), d.get("rounds", 0)
    n = 0
    while True:
        n += 1
        log.info("Donation round %d%s", n, f" of {max_rounds}" if max_rounds else "")
        request_round(bot, state)
        donated = donate_round(bot, main, state)
        elixir = main_elixir(bot)
        log.info("%s elixir after donating: %s (keeps at least %s)", main["name"],
                 f"{elixir:,}" if elixir is not None else "?", f"{keep:,}")
        if max_rounds and n >= max_rounds:
            return
        if elixir is not None and elixir < keep:
            log.info("Main's elixir is below the limit: donation cycle done")
            return
        if donated == 0:
            log.info("Nothing was donated this round (no requests or nothing to give): stopping the cycle")
            return


@register("loot_donate", "Loot + Donate cycle",
          "Main and Loot-only accounts loot until full; then every 'Loot + request' and Feeder account "
          "empties its Clan Castle and requests, and Main donates to all of them. Repeats while Main has "
          "elixir, then loots again.", order=3)
def run_loot_donate(bot, state):
    main = _main_account(bot)
    looters = [main] + active_accounts(bot, ["loot"])
    rounds = bot.settings.get("repeat_rounds", 1)
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        log.info("Cycle %d%s", n, f" of {rounds}" if rounds else "")
        if bot.settings["donate"].get("loot_before_donate", True):
            for acc in looters:
                bot.status(account=acc["name"], progress="loot", action="Looting")
                _loot_account(bot, acc, state, cycle=True)
        donation_cycle(bot, main, state)


@register("donate_only", "Donate only",
          "Every 'Loot + request' and Feeder account empties its Clan Castle and requests, then Main "
          "donates to all of them; repeats while Main has elixir.", order=4)
def run_donate_only(bot, state):
    main = _main_account(bot)
    rounds = bot.settings.get("repeat_rounds", 1)
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        donation_cycle(bot, main, state)

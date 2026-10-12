"""Looting modes."""

import logging

from .. import config
from ..actions import account as account_actions
from ..actions import builder_base, loot, upgrades
from . import register
from .common import StopRun, active_accounts, when_full, with_recovery

log = logging.getLogger("bot")


def _loot_account(bot, acc, state, switch=True, cycle=False, plan=False):
    """Loot one account until full, applying 'when full'. Returns when we should move on.
    In the donation cycle (cycle=True) "switch to the next account" is implied, but
    "wait for me" and "stop" still apply. plan=True ("Loot + Upgrade" mode): the upgrade plan
    runs before looting (if there are resources already) and again after looting."""
    if switch:
        ok = with_recovery(bot, f"switch to {acc['name']}",
                           lambda: account_actions.switch_to(bot, acc, state))
        if not ok:
            log.error("Skipping %s: could not switch to it", acc["name"])
            return
        config.save_accounts(bot.accounts)          # remembers the Town Hall level we read
    if plan:
        upgrade(bot, acc, "before looting")         # resources there already: builders first
    while True:
        result = with_recovery(bot, f"loot {acc['name']}", lambda: loot.loot_until_full(bot, acc))
        if result is None:
            return                                   # gave up after retries
        log.info("%s: %s", acc["name"], {"full": "storages full", "stuck": "storages full (stopped growing)",
                                          "limit": "attack limit reached"}[result])
        builder_after(bot, acc)
        if plan and bot.settings.get("when_full") != "wait":
            upgrade(bot, acc, "after looting")      # spend before moving on (not when you spend yourself)
        if cycle and bot.settings.get("when_full") == "switch":
            return
        if when_full(bot, acc) == "next":
            return


def upgrade(bot, acc, when):
    """Upgrade plan (actions/upgrades.py) on accounts ticked "Upgrade" on the Accounts page."""
    if acc.get("upgrade") and bot.settings.get("upgrades", {}).get("enabled", True):
        bot.status(action="Upgrading")
        with_recovery(bot, f"upgrades on {acc['name']}", lambda: upgrades.run(bot, acc, when), attempts=2)


def builder_after(bot, acc):
    """'After the home village is full, loot the Builder Base too' (Builder Base page)."""
    cfg = bot.settings.get("builder", {})
    if cfg.get("after_main") and acc.get("role", "loot") in cfg.get("on_roles", ["main", "loot", "both", "feeder"]):
        with_recovery(bot, f"Builder Base of {acc['name']}", lambda: builder_base.session(bot, acc), attempts=2)


@register("builder_only", "Builder Base only",
          "Visit the enabled accounts' Builder Base (night village): attack until the daily Star Bonus is "
          "complete (or keep going, see the Builder Base page), collect, upgrade, then sail back.", order=6)
def run_builder_only(bot, state):
    roles = bot.settings.get("builder", {}).get("on_roles", ["main", "loot", "both", "feeder"])
    accounts = active_accounts(bot, roles)
    if not accounts:
        raise StopRun("No enabled accounts with the roles ticked for the Builder Base.")
    rounds = bot.settings.get("repeat_rounds", 1)
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        for i, acc in enumerate(accounts):
            bot.status(account=acc["name"], progress=f"{i + 1}/{len(accounts)}")
            ok = with_recovery(bot, f"switch to {acc['name']}",
                               lambda a=acc: account_actions.switch_to(bot, a, state))
            if not ok:
                continue
            config.save_accounts(bot.accounts)
            with_recovery(bot, f"Builder Base of {acc['name']}", lambda a=acc: builder_base.session(bot, a), attempts=2)


@register("loot_all", "Loot all accounts",
          "Switch through the enabled accounts (roles ticked in Loot Settings) in list order and loot "
          "each one until its watched storages are full.", order=1)
def run_loot_all(bot, state):
    roles = [r for r, on in bot.settings["loot"].get("roles", {}).items() if on] or ["main", "loot", "both"]
    accounts = active_accounts(bot, roles)
    if not accounts:
        raise StopRun("No enabled accounts with the roles ticked in Loot Settings.")
    rounds = bot.settings.get("repeat_rounds", 1)
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        log.info("Round %d%s", n, f" of {rounds}" if rounds else "")
        start = state.get("loot_all_next", 0) if n == 1 else 0
        for i, acc in enumerate(accounts):
            if i < start:
                continue
            state["loot_all_next"] = i
            config.save_state(state)
            bot.status(account=acc["name"], progress=f"{i + 1}/{len(accounts)}")
            _loot_account(bot, acc, state)
        state["loot_all_next"] = 0
        config.save_state(state)


@register("loot_current", "Loot current account only",
          "Stay on the account that is open now and loot it until full. Good with "
          "'When full: Wait for me' to spend resources and keep going.", uses_accounts=False, order=2)
def run_loot_current(bot, state):
    name = bot.settings.get("current_account", "")
    acc = next((a for a in bot.accounts if a["name"] == name), None)
    if acc is None:
        acc = config.new_account(name or "Current account")
        acc["th"] = bot.settings.get("current_th", 0)
    _loot_account(bot, acc, state, switch=False)

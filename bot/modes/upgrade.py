"""Upgrade modes - separate from looting and donating.

Loot + Upgrade: the accounts #from-#to on the Accounts page (Upgrades page; default 1-15, i.e.
Buggu01 to Buggu7) are looted one after another. On the ones ticked "Upgrade" (all but the Main
and the Omi account) the upgrade plan runs before looting, if there are resources already, and
again after looting.

Builder Base upgrades: the same accounts' Builder Base - attacks as set on the Builder Base page,
with the Builder Base plan (new buildings, your list, then the Builder Hall) before and after.
"""

import logging

from .. import config
from ..actions import account as account_actions
from ..actions import builder_base
from . import register
from .common import StopRun, with_recovery
from .loot import _loot_account

log = logging.getLogger("bot")


def plan_accounts(bot):
    """Accounts #from-#to of the Accounts page (skipped / switched-off ones left out)."""
    cfg = bot.settings.get("upgrades", {})
    first, last = max(1, int(cfg.get("from", 1))), int(cfg.get("to", 15))
    return [a for a in bot.accounts[first - 1:last] if a.get("enabled", True) and a.get("role") != "skip"]


@register("loot_upgrade", "Loot + Upgrade",
          "Accounts #1-#15 of the Accounts page (Buggu01 to Buggu7; change it on the Upgrades page) loot "
          "until full. On every account ticked 'Upgrade' (all but the Main and Omi ji) free builders start the "
          "upgrade plan first if there are resources, and again after looting.", order=5)
def run_loot_upgrade(bot, state):
    accounts = plan_accounts(bot)
    if not accounts:
        raise StopRun("No accounts in the range set on the Upgrades page.")
    log.info("Loot + Upgrade: %s", ", ".join(a["name"] for a in accounts))
    rounds = bot.settings.get("repeat_rounds", 1)
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        log.info("Round %d%s", n, f" of {rounds}" if rounds else "")
        start = state.get("loot_upgrade_next", 0) if n == 1 else 0
        for i, acc in enumerate(accounts):
            if i < start:
                continue
            state["loot_upgrade_next"] = i
            config.save_state(state)
            bot.status(account=acc["name"], progress=f"{i + 1}/{len(accounts)}")
            _loot_account(bot, acc, state, plan=True)
        state["loot_upgrade_next"] = 0
        config.save_state(state)


@register("bb_upgrade", "Builder Base upgrades",
          "The same accounts (#1-#15) sail to their Builder Base and attack as set on the Builder Base page. "
          "On every account ticked 'Upgrade' the builders first build new buildings, then upgrade your list "
          "(default Cannon, Archer Tower, Mortar) and the Builder Hall once that list is maxed - to gear up.",
          order=7)
def run_bb_upgrade(bot, state):
    accounts = plan_accounts(bot)
    if not accounts:
        raise StopRun("No accounts in the range set on the Upgrades page.")
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
            with_recovery(bot, f"Builder Base of {acc['name']}",
                          lambda a=acc: builder_base.session(bot, a, plan=True), attempts=2)

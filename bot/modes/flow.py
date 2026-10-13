"""The flow: your functions, run in the order you arranged them in the window (bot/flow.py).

Per-account steps run account by account (account 1 does all of them, then account 2, ...),
each on the accounts listed in its settings. While an account is being looted, another account
whose builders (or laboratory) are free again - the time is read from its menu when it was
last put to work - is visited to start the next upgrade (research), then the looting goes on.
"""

import contextlib
import logging

from .. import config
from ..actions import account as account_actions
from ..actions import builder_base, loot, research, timers, upgrades
from ..core.context import BotError
from ..flow import BY_KEY, segments, step_accounts
from ..states import go_home
from . import register
from .common import StopRun, when_full, with_recovery
from .donate import _main_account, donation_cycle

log = logging.getLogger("bot")

# per-account steps that can be done "in between" (when their builders / lab are free again)
COMEBACK = {"home_upgrade": "builders", "home_research": "lab"}


class Ctx:
    """What one run of the flow knows: its steps' settings and the accounts they work on."""

    def __init__(self, bot, keys, state):
        self.bot, self.keys, self.state = bot, keys, state
        steps = bot.settings.get("steps", {})
        self.cfg = {k: steps.get(k, {}) for k in BY_KEY}
        self.accounts = {k: [a["name"] for _, a in step_accounts(self.cfg[k].get("accounts", ""), bot.accounts)]
                         for k in BY_KEY}
        self.comeback = [k for k in COMEBACK if k in keys]
        self.away = False                              # True while visiting another account in between


@register("flow", "Flow", "Your functions, in the order you arranged them", order=0)
def run_flow(bot, state):
    keys = [k for k in bot.settings.get("flow", []) if k in BY_KEY]
    if not keys:
        raise StopRun("The flow is empty: drag functions into it first.")
    ctx = Ctx(bot, keys, state)
    sig = ",".join(keys)
    rounds = bot.settings.get("repeat_rounds", 1)
    log.info("Flow: %s", " -> ".join(BY_KEY[k].title for k in keys))
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        log.info("Round %d%s", n, f" of {rounds}" if rounds else "")
        resume = state.get("flow_next") if n == 1 and (state.get("flow_next") or {}).get("sig") == sig else None
        for si, (kind, part) in enumerate(segments(keys)):
            if resume and si < resume.get("seg", 0):
                continue
            if kind == "once":
                _run_once(bot, ctx, part)
            else:
                start = resume.get("pos", 0) if resume and si == resume.get("seg") else 0
                _run_accounts(bot, ctx, si, part, sig, start)
            resume = None
        state.pop("flow_next", None)
        config.save_state(state)


# --- steps that run once -------------------------------------------------------------------------

def _run_once(bot, ctx, key):
    if key == "donate":
        main = _main_account(bot)
        bot.status(account=main["name"], action="Donating", progress="")
        log.info("== Donate")
        donation_cycle(bot, main, ctx.state)
    elif key == "loot_current":
        _loot_current(bot, ctx)


@contextlib.contextmanager
def _loot_settings(bot, **values):
    """Use other loot settings for a while (Loot current has its own army, plan and time)."""
    lo = bot.settings["loot"]
    old = {k: lo.get(k) for k in values}
    lo.update({k: v for k, v in values.items() if v is not None})
    try:
        yield
    finally:
        lo.update(old)


def _loot_current(bot, ctx):
    cfg = ctx.cfg["loot_current"]
    name = cfg.get("account", "")
    acc = next((a for a in bot.accounts if a["name"] == name), None) if name else None
    if acc is not None:
        if not with_recovery(bot, f"switch to {acc['name']}", lambda: account_actions.switch_to(bot, acc, ctx.state)):
            log.error("Loot current: could not open %s", acc["name"])
            return
    else:                                              # the account open now
        acc = bot.current_acc or next((a for a in bot.accounts if a["name"] == bot.current_account), None)
        if acc is None:
            acc = config.new_account("Current account")
    log.info("== Loot current on %s (keeps attacking even when full)", acc["name"])
    bot.status(account=acc["name"], action="Loot current", progress="")
    with _loot_settings(bot, battle_seconds=cfg.get("battle_seconds"), army_recipe=cfg.get("army_recipe"),
                        attack_plan=cfg.get("attack_plan") or None):
        result = with_recovery(bot, f"loot {acc['name']}",
                               lambda: loot.loot_until_full(bot, acc, keep_going=True,
                                                            max_attacks=cfg.get("max_attacks", 0)))
    if result == "limit":
        log.info("Loot current: %d attacks done", cfg.get("max_attacks", 0))


# --- steps that run account by account -----------------------------------------------------------

def _run_accounts(bot, ctx, si, keys, sig, start_pos=0):
    """Each account (in list order) that any of these steps works on does them in flow order."""
    plan = {}
    for key in keys:
        for pos, acc in step_accounts(ctx.cfg[key].get("accounts", ""), bot.accounts):
            plan.setdefault(pos, (acc, []))[1].append(key)
    order = sorted(plan)
    if not order:
        log.info("No accounts for %s", ", ".join(BY_KEY[k].title for k in keys))
        return
    for i, pos in enumerate(order):
        if pos < start_pos:
            continue
        acc, todo = plan[pos]
        ctx.state["flow_next"] = {"sig": sig, "seg": si, "pos": pos}
        config.save_state(ctx.state)
        bot.status(account=acc["name"], progress=f"{i + 1}/{len(order)}")
        if not with_recovery(bot, f"switch to {acc['name']}", lambda a=acc: account_actions.switch_to(bot, a, ctx.state)):
            log.error("Skipping %s: could not switch to it", acc["name"])
            continue
        config.save_accounts(bot.accounts)            # the Town Hall level and name just read
        log.info("== %s: %s", acc["name"], ", ".join(BY_KEY[k].title for k in todo))
        no_bb = False
        for key in todo:
            if BY_KEY[key].village == "builder":
                if no_bb:
                    continue
                if not _to_village(bot, acc, "builder"):
                    no_bb = True
                    continue
            else:
                _to_village(bot, acc, "main")
            _run_step(bot, ctx, key, acc)
        _to_village(bot, acc, "main")


def _to_village(bot, acc, village):
    """Sail to the Builder Base / back home if needed. False if this account has no Builder Base."""
    try:
        if builder_base.where(bot) == village:
            return True
        if village == "builder":
            builder_base.travel(bot, "builder")
            if bot.settings.get("builder", {}).get("collect", True):
                builder_base.collect(bot)
        else:
            builder_base.travel(bot, "main")
        return True
    except BotError as e:
        if village == "builder":
            log.info("%s: %s - skipping its Builder Base steps", acc["name"], e)
        else:
            log.warning("%s: %s", acc["name"], e)
        go_home(bot)
        return village == "main"


def _run_step(bot, ctx, key, acc):
    cfg = ctx.cfg[key]
    name = acc["name"]
    title = BY_KEY[key].title
    bot.status(action=title)
    if key == "attack_all":
        while True:
            result = with_recovery(bot, f"loot {name}", lambda: (
                _on(bot, ctx, acc), loot.loot_until_full(bot, acc, between=lambda: _comeback(bot, ctx, acc)))[1])
            if result is None:
                return
            log.info("%s: %s", name, {"full": "storages full", "stuck": "storages full (stopped growing)",
                                      "limit": "attack limit reached"}[result])
            if when_full(bot, acc) == "next":
                return
            _to_village(bot, acc, "main")
    elif key == "home_upgrade":
        with_recovery(bot, f"upgrades on {name}", lambda: upgrades.run(
            bot, acc, max_count=cfg.get("max_per_visit", 5), buildings=cfg.get("buildings") or []), attempts=2)
    elif key == "home_research":
        with_recovery(bot, f"research on {name}", lambda: research.run(bot, acc, cfg.get("research") or []),
                      attempts=2)
    elif key == "bb_attack":
        with_recovery(bot, f"Builder Base attacks on {name}", lambda: builder_base.attacks(bot, acc), attempts=2)
    elif key == "bb_upgrade":
        with_recovery(bot, f"Builder Base upgrades on {name}", lambda: upgrades.run_bb(
            bot, acc, plan=cfg.get("buildings") or [], new_first=cfg.get("new_first", True)), attempts=2)
    elif key == "bb_research":
        with_recovery(bot, f"Star Laboratory on {name}",
                      lambda: research.run(bot, acc, cfg.get("research") or [], builder=True), attempts=2)


def _on(bot, ctx, acc):
    """Make sure this account is the one open (after a visit to another one, or a retry)."""
    if bot.current_account != acc["name"]:
        account_actions.switch_to(bot, acc, ctx.state)
        _to_village(bot, acc, "main")


def _comeback(bot, ctx, here):
    """Before each attack on `here`: is another account's builder (or lab) free again? Then go there,
    start the next upgrade (research) and come back. Returns True if the bot was away."""
    if ctx.away or not ctx.comeback:
        return False
    names = {n for k in ctx.comeback for n in ctx.accounts[k]} - {here["name"]}
    due = timers.due(bot, names, [COMEBACK[k] for k in ctx.comeback])
    if not due:
        return False
    name = due[0][0]
    other = next((a for a in bot.accounts if a["name"] == name), None)
    if other is None:
        return False
    kinds = {k for n, k in due if n == name}
    todo = [k for k in ctx.comeback if COMEBACK[k] in kinds and name in ctx.accounts[k]]
    log.info("%s: %s free again - going there to start the next one, then back to %s", name,
             " and ".join("builders" if COMEBACK[k] == "builders" else "laboratory" for k in todo), here["name"])
    ctx.away = True
    try:
        if with_recovery(bot, f"switch to {name}", lambda: account_actions.switch_to(bot, other, ctx.state)):
            for key in todo:
                _to_village(bot, other, "main")
                _run_step(bot, ctx, key, other)
        else:
            for key in todo:
                timers.clear(bot, other, COMEBACK[key])   # do not try again and again
        _on(bot, ctx, here)                            # back (an error here is retried by the looting)
        bot.status(account=here["name"], action=BY_KEY["attack_all"].title)
    finally:
        ctx.away = False
    return True

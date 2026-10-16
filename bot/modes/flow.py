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
from ..actions import builder_base, loot, research, timers, upgrades, walls
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
        self.accounts = {k: [a["name"] for _, a in step_accounts(self.cfg[k].get("accounts", ""), bot.accounts, k)]
                         for k in BY_KEY}
        self.comeback = [k for k in COMEBACK if k in keys]
        self.away = False                              # True while visiting another account in between


@register("flow", "Flow", "Your functions, in the order you arranged them", order=0)
def run_flow(bot, state):
    keys = [k for k in bot.settings.get("flow", []) if k in BY_KEY]
    if not keys:
        raise StopRun("The flow is empty: drag functions into it first.")
    ctx = Ctx(bot, keys, state)
    rounds = bot.settings.get("repeat_rounds", 1)
    # "Start from account" (in the window): the account the first round starts with. It follows the
    # run (the window shows the account the bot is on), so after a stop the next run goes on there.
    start = max(1, int(bot.settings.get("start_from", 1) or 1))
    log.info("Flow: %s", " -> ".join(BY_KEY[k].title for k in keys))
    if start > 1:
        log.info("Starting from account #%d (%s)", start,
                 bot.accounts[start - 1]["name"] if start <= len(bot.accounts) else "?")
    if bot.settings.get("option") == "upgrade_donate":
        return _upgrade_loot_donate(bot, ctx, start)
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        log.info("Round %d%s", n, f" of {rounds}" if rounds else "")
        for kind, part in segments(keys):
            if kind == "once":
                _run_once(bot, ctx, part)
            else:
                _run_accounts(bot, ctx, part, start)
                start = 1                              # only the first part of the first round skips
        _set_start(bot, 1)                             # a whole round done: the next one starts at #1


def _upgrade_loot_donate(bot, ctx, start):
    """"Upgrade, loot, donate": accounts 1-15 upgrade, loot until full and upgrade again (a builder
    that frees up on another account meanwhile is put to work between two attacks); then the
    Loot + Donate cycle for good: accounts 1-2 (Main, Omi ji) loot, the others request, Main donates.
    When a builder frees up on an account, donating stops for a moment: the bot goes there,
    upgrades, loots it full, upgrades again, and goes back to donating."""
    pass_keys = [k for k in ctx.keys if k != "donate"]
    if start <= max((p for p, _ in step_accounts(ctx.cfg["attack_all"].get("accounts", ""), bot.accounts,
                                                 "attack_all")), default=0):
        log.info("== Upgrade and loot every account")
        _run_accounts(bot, ctx, pass_keys, start)
    _set_start(bot, len(bot.accounts) + 1)              # a stop from here on: straight back to donating
    main = _main_account(bot)
    looters = step_accounts("1-2", bot.accounts)          # Main and Omi ji (by position)
    hook = lambda: _visit_free_builders(bot, ctx)        # noqa: E731
    log.info("== Loot + Donate (%s loot); a freed builder is put to work in between",
             " and ".join(a["name"] for _, a in looters))
    while True:
        hook()
        bot.status(account=main["name"], action="Donating", progress="")
        result = donation_cycle(bot, main, ctx.state, between=hook)
        for _, acc in looters:
            hook()
            if not with_recovery(bot, f"switch to {acc['name']}",
                                 lambda a=acc: account_actions.switch_to(bot, a, ctx.state)):
                continue
            _to_village(bot, acc, "main")
            bot.status(account=acc["name"], action="Looting", progress="")
            with_recovery(bot, f"loot {acc['name']}", lambda a=acc: loot.loot_until_full(bot, a, between=hook))
        if result == "idle":                             # no requests were possible: give the timers a minute
            bot.sleep(60)


def _visit_free_builders(bot, ctx):
    """Donating / looting: an account whose builder is free again (time read from its builder menu) gets
    its upgrade, is looted full and upgraded again, then the bot goes back to what it was doing.
    Returns True if it visited one."""
    if ctx.away:
        return False
    names = ctx.accounts.get("home_upgrade") or []
    due = timers.due(bot, names, ["builders"], unknown=True)   # (never looked at: due as well)
    if not due:
        return False
    ctx.away = True
    waiting = list(dict.fromkeys(n for n, _ in due))
    if len(waiting) > 1:
        log.info("Builders to look at on %d accounts (%s): %s now, the others between the next rounds",
                 len(waiting), ", ".join(waiting), waiting[0])
    try:
        for name in waiting[:1]:                       # one account between two donation rounds
            acc = next((a for a in bot.accounts if a["name"] == name), None)
            if acc is None:
                continue
            log.info("%s: a builder is free (or not looked at yet) - upgrading, looting, upgrading, then back", name)
            if not with_recovery(bot, f"switch to {name}", lambda a=acc: account_actions.switch_to(bot, a, ctx.state)):
                timers.later(bot, acc, "builders", upgrades.IDLE_RETRY)   # not again and again: in an hour
                continue
            _to_village(bot, acc, "main")
            for key in ("home_upgrade", "attack_all", "home_upgrade"):
                _run_step(bot, ctx, key, acc)
            for n, k in timers.due(bot, [name], ["builders"], unknown=True):   # never twice in a row
                timers.later(bot, acc, k, upgrades.IDLE_RETRY)                  # for nothing: in an hour
    finally:
        ctx.away = False
    return True


def _set_start(bot, pos):
    """Where the next run starts: the window shows it and saves it."""
    bot.settings["start_from"] = pos
    bot.status(start_from=pos)


# --- steps that run once -------------------------------------------------------------------------

def _run_once(bot, ctx, key):
    if key == "donate":
        main = _main_account(bot)
        bot.status(account=main["name"], action="Donating", progress="")
        log.info("== Donate")
        result = donation_cycle(bot, main, ctx.state)
        if result == "low" and not any(BY_KEY[k].key in ("attack_all", "loot_current") for k in ctx.keys):
            raise StopRun("Main's elixir is low: Donate only is done (Loot + Donate loots it back)")
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

def _run_accounts(bot, ctx, keys, start_pos=1):
    """Each account (in list order) that any of these steps works on does them in flow order,
    from account #start_pos on."""
    plan = {}
    for key in keys:
        for pos, acc in step_accounts(ctx.cfg[key].get("accounts", ""), bot.accounts, key):
            plan.setdefault(pos, (acc, []))[1].append(key)
    order = sorted(plan)
    if not order:
        log.info("No accounts for %s", ", ".join(BY_KEY[k].title for k in keys))
        return
    for i, pos in enumerate(order):
        if pos < start_pos:
            continue
        acc, todo = plan[pos]
        _set_start(bot, pos)                           # a stop here: the next run starts with this account
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
        here = builder_base.where(bot)
        if here == village:
            return True
        if here is None and village == "main" and go_home(bot, 60):
            return True                               # an unknown screen over the home village
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
            if result in ("no_army", "no_gold"):
                return                                 # (logged): no army / no gold to search
            log.info("%s: %s", name, {"full": "storages full", "stuck": "storages full (stopped growing)",
                                      "limit": "attack limit reached"}[result])
            if when_full(bot, acc) == "next":
                return
            _to_village(bot, acc, "main")
    elif key == "home_upgrade":
        with_recovery(bot, f"upgrades on {name}", lambda: upgrades.run(
            bot, acc, max_count=cfg.get("max_per_visit", 5), buildings=cfg.get("buildings") or []), attempts=2)
    elif key == "walls":
        with_recovery(bot, f"walls on {name}", lambda: walls.run(bot, acc), attempts=2)
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
        for key in todo:                               # still "due" after the visit (nothing could be
            for n, k in timers.due(bot, [name], [COMEBACK[key]]):     # started, or unreadable): do not loop
                timers.clear(bot, other, k)
        _on(bot, ctx, here)                            # back (an error here is retried by the looting)
        bot.status(account=here["name"], action=BY_KEY["attack_all"].title)
    finally:
        ctx.away = False
    return True

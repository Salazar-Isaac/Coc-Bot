"""Donation modes.

Loot + Donate cycle (the XpIncrease way):
  1. On Main: donate to any request that is still open.
  2. If Main has enough elixir for a whole round ("Main keeps at least" + what one round
     cost last time): the requesting accounts (Looter, Loot + request, Feeder) empty their
     Clan Castle and request, taking turns (a round goes on after the last account of the
     round before) - as many as fit the 10-minute request cooldown together with the
     donating - then Main donates to all of them. Back to 2.
  3. Not enough elixir: Main and the Looter account(s) loot until full, then back to 1.
Donate only: steps 1-2, until the elixir runs low (or for the set number of rounds).
"""

import logging
import time

from .. import config
from ..core.context import BotError
from ..actions import account as account_actions
from ..actions import clan, loot
from .common import StopRun, active_accounts, with_recovery

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


OVER_COOLDOWN = 1.05            # a round (requests + donating) may take at most 5% longer than the cooldown


def round_size(bot, state, total):
    """About how many accounts fit a request round: by the time they have all requested and Main
    has donated to them, the first one's request cooldown (read from the game, 10 min) is over
    again. Only an estimate for the log - request_round stops on the clock.
    "Accounts per round" on the Donate page overrides it."""
    fixed = bot.settings["donate"].get("round_accounts", 0)
    if fixed:
        return min(fixed, total)
    cooldown = state.get("request_cooldown") or 600
    per = (state.get("request_secs") or 20) + (state.get("donate_secs") or 8)
    return max(1, min(total, int(cooldown * OVER_COOLDOWN // per)))


def _requesters_in_turn(bot, state):
    """The requesting accounts in turn order: from the one after the last account that requested
    (the list goes round), so every account gets its turn - not always the first ones."""
    requesters = active_accounts(bot, REQUEST_ROLES)
    names = [a["name"] for a in requesters]
    cursor = state.get("request_cursor")
    start = names.index(cursor) if cursor in names else 0
    return requesters[start:] + requesters[:start], requesters


def _other_clan(bot, acc, main):
    """True if this account is known to be in another clan than the Main (its requests never reach the
    Main: e.g. Buggu8, Leader of '#White Devil'). The clan is read on the village after each switch."""
    from ..actions.account import same_name
    mine, theirs = main.get("clan"), acc.get("clan")
    return bool(mine and theirs and not same_name(mine, theirs))


def request_round(bot, state):
    """The requesting accounts empty their Clan Castle and request, taking turns: a round goes on from
    the account after the last one that requested in the round before (after #20 comes #21, and after
    the last one #2 again), so no account waits for its own request cooldown while others are ready.
    As many request as fit the request cooldown: the whole round - their requests plus Main donating to
    all of them - takes about the 10 minutes an account waits to request again. An account still on
    cooldown is passed over (its turn comes again), never waited for. Returns requests sent."""
    order, requesters = _requesters_in_turn(bot, state)
    if not requesters:
        raise StopRun("No requesting accounts (roles 'Looter', 'Loot + request' or 'Feeder') in the Accounts tab.")
    main = _main_account(bot)
    cooldown = state.get("request_cooldown") or 600
    fixed = bot.settings["donate"].get("round_accounts", 0)
    limit = min(fixed, len(requesters)) if fixed else len(requesters)
    req_secs = state.get("request_secs") or 20
    don_secs = state.get("donate_secs") or 8
    # a stopped round goes on (its clock too) while its first requests are still on cooldown
    sent = state.get("request_sent", 0)
    ago = time.time() - state.get("request_round_at", 0)
    if sent and ago < cooldown:
        log.info("Continuing the request round at %s (%d sent, started %ds ago)", order[0]["name"], sent, ago)
        t0 = time.monotonic() - ago
    else:
        sent, t0 = 0, time.monotonic()
        state["request_round_at"] = time.time()
    log.info("Request round from %s (#%d of %d requesting accounts): %s (request cooldown %dm; about %ds per "
             "request + %ds donating each)", order[0]["name"], requesters.index(order[0]) + 1, len(requesters),
             f"{limit} account(s)" if fixed else
             f"about {round_size(bot, state, len(requesters))} account(s), as many as fit the cooldown",
             cooldown // 60, req_secs, don_secs)
    requested_at = state.setdefault("requested_at", {})
    no_clan = state.setdefault("no_clan", {})
    waiting, elsewhere, tried = [], [], 0
    for i, acc in enumerate(order):
        name = acc["name"]
        if sent >= limit:
            state["request_cursor"] = name
            break
        # its own cooldown (when it requested last is known): passed over, its turn comes again
        left = requested_at.get(name, 0) + cooldown - max(5, req_secs - 6) - time.time()
        if left > 0:
            waiting.append(f"{name} ({left:.0f}s)")
            continue
        if _other_clan(bot, acc, main):
            elsewhere.append(f"{name} ({acc.get('clan')})")
            continue
        if time.time() - no_clan.get(name, 0) < NO_CLAN_RECHECK:
            continue                                   # had no clan recently: do not switch to it again
        if sent and not fixed:
            elapsed = time.monotonic() - t0
            finish = elapsed + req_secs + (sent + 1) * don_secs
            if finish > cooldown * OVER_COOLDOWN:
                log.info("Round full after %d request(s) in %ds: one more would make requests + donating "
                         "about %ds, longer than the %dm cooldown - %s goes first next round", sent, elapsed,
                         finish, cooldown // 60, name)
                state["request_cursor"] = name
                break
        state["request_cursor"], state["request_sent"] = name, sent
        config.save_state(state)
        bot.status(account=name, progress=f"request {sent + 1}", action="Requesting")
        started = time.monotonic()
        tried += 1
        if _switch(bot, acc, state):
            if _other_clan(bot, acc, main):            # its clan was just read: not the Main's
                elsewhere.append(f"{name} ({acc.get('clan')})")
            else:
                bot.request_cooldown = None
                result = with_recovery(bot, f"request on {name}",
                                       lambda a=acc: clan.feeder_turn(bot, a, bot.settings))
                if result:
                    sent += 1
                    requested_at[name] = time.time()
                    _learn(state, "request_secs", time.monotonic() - started)
                    if bot.request_cooldown:
                        old = state.get("request_cooldown")
                        if old and abs(bot.request_cooldown - old) > 30:
                            log.info("The clan's request cooldown is now %dm %ds (was %dm): the rounds follow it",
                                     bot.request_cooldown // 60, bot.request_cooldown % 60, old // 60)
                        state["request_cooldown"] = bot.request_cooldown
                        cooldown = bot.request_cooldown    # this round already uses the new time
                else:
                    log.info("%s did not request (%s)", name, "see above" if result is not None else "gave up")
        if acc.get("_no_clan"):
            no_clan[name] = time.time()
        # the next account goes on from here (also after an account that could not request)
        state["request_cursor"] = order[(i + 1) % len(order)]["name"]
        config.save_state(state)
    state["request_sent"] = 0
    config.save_state(state)
    if waiting:
        log.info("Still on request cooldown, passed over this round: %s", ", ".join(waiting))
    if elsewhere:
        log.info("In another clan than %s (their requests never reach it), not requesting: %s", main["name"],
                 ", ".join(elsewhere))
    log.info("Requests sent: %d of %d tried in %ds; next round starts with %s", sent, tried,
             time.monotonic() - t0, state.get("request_cursor") or requesters[0]["name"])
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


def donation_cycle(bot, main, state, between=None):
    """The XpIncrease way, always starting on Main (you may have spent its elixir meanwhile):
      1. not enough elixir for a whole round -> "low" (time to loot);
      2. donate to requests that are still open, then check the elixir again;
      3. while it covers a whole round: every requesting account requests, Main donates.
    between(): called before every request round (e.g. a freed builder is put to work first).
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
        if between is not None:
            between()
        request_round(bot, state)
        donated, elixir = donate_round(bot, main, state)
        if max_rounds and n >= max_rounds:
            return "rounds"
        if donated == 0:
            log.info("Nothing was donated this round (no requests or nothing to give)")
            return "idle"

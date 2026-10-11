"""Helpers shared by modes: error recovery, 'when full' and 'when done' behaviour."""

import logging
import subprocess
import winsound

from ..core.context import BotError
from ..core.control import BotStopped, control, is_user_abort
from ..states import ensure_game, go_home, restart_game

log = logging.getLogger("bot")


class StopRun(Exception):
    """The run should end normally (e.g. 'when full: stop')."""


def with_recovery(bot, label, fn, attempts=3):
    """Run fn(); on errors save a screenshot, get the game back to the village and retry."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (BotStopped, StopRun):
            raise
        except Exception as e:  # noqa: BLE001 - any failure: recover and retry
            if is_user_abort(e):
                raise BotStopped() from e
            if isinstance(e, BotError):
                log.warning("%s: %s (attempt %d/%d)", label, e, attempt, attempts)
            else:
                log.exception("%s: unexpected error (attempt %d/%d)", label, attempt, attempts)
            bot.save_error(label.replace(" ", "-"))
            try:
                if attempt == attempts - 1 or not bot.device.is_game_running() or not go_home(bot, 45):
                    restart_game(bot)
            except (BotStopped, StopRun):
                raise
            except Exception:  # noqa: BLE001
                log.exception("Recovery failed")
    log.error("%s: giving up after %d attempts", label, attempts)
    return None


def when_full(bot, account):
    """Apply the 'When an account is full' setting.
    Returns "next" (go on to the next account) or "again" (loot the same account again)."""
    action = bot.settings.get("when_full", "switch")
    if action == "wait":
        log.info("%s is full. Use your resources, then press Continue (F8).", account["name"])
        bot.status(action=f"{account['name']} full - waiting for you", waiting=True)
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        control.wait_for_user()
        bot.status(waiting=False)
        ensure_game(bot)
        return "again"
    if action == "stop":
        log.info("%s is full. Stopping as configured.", account["name"])
        raise StopRun()
    return "next"


def when_done(bot):
    action = bot.settings.get("when_done", "nothing")
    if action == "close_game":
        log.info("Closing the game")
        bot.device.close_game()
    elif action == "shutdown":
        log.info("Shutting down the PC in 60 seconds (Cancel shutdown in the window to stop it)")
        bot.device.close_game()
        subprocess.run(["shutdown", "/s", "/t", "60", "/c", "Coc-Bot finished. Shutting down in 60 seconds."],
                       creationflags=subprocess.CREATE_NO_WINDOW)
        bot.status(shutdown_pending=True)
    elif action == "sleep":
        log.info("Putting the PC to sleep")
        bot.device.close_game()
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                       creationflags=subprocess.CREATE_NO_WINDOW)


def cancel_shutdown():
    subprocess.run(["shutdown", "/a"], creationflags=subprocess.CREATE_NO_WINDOW)


def chores(bot, acc, phase):
    """Village chores for an account, if its role is enabled for chores.
    phase "arrive": collect resources; "leave": upgrades and research."""
    from ..actions import village
    v = bot.settings.get("village", {})
    if acc.get("role", "loot") not in v.get("on_roles", ["main", "loot", "both", "feeder"]):
        return
    if phase == "arrive" and not v.get("collect", True):
        return
    if phase == "leave" and not (v.get("upgrade_buildings") or v.get("research")):
        return
    bot.status(action="Collecting" if phase == "arrive" else "Upgrading")
    with_recovery(bot, f"chores on {acc.get('name', '?')}", lambda: village.chores(bot, acc, phase), attempts=2)


def active_accounts(bot, roles=None):
    out = [a for a in bot.accounts if a.get("enabled", True) and a.get("role") != "skip"]
    if roles:
        out = [a for a in out if a.get("role") in roles]
    return out

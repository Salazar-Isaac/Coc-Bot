"""Runs the chosen mode in a background thread so the window stays responsive."""

import logging
import threading
import time

from . import catalog, config
from .core import vision
from .core.context import Bot
from .core.control import BotStopped, control, is_user_abort
from .core.devices import make_device
from .core.layout import layout
from .core.profile import profile
from .modes import MODES, load_all
from .modes.common import StopRun, when_done
from .states import ensure_game, restart_game

MAX_AUTO_RESTARTS = 20

log = logging.getLogger("bot")


def missing_templates():
    return [k for k in catalog.REQUIRED if not vision.templates.has(k)]


class Runner(threading.Thread):
    def __init__(self, mode_key, settings, accounts, on_status, on_finished, resume=True):
        super().__init__(daemon=True, name="bot")
        self.mode_key = mode_key
        self.settings = settings
        self.accounts = accounts
        self.on_status = on_status
        self.on_finished = on_finished
        self.resume = resume
        self.bot = None

    def run(self):
        control.reset()
        started = time.time()
        reason = "finished"
        try:
            load_all()
            mode = MODES[self.mode_key]
            profile.use(self.settings.get("profile", profile.name))
            vision.templates.reload()
            vision.digits.reload()
            layout.reload()
            missing = missing_templates()
            if missing:
                raise StopRun("Missing templates (capture them in the Templates tab): " + ", ".join(missing))
            if not vision.digits.ready:
                raise StopRun("Digit images are missing for this profile")

            device = make_device(self.settings)
            self.bot = Bot(device, self.settings, self.accounts, self.on_status)
            state = config.load_state()
            if not self.resume:
                state.pop("loot_all_next", None)
            log.info("Starting '%s' on %s", mode.title, device.describe())
            self.on_status(running=True, mode=mode.title)
            restarts = 0
            while True:
                try:
                    ensure_game(self.bot)
                    mode.run(self.bot, state)
                    break
                except (BotStopped, StopRun):
                    raise
                except Exception as e:  # noqa: BLE001 - keep a long run alive: restart the game and go on
                    if is_user_abort(e) or restarts >= MAX_AUTO_RESTARTS or                             not self.settings.get("auto_restart", True):
                        raise
                    restarts += 1
                    log.exception("Unexpected error; restarting the game and continuing (%d/%d)",
                                  restarts, MAX_AUTO_RESTARTS)
                    self.bot.save_error("crash")
                    try:
                        restart_game(self.bot)
                    except (BotStopped, StopRun):
                        raise
                    except Exception:  # noqa: BLE001
                        log.exception("Game restart failed; trying again in 30 s")
                        control.sleep(30)
            when_done(self.bot)
        except BotStopped as e:
            reason = "stopped"
            log.info("Stopped: %s", e.args[0] if e.args else "Stop pressed")
        except StopRun as e:
            if e.args:                       # could not run (missing setup etc.)
                reason = "stopped"
                log.warning("%s", e.args[0])
            else:                            # e.g. "When full: Stop" - a normal end of the run
                log.info("Run ended")
                try:
                    when_done(self.bot)
                except Exception:  # noqa: BLE001
                    log.exception("'When the run ends' action failed")
        except Exception as e:  # noqa: BLE001
            if is_user_abort(e):
                reason = "stopped"
                log.info("Stopped (mouse moved into a screen corner)")
            else:
                reason = "error"
                log.exception("The bot stopped because of an error")
                if self.bot:
                    self.bot.save_error("crash")
        finally:
            mins = (time.time() - started) / 60
            stats = self.bot.stats if self.bot else {}
            log.info("Run %s after %.0f min. Attacks: %s, searches: %s", reason, mins,
                     stats.get("attacks", 0), stats.get("searches", 0))
            self.on_status(running=False)
            self.on_finished(reason)

"""Stop / pause / continue signals shared by the GUI and the bot thread.

Every input action and every wait calls `control.checkpoint()`, so pressing
Pause or Stop in the window takes effect within ~0.1 s.
"""

import threading
import time


class BotStopped(Exception):
    """Raised inside the bot thread when the user presses Stop."""


def is_user_abort(exc):
    """pyautogui's fail-safe (mouse pushed into a screen corner) counts as Stop."""
    return isinstance(exc, BotStopped) or type(exc).__name__ == "FailSafeException"


class Control:
    def __init__(self):
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._resume = threading.Event()   # set by "Continue" while waiting for the user
        self.waiting_for_user = False

    # --- called from the GUI -------------------------------------------------
    def reset(self):
        self._stop.clear()
        self._pause.clear()
        self._resume.clear()
        self.waiting_for_user = False

    def stop(self):
        self._stop.set()
        self._resume.set()

    def pause(self):
        self._pause.set()

    def unpause(self):
        self._pause.clear()

    def toggle_pause(self):
        if self._pause.is_set():
            self._pause.clear()
        else:
            self._pause.set()

    def resume_from_wait(self):
        self._resume.set()

    @property
    def paused(self):
        return self._pause.is_set()

    @property
    def stopping(self):
        return self._stop.is_set()

    # --- called from the bot thread -----------------------------------------
    def checkpoint(self):
        if self._stop.is_set():
            raise BotStopped()
        while self._pause.is_set():
            if self._stop.is_set():
                raise BotStopped()
            time.sleep(0.1)

    def sleep(self, seconds):
        end = time.monotonic() + seconds
        while True:
            self.checkpoint()
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.1, left))

    def wait_for_user(self):
        """Block until the user presses Continue (or Stop). The bot touches nothing meanwhile."""
        self._resume.clear()
        self.waiting_for_user = True
        try:
            while not self._resume.is_set():
                if self._stop.is_set():
                    raise BotStopped()
                time.sleep(0.1)
        finally:
            self.waiting_for_user = False
        self.checkpoint()


control = Control()

"""Is the PC online? Used to wait out a network outage (and keep tapping the game's Try Again)
instead of restarting the game over and over while there is no internet."""

import logging
import socket
import time

from .control import control

log = logging.getLogger("bot")

# a few well-known servers; any one answering means we are online
HOSTS = [("1.1.1.1", 443), ("8.8.8.8", 443), ("www.google.com", 443), ("8.8.8.8", 53)]


def online(timeout=2.0):
    for host, port in HOSTS:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def wait_until_online(bot=None, max_wait=900):
    """Block until the internet is back (at most max_wait seconds). Returns True if it was down."""
    if online():
        return False
    log.warning("No internet connection: waiting for it to come back")
    if bot is not None:
        bot.status(action="Waiting for the internet")
    start = time.monotonic()
    while not online():
        if time.monotonic() - start > max_wait:
            log.warning("Still no internet after %d min; trying the game anyway", max_wait // 60)
            return True
        control.sleep(5)
    log.info("Internet is back after %d s", time.monotonic() - start)
    return True

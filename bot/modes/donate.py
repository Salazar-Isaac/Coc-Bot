"""Donation modes (the clan screens are mapped in the next build step)."""

from . import register
from .common import StopRun


@register("loot_donate", "Loot + Donate cycle",
          "Main and Loot-only accounts loot; Feeder accounts empty their Clan Castle and request; "
          "the Main account donates to them, repeating while it has elixir. (Coming next)",
          ready=False, order=3)
def run_loot_donate(bot, state):
    raise StopRun("Loot + Donate is not built yet")


@register("donate_only", "Donate only",
          "Feeders request, the Main account donates, repeat. (Coming next)", ready=False, order=4)
def run_donate_only(bot, state):
    raise StopRun("Donate only is not built yet")

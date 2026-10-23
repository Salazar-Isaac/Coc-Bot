"""Bot modes. Imported modules in this folder register modes with @register.

To add a new mode later, create bot/modes/<name>.py:

    from . import register

    @register("my_mode", "My mode", "What it does", uses_accounts=True)
    def run(bot, state):
        ...

Then import it in load_all so it is included in source and packaged builds.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass
class Mode:
    key: str
    title: str
    description: str
    run: Callable
    uses_accounts: bool = True
    ready: bool = True          # False = shown but disabled ("coming soon")
    order: int = 100


MODES = {}


def register(key, title, description, uses_accounts=True, ready=True, order=100):
    def deco(fn):
        MODES[key] = Mode(key, title, description, fn, uses_accounts, ready, order)
        return fn
    return deco


def load_all():
    from . import donate as _donate
    from . import flow as _flow

    return MODES

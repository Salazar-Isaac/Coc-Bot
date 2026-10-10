"""Bot modes. Each module in this folder registers one or more modes with @register.

To add a new mode later, create bot/modes/<name>.py:

    from . import register

    @register("my_mode", "My mode", "What it does", uses_accounts=True)
    def run(bot, state):
        ...

It then appears in the Mode list of the window automatically.
"""

import importlib
import pkgutil
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
    for info in pkgutil.iter_modules(__path__):
        if not info.name.startswith("_") and info.name != "common":
            importlib.import_module(f"{__name__}.{info.name}")
    return MODES

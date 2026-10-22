import os
import sys

ROOT = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(ROOT, "assets")
PROFILES = os.path.join(ASSETS, "profiles")   # one folder per screen layout (templates, digits, layout)
CONFIG = os.path.join(ROOT, "config")
LOGS = os.path.join(ROOT, "logs")
ERROR_SHOTS = os.path.join(LOGS, "errors")

for _d in (PROFILES, CONFIG, LOGS, ERROR_SHOTS):
    os.makedirs(_d, exist_ok=True)

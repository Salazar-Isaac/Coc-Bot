# Coc-Bot

Clash of Clans looting bot with a window, for Google Play Games on PC or Android over ADB.

## Start

```
python main.py
```
or double-click `run.bat` (no console window).

## Tabs

| Tab | What it is for |
|---|---|
| **Run** | Pick a mode, choose what happens when an account is full (switch / wait for me / stop) and when the run ends (nothing / close game / shut down / sleep). Start, Pause (F9), Continue (F8), Stop (F10). Live status and log. |
| **Accounts** | Your Supercell ID accounts in order, with role (Main / Loot only / Feeder / Skip), Town Hall and optional own "full at" amounts. "Read names from the game" fills it from the switch list. |
| **Loot Settings** | Which resources count (gold / elixir / dark), "any" or "all" full, minimum loot to attack, attack plan, battle time, limits, and the "full at" table per Town Hall. |
| **Donate** | Settings for the donation modes (next build step). |
| **Device & Settings** | Google Play Games shortcut, or ADB device (BlueStacks, LDPlayer, MuMu, Nox, phone), screen profile, hotkeys. |
| **Templates** | Every image the bot recognises. Take a screenshot, select a row, drag a box to (re)capture it. "Teach digits" learns the resource font. |

Emergency stop: F10, or push the mouse into a screen corner.

## How it works

- `bot/core/` — device backends (PC window / ADB + scrcpy pinch), image matching, digit reader, OCR, stop/pause.
- `bot/states.py` — recognises the current screen and gets back to the village from anywhere.
- `bot/actions/` — account switching (reads names with OCR), looting, attack plans.
- `bot/modes/` — one file per mode; a new `@register(...)` function appears in the Run tab automatically.
- `config/` — settings.json, accounts.json, attack_plans.json (edit the plan points/keys here).
- `assets/profiles/<profile>/` — templates, digits and click points for one screen size.
- `logs/bot.log`, `logs/errors/` — full log and a screenshot of every problem.

When Supercell changes how a button looks, re-capture it in the Templates tab; no code changes needed.

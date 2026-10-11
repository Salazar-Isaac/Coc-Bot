# Coc-Bot

Clash of Clans bot with a window, for Google Play Games on PC or Android over ADB
(BlueStacks, LDPlayer, MuMu, Nox or a phone).

## Start

```
python main.py
```
or double-click `run.bat` (no console window).

## Modes

| Mode | What it does |
|---|---|
| **Loot all accounts** | Switches through the enabled accounts (roles ticked on the Loot page) and loots each until its watched storages are full. |
| **Loot current account only** | Loots the open account. With "When full: Wait for me" you spend the resources, press Continue (F8) and it loots again. |
| **Loot + Donate cycle** | Main and Loot-only accounts loot until full → every "Loot + request" and Feeder account empties its Clan Castle and requests → Main donates to all requests → repeat while Main has more elixir than "Main keeps at least" → loot again. |
| **Donate only** | The request → donate part of the cycle. |
| **Village chores only** | Visits the accounts without attacking: collects resources, starts building upgrades and research. |

Account roles: **Main** (loots, donates) · **Loot only** · **Loot + request** (loots in "Loot all", requests in donation modes) · **Feeder** (only requests) · **Skip**.

## Village chores (Village page)

- **Collect**: one tap per full collector type (gold, elixir, dark) plus the loot cart, when arriving on an account.
- **Upgrade buildings**: reads the builder menu (the "1/5" counter), takes the game's suggested upgrades first, skips
  your "Never upgrade" list (heroes and walls by default) and never goes below your reserve.
- **Research**: same for the laboratory.
- Prices are read from the Confirm button (also discounted green prices); only the button with a resource price is
  pressed. Boost, Finish Now and Hammer/Book confirms are never touched; "buy with gems" offers are closed.

## Smart donations (Donate page)

The bot reads every request card: who asked, the message, and the free space for troops / spells / siege
(e.g. 34/50). Items whose name or keywords appear in the message ("loons please" → Balloon) go first, then your
priority list, and it stops exactly when the space is used (each item has a housing space). Optionally it only
donates to your own accounts.

## Pages

Dashboard (mode, options, Start / Pause F9 / Continue F8 / Stop F10, live stats and log) ·
Accounts · Loot · Donate · Village · Device · Templates · Logs.
Emergency stop: F10, or push the mouse into a screen corner.

## How it works

- **Any window size**: the picture is scaled to a 1080-high "game space" and buttons are
  pinned to the screen edge they belong to; in windowed mode the Google Play Games
  title bar and sidebar are detected and cut off.
- **Reading numbers**: digit images of the game font (about 8 ms, exact) — no OCR.
  Account names: RapidOCR, matched strictly on the numbers (Buggu1 ≠ Buggu01).
- **Smart deployment**: finds the scouted base and drops troops on a ring just
  outside it, reads each troop's count, checks that every tap really deployed a unit,
  moves spots that land in the red area and stops when a card is empty.
- **Recovery**: knows the home, army, search, battle, results, reward chest, daily
  reward, character dialogs, chat, donate window, settings, account list and the
  "Anyone there?" popup, and gets back to the village from any of them. Every problem
  saves a screenshot in `logs/errors/`.
- **Never spends gems**: the request button on cooldown (gem price) is detected and skipped.

## Files

- `bot/core/` — devices (PC window / ADB + scrcpy pinch), game space, image matching, digits, OCR, stop/pause.
- `bot/states.py` — screen detection and "go home".
- `bot/actions/` — account switching, looting, attack + deploy zone, clan castle / donating (`troops.py`: housing
  space and keywords), village chores (`village.py`).
- `bot/modes/` — one file per mode; `@register(...)` adds it to the dashboard.
- `gui/` — the window (PySide6).
- `config/` — settings.json, accounts.json, attack_plans.json.
- `assets/profiles/<profile>/` — templates (`name.png`, extra looks `name~2.png`), digits, click points.

When Supercell changes a button, re-capture it on the Templates page; no code changes needed.

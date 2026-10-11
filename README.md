# Coc-Bot

Clash of Clans bot with a window, for Google Play Games on PC or Android over ADB
(BlueStacks, LDPlayer, MuMu, Nox or a phone).

## Setup (once)

1. Install **Python 3.10+** from python.org (tick "Add python.exe to PATH").
2. Double-click **`setup.bat`**. It installs the packages from `requirements.txt` (no virtual
   environment), checks everything with `tools/check_setup.py` and can put a **Coc-Bot** shortcut on
   the desktop.

No PaddleOCR is needed: numbers are read with the game's own digit images, and the few words
(account names, request messages) with RapidOCR, which is small and starts in a few seconds.

To check an existing install at any time: `python tools/check_setup.py`

## Start

Double-click the **Coc-Bot** desktop shortcut or `run.bat`, or run `python main.py`.

## Modes

| Mode | What it does |
|---|---|
| **Loot all accounts** | Switches through the enabled accounts (roles ticked on the Loot page) and loots each until its watched storages are full. |
| **Loot current account only** | Loots the open account. With "When full: Wait for me" you spend the resources, press Continue (F8) and it loots again. |
| **Loot + Donate cycle** | Like XpIncrease, always starting on Main: not enough elixir for a whole round ("Main keeps at least" + what the last round cost) → Main and the Looter accounts loot until full. Enough → Main first donates to requests that are still open, then every Looter / "Loot + request" / Feeder account empties its Clan Castle and requests → Main donates → repeat while the elixir covers another round → loot again. |
| **Donate only** | The same without looting: stops when Main's elixir is too low for a round. |
| **Builder Base only** | Sails to each account's Builder Base (night village), attacks until the daily Star Bonus is complete (or keeps going), collects, upgrades (Builder Hall → new buildings → Cannon / Archer Tower / Mortar), Star Lab research, sails back. Accounts without a Builder Base are skipped. |

"Loot the Builder Base after the home village is full" (Builder Base page) makes every loot mode do the
night village too, right after each account's home village.

**Upgrade plan** (Upgrades page; tick "Upgrade" per account on the Accounts page - by default every account
except the Main and Omishrisha): when such an account is looted, free builders are put to work first if it has
the resources, and again after looting. Order: storages → army camp → barracks / dark barracks / spell factories
(new troops and spells) → blacksmith → hero hall → laboratory, pet house → archer tower, cannon → Town Hall (only
when nothing above can be upgraded any more; from Town Hall 16 its weapon gets all 5 stars first). Gems are never
spent. Builder Base attacks are ended after 60 seconds (Builder Base page).

**Android phone / emulator** (Device page → Android): only adb is used (screenshots + taps), nothing is
mirrored or recorded and the PC stays free. The connected phone is picked automatically; at start the bot measures
how big the game draws its buttons on that screen (phones: bigger, with margins for the camera cut-out).

Account roles: **Main** (loots, donates) · **Looter** (loots in every mode, also in the cycle, and requests) · **Loot + request** (loots in "Loot all", only requests in donation modes) · **Feeder** (only requests) · **Skip**.

Accounts are switched the way the old completeid/XpIncrease scripts did it: one 0.5 s drag moves the Supercell ID
list exactly 4 accounts, so the bot drags straight to the account's page (keep the Accounts page in the game's
list order), reads the names there and taps. If the game shows **Try Again** (connection lost) the bot waits for
the internet and taps it; **Reload** (another device opened the account) or **Reload Game** (idle) are tapped and
the bot checks it is still on the same account, else opens it again.

## When is an account full?

The bot measures each account's real storage size from the resource bar (amount ÷ how full the bar is,
within about 1 %), so "full" means *that account's* storages minus a margin (Loot page, default 5 lakh:
a 3 crore storage is looted until 2.95 crore). Accounts whose storages are smaller than their Town Hall
suggests are handled, and if storages stop growing for a few attacks the account counts as full anyway.
The same applies to the Builder Base.

## Army

"Army recipe to use before looting" (Loot page) switches every account to a Saved Recipe by name
(e.g. your E-Dragon + Clone recipe called "loot") before it attacks. The "E-Dragons + Clone" plan reads
the key on each troop card, so it works with whatever the account has.

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

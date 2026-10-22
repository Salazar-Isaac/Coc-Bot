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
To build the Windows app with its logo embedded in the executable, run `build.bat`. The app is
created in `dist/Coc-Bot/`; `run.bat` and a newly created desktop shortcut use it automatically.
The build carries over existing settings, accounts and attack plans from `config/`.

## Modes

| Mode | What it does |
|---|---|
| **Loot all accounts** | Switches through the enabled accounts (roles ticked on the Loot page) and loots each until its watched storages are full. |
| **Loot current account only** | Loots the open account. With "When full: Wait for me" you spend the resources, press Continue (F8) and it loots again. |
| **Loot + Donate cycle** | Like XpIncrease, always starting on Main: not enough elixir for a whole round ("Main keeps at least" + what the last round cost) → Main and the Looter accounts loot until full. Enough → Main first donates to requests that are still open, then every Looter / "Loot + request" / Feeder account empties its Clan Castle and requests → Main donates → repeat while the elixir covers another round → loot again. |
| **Donate only** | The same without looting: stops when Main's elixir is too low for a round. |
| **Loot + Upgrade** | Accounts #1-#15 of the Accounts page (Buggu01 … Buggu7; set on the Upgrades page) loot until full; on the ones ticked "Upgrade" (all but the Main and Omi ji) the upgrade plan runs before looting (if there are resources) and after looting. |
| **Builder Base upgrades** | The same accounts' Builder Base: attacks as set on the Builder Base page, and the Builder Base plan before and after - new buildings first, then your list (default Cannon, Archer Tower, Mortar), then the Builder Hall when the list is maxed (gear up). |
| **Builder Base only** | Sails to each account's Builder Base (night village), attacks until the daily Star Bonus is complete (or keeps going), collects, upgrades (Builder Hall → new buildings → Cannon / Archer Tower / Mortar), Star Lab research, sails back. Accounts without a Builder Base are skipped. |

"Loot the Builder Base after the home village is full" (Builder Base page) makes every loot mode do the
night village too, right after each account's home village.

**Upgrade plan** (Upgrades page; only in the two upgrade modes): storages → army camp → barracks / dark
barracks / spell factories (new troops and spells) → blacksmith → hero hall → laboratory, pet house → archer
tower, cannon → the buildings you add ("Also upgrade") → Town Hall (only when nothing above can be upgraded any
more; from Town Hall 16 its weapon gets all 5 stars first). Prices are read from the game every time (sales and
price changes are fine) and gems are never spent. Builder Base attacks are ended after 60 seconds. When the bot
starts the game it closes the Google Play Games store window that opens with it.

**Android emulator** (Device page → Android): set the emulator to 1920×1080 and switch on its ADB. Only adb
is used (screenshots + taps), nothing is mirrored or recorded and the PC stays free. The running emulator is
picked automatically.

**Google Play Games without moving the PC mouse**: on the Device page, leave **Use background input** enabled
(the default). The bot posts input messages to the game window rather than moving the system cursor or refocusing
an already-open game. Some Google Play Games versions may ignore background input; if that happens, disable
this option or use Android over ADB instead. Starting a game that is not already open may still activate it.

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
(e.g. your E-Dragon + Clone recipe called "loot") before it attacks. The attack-plan dropdown includes
**Troop Spam** (swipe troop-bar slot 1 around the perimeter) and **E-Dragon Perimeter** (put E-Dragons in
troop-bar slot 1), alongside saved plans such as "E-Dragons + Clone". The selected plan is used by both
Loot all and Loot current account. On ADB, these presets assume the usual order: troop in slot 1, siege in
slot 4, heroes in slots 5-8, and the first spell in slot 9; edit `config/attack_plans.json` if your army
differs.
The **Valkyries / Sneaky Goblins / Super Minions** plan selects the primary troop with its configured
key/slot, keeps one continuous drag through the perimeter corners, then deploys an available siege
machine, available heroes and their abilities, and 11 Earthquake clicks. On ADB, put the main troop in
slot 1, siege in slot 3, heroes in slots 4-9, and Earthquake in slot 10. Choose Curve or Random region
under **Earthquake placement**. Capture the Super Dragon, Log Launcher, and Siege Barracks troop-card
templates to recognize the optional Super Dragon and prioritize Log Launcher over Siege Barracks;
without siege templates, the plan deploys the first detected siege card (or its configured slot on ADB).

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
- **Event Lavaloon**: optionally deploys the entire event stack when exactly one troop-bar card
  shows `x50`; multiple matching cards are skipped rather than guessed.
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

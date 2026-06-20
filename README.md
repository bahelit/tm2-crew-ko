# tm2-crew-ko — Knockout + Bowl of the Night

A **Trackmania 2 Stadium** event system:

- A **Knockout** game mode (ManiaScript) — slowest racer(s) eliminated each round
  until one winner remains.
- A **PyPlanet** controller app (`apps/knockout/`) that runs cups, a daily **Bowl
  of the Night (BOTN)**, an always-on match HUD, season leaderboards, and planet
  payouts.

The mode and the app talk over a frozen callback contract (`KO*` ModeScript
callbacks), defined and parsed in one place: `apps/knockout/callbacks.py`.

---

## Repository layout

```
apps/knockout/
  __init__.py            # AppConfig: settings + controller wiring + startup mode
  callbacks.py           # KO* callback contract: registrations + pure parsers
  score_modes.py         # pure: points-by-placement tables
  hud_format.py          # pure: HUD time/gap/label formatting
  botn.py                # Bowl of the Night controller + pure time helpers
  loader_fix.py          # self-healing jinja loader (late-loaded app templates)
  season.py              # pure season aggregation + SeasonController
  config.py              # cup presets JSON loader
  export.py              # CSV + Discord-markdown export
  payouts.py             # planet payouts by placement
  controllers/           # PyPlanet-heavy controllers
    cup.py  capture.py  live.py  results.py  commands.py
  models/                # MatchInfo, PlayerScore, CupInfo, CupMatch (peewee)
  views/                 # on-screen UI: HUD, widget, countdowns, results, ...
    templates/           # Manialink XML
Modes/Trackmania/
  Knockout.Script.txt    # the game mode (#Extends RoundsBase2)
  Libs/crew/Notify.Script.txt   # our own minimal message lib
  Base/                  # RoundsBase2 + chain, shipped for review (server-provided)
```

Pure, testable modules stay at the package top level; PyPlanet-coupled
controllers live under `controllers/`.

---

## Install

### PyPlanet app
1. Copy `apps/knockout/` into your PyPlanet project's `apps/` directory.
2. Add it to your `APPS` list (Python settings `settings/apps.py`, or YAML):
   ```python
   APPS = {
       'default': [
           # ... core + contrib apps ...
           'apps.knockout',
       ]
   }
   ```
3. Restart PyPlanet. The `knockout_*` tables are auto-created on first start.

### Game mode
1. Copy `Modes/Trackmania/Knockout.Script.txt` and `Modes/Trackmania/Libs/crew/`
   into your dedicated server's `Scripts/` tree (so the paths resolve to
   `Scripts/Modes/TrackMania/Knockout.Script.txt` and
   `Scripts/Libs/crew/Notify.Script.txt`).
2. Set the mode in the playlist / matchsettings XML.
3. Do **not** set `S_UseLegacyXmlRpcCallbacks` — PyPlanet forces it to `0`, and
   the mode's callbacks are built for that.

> The `Modes/Trackmania/Base/` scripts (`RoundsBase2`, `ModeTrackmania`,
> `ModeBase2`, `ModeBase`) are shipped only for review — they are provided by the
> server install; the title pack does not redistribute the stock `Libs/Nadeo/*`.

---

## Startup &amp; modes

On boot the app puts the server into a **resting state** chosen by the
`startup_mode` configuration. Nothing else needs to be running for this to work —
set it once and the server comes up ready to play.

| Mode | What the server does on boot |
|---|---|
| `none` *(default)* | Leaves the server's own configured mode untouched. |
| `knockout` | Loads **TimeAttack** and idles, waiting for an admin `//cup on`. |
| `botn` | Auto-starts a **Bowl of the Night** (nightly TimeAttack practice → knockout, cycling a weekly playlist). |

### Where to set it

`startup_mode` can be set two ways. A `KNOCKOUT_STARTUP_MODE` key in the PyPlanet
settings file **wins** over the live `startup_mode` setting, so the boot mode can
be pinned in config for launch-and-play:

- **Settings file** (recommended for launch-and-play):
  - Python settings (`settings/base.py` or `settings/local.py`):
    ```python
    KNOCKOUT_STARTUP_MODE = 'botn'   # 'knockout' | 'botn' | 'none'
    ```
  - YAML settings (`settings/base.yaml`):
    ```yaml
    KNOCKOUT_STARTUP_MODE: botn
    ```
- **Live setting** (`//settings`): set `startup_mode` to `none` / `knockout` /
  `botn`. Used only when the file key is absent. Read once at boot, so it takes
  effect on the next controller start.

### Knockout-cup servers (`startup_mode = knockout`)

The server boots into TimeAttack and waits. An admin runs `//cup on` (optionally
`//cup setup <preset>` to push the knockout mode + settings), the cup is played,
and `//cup off` stops the cup and **returns the server to TimeAttack** between
cups. An active cup survives a controller restart and resumes automatically.

**Run through the whole playlist (the Friday cup).** A cup whose map count is set
to `all` (a preset's `"mapcount": "all"`, or `//cup mapcount all`) spans the
**entire current playlist**: the knockout plays each map in turn and the cup
**auto-completes** after the last one, announces the champion, and drops the server
back to TimeAttack. A plain `0` map count is open-ended (never auto-completes), and
a fixed number caps the cup at that many maps.

So a typical Friday cup is: `//cup setup friday` (push the knockout mode), then
`//cup on friday` with the `friday` preset carrying `"mapcount": "all"`.

**Shields (earned saves).** The knockout's earned-shield feature (the round winner
banks a one-time save against elimination, `S_EnableShields`) is a mode setting, so
enable it per cup through its preset — the example `knockout_friday` preset turns it
on. BOTN deliberately leaves shields off (Cup-of-the-Day style); the Friday cup is
where they belong.

### Bowl of the Night (`startup_mode = botn`)

A **nightly** event over a **weekly playlist** — one map per night — recorded as a
single weekly cup (`cup_key = botn`) sized to the playlist length:

1. The server boots (or `//botn on`) into **TimeAttack practice** on that night's
   map, and arms a Python cutoff clock for `botn_cutoff_time`.
2. A right-side overlay counts down the whole time — **"PRACTICE ENDS IN"** to the
   cutoff, then **"KNOCKOUT IN"** through the handoff. It is also re-sent to
   players who connect mid-countdown, with their correct remaining time.
3. At the cutoff the fastest practice time is recorded (for the announcement only).
4. After the `botn_countdown_seconds` handoff window the app switches the **same
   map** to Knockout. The knockout runs `botn_warmup_laps` **warm-up laps**, then
   plays to a winner — which records into the weekly `botn` cup. BOTN re-creates
   TM2020's **Cup of the Day**: a plain knockout with **no shields** (shields are
   forced off; they stay available to the Friday knockout cup — see below).
5. When the knockout ends, the server **advances to the next playlist map** back in
   **TimeAttack**, and the cutoff re-arms for the next night. After the last map the
   weekly cup completes (crowning the week's champion) and a fresh weekly cup opens
   so the cycle continues.

**Admin workflow.** Build a match-settings file with the week's maps (e.g. seven),
launch the server with `startup_mode = botn`, and the cycle above runs unattended:
TimeAttack countdown → knockout (warm-up laps → match → winner) → next map.

**Restart behavior.** On a controller restart, a BOTN still genuinely in its
**practice** phase is resumed (cutoff re-armed). Any other leftover — a knockout
that was handed off, or some other active cup — is replaced with a fresh BOTN, so
a `startup_mode = botn` server always comes back up in practice rather than a
stale knockout.

Because ManiaScript has no wall clock, all BOTN timing lives in Python.

---

## Commands

### Admin (`//`)
| Command | Description |
|---|---|
| `//cup on [key] [name]` | Start a cup (key can match a preset). |
| `//cup off` | Stop the active cup (returns the server to TimeAttack). |
| `//cup setup <preset>` | Push a preset's mode script + settings. |
| `//cup mapcount <n\|all>` / `//cup edition <n>` / `//cup scoremode <id>` | Tune the active cup (`all` = whole playlist, `0` = open-ended). |
| `//cup edit <index>` | Toggle whether a map counts towards the cup. |
| `//cup export` | Write CSV + Discord-markdown standings. |
| `//cup pay [payout]` | Pay planets to the standings (needs `cup_payouts_enabled`). |
| `//botn on [HH:MM]` | Start a Bowl of the Night (optional cutoff override). |
| `//botn off` / `//botn start` | Cancel / skip straight to the knockout. |
| `//botn countdown <seconds>` | Set the practice→knockout handoff countdown. |
| `//ko hud` | Print HUD live state + force a test render (diagnostic). |

### Public (`/`)
`/cup status` · `/cup results` · `/cup matches` · `/cup season [key]` ·
`/cup stats <login>` · `/botn status`

---

## Configuration

All options below are PyPlanet settings, tunable live with `//settings` (stored in
the database). The one exception is the boot mode, which can also be pinned in the
settings file via `KNOCKOUT_STARTUP_MODE` (see [Startup &amp; modes](#startup--modes)).

### Startup
| Setting | Default | Description |
|---|---|---|
| `startup_mode` | `none` | Boot resting state: `none` / `knockout` / `botn`. Overridden by the `KNOCKOUT_STARTUP_MODE` file key. |

### Bowl of the Night
| Setting | Default | Description |
|---|---|---|
| `botn_cutoff_time` | `17:00` | Local `HH:MM` when practice ends and the knockout begins. |
| `botn_countdown_seconds` | `900` | Seconds between practice closing and the knockout starting (15 min). Settable live with `//botn countdown <seconds>`. |
| `botn_warmup_laps` | `3` | Warm-up laps the knockout runs before eliminations begin (mode's `S_WarmUpNb`). `0` = none. |

### Cups
| Setting | Default | Description |
|---|---|---|
| `cup_default_score_mode` | `default` | Points table for new cups (see Score modes). |
| `cup_presets_path` | *(blank)* | Path to the cup presets JSON (names / presets / payouts). |
| `cup_payouts_enabled` | off | Allow `//cup pay` to send real planets to cup winners. |
| `cup_export_path` | *(blank)* | Directory for `//cup export` files (blank = working dir). |
| `save_to_season` | on | When off, cups started from then on are excluded from the season leaderboard. |

### On-screen HUD
| Setting | Default | Description |
|---|---|---|
| `show_match_hud` | on | Always-on left-side match HUD (round, players alive, KOs/round, times) during knockout rounds. Also gates the bottom checkpoint-splits feed below. |
| `show_season_points` | on | Add each racer's running cup-points total as a column on the match HUD. |
| `show_cup_widget` | off | Live standings widget during an active cup (experimental). |

A bottom centre-right **checkpoint-splits feed** rides alongside the match HUD: as
players cross checkpoints during a live round it lists the most recent crossings —
player, checkpoint, and split versus the best time at that checkpoint (leading split
as an absolute time, the rest as a `+gap`). It shows only during live rounds and
follows the `show_match_hud` toggle.

Display settings take effect live — no app reload.

### Chat notifications
| Setting | Default | Description |
|---|---|---|
| `notifications` | on | Master switch for the knockout chat notices below. |
| `show_join` | on | Notify when a player joins the knockout. |
| `show_knockout` | on | Notify when a player is knocked out. |
| `show_winner` | on | Notify when a match winner is determined. |

### Score modes

Selectable per cup with `//cup scoremode <id>`:

| Id | Points |
|---|---|
| `default` | 10, 8, 6, 5, 4, 3, 2, 1 |
| `f1` | 25, 18, 15, 12, 10, 8, 6, 4, 2, 1 |
| `flat` | 1 point for the win |
| `survival` | sum of knockout survival points |

### Cup presets

`cup_presets_path` points at a JSON file with three top-level keys — `names`,
`presets`, and `payouts` — used by `//cup on <key>`, `//cup setup <preset>`, and
`//cup pay`. See `presets_example.json`.

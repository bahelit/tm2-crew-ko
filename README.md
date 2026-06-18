# tm2-crew-ko — Knockout + Bowl of the Evening

A nightly, livestreamed **Trackmania 2 Stadium** event system:

- A **Knockout** game mode (ManiaScript) — slowest racer(s) eliminated each round
  until one winner remains.
- A **PyPlanet** controller app (`apps/knockout/`) that runs cups, the **Bowl of
  the Evening (BOTD)** clock, broadcast overlays, an always-on match HUD, season
  leaderboards, planet payouts, and VOD highlight markers.

The full design is in [`KNOCKOUT_REBUILD_SPEC.md`](KNOCKOUT_REBUILD_SPEC.md).

The mode and the app talk over a frozen callback contract (`KO*` ModeScript
callbacks); it is defined and parsed in one place: `apps/knockout/callbacks.py`
(spec §3.1).

---

## Repository layout

```
apps/knockout/
  __init__.py            # thin AppConfig: settings + controller wiring
  callbacks.py           # KO* callback contract: registrations + pure parsers
  score_modes.py         # pure: points-by-placement tables
  hud_format.py          # pure: HUD time/gap/label formatting
  botd.py                # Bowl of the Evening controller + pure time helpers
  season.py              # pure season aggregation + SeasonController
  markers.py             # pure VOD-marker formatting + MarkersController
  config.py              # cup presets JSON loader
  export.py              # CSV + Discord-markdown export
  payouts.py             # planet payouts by placement
  controllers/           # PyPlanet-heavy controllers
    cup.py  capture.py  live.py  results.py  commands.py
  models/                # MatchInfo, PlayerScore, CupInfo, CupMatch (peewee)
  views/                 # hud / ticker / lower_third / widget / results / ...
    templates/           # Manialink XML
Modes/Trackmania/
  Knockout.Script.txt    # the game mode (#Extends RoundsBase2)
  Libs/crew/Notify.Script.txt   # our own minimal message lib (no domino54)
  Base/                  # RoundsBase2 + chain, shipped for review (server-provided)
tests/                   # pure-core pytest suite (no PyPlanet needed)
```

Pure, testable modules stay at the package top level; PyPlanet-coupled
controllers live under `controllers/`.

---

## Install

### PyPlanet app
1. Copy `apps/knockout/` into your PyPlanet project's `apps/` directory.
2. Add it to `APPS` in your PyPlanet `config.yaml` (see
   `pyplanet_config_example.yaml`):
   ```yaml
   APPS:
     default:
       - 'apps.knockout'
   ```
3. Restart PyPlanet. The four `knockout_*` tables are auto-created on first start.

### Game mode
1. Copy `Modes/Trackmania/Knockout.Script.txt` and `Modes/Trackmania/Libs/crew/`
   into your dedicated server's `Scripts/` tree (so the paths resolve to
   `Scripts/Modes/TrackMania/Knockout.Script.txt` and
   `Scripts/Libs/crew/Notify.Script.txt`).
2. Set the mode in the playlist / matchsettings XML.
3. Do **not** set `S_UseLegacyXmlRpcCallbacks` — PyPlanet forces it to `0`, and
   the mode's callbacks are built for that.

> The `Modes/Trackmania/Base/` scripts (`RoundsBase2`, `ModeTrackmania`,
> `ModeBase2`, `ModeBase`) are shipped only for review. They are provided by the
> server install; the title pack does not redistribute the stock `Libs/Nadeo/*`.

> ⚠️ **The ManiaScript mode is a re-based draft and needs live-server
> validation** before a real event — it could not be compiled here. See the
> "VALIDATE ON A LIVE SERVER" checklist in the header of `Knockout.Script.txt`
> (plug stacking, `Match_LogVersions`, the `ST2::` scores table, survival-points
> field, round-stop, callbacks under legacy-off).

---

## Commands

### Admin (`//`)
| Command | Description |
|---|---|
| `//cup on [key] [name]` | Start a cup (key can match a preset). |
| `//cup off` | Stop the active cup. |
| `//cup setup <preset>` | Push a preset's mode script + settings. |
| `//cup mapcount <n>` / `//cup edition <n>` / `//cup scoremode <id>` | Tune the active cup. |
| `//cup edit <index>` | Toggle whether a map counts. |
| `//cup export` | Write CSV + Discord-markdown standings. |
| `//cup pay [payout]` | Pay planets (needs `cup_payouts_enabled`). |
| `//botd on [HH:MM]` | Start a Bowl of the Evening (optional cutoff override). |
| `//botd off` / `//botd start` | Cancel / skip-to-knockout. |
| `//botd countdown <seconds>` | Set the practice→knockout countdown. |
| `//ko hud` | Print HUD live state + force a test render (diagnostic). |
| `//ko streamstart` / `//ko mark <note>` | VOD marker clock / manual marker. |

### Public (`/`)
`/cup status` · `/cup results` · `/cup matches` · `/cup season [key]` ·
`/cup stats <login>` · `/botd status`

---

## Settings (`//settings`)

Key settings — see `apps/knockout/__init__.py` for the full list and defaults:

- `show_match_hud` (on), `show_overlays` (off), `show_cup_widget` (off),
  `show_season_points` (on) — display toggles; take effect live, no reload.
- `notifications`, `show_join`, `show_knockout`, `show_winner` — chat notices.
- `save_to_season` — off excludes new cups from the season leaderboard.
- `botd_cutoff_time` (`17:00`), `botd_countdown_seconds` (`900`),
  `botd_fastest_shield` (on) — Bowl of the Evening.
- `cup_presets_path`, `cup_default_score_mode`, `cup_payouts_enabled`,
  `cup_export_path` — cup config.
- `vod_markers_enabled`, `vod_markers_path` — VOD highlight markers.

Score modes: `default` (10,8,6,5,4,3,2,1), `f1`, `flat`, `survival`.
Cup presets are a JSON file (`names` / `presets` / `payouts`); see
`presets_example.json`.

---

## Bowl of the Evening flow

`//botd on` starts a one-map cup (`cup_key = botd`), loads TimeAttack practice,
and arms a Python cutoff clock. At `botd_cutoff_time` the fastest practice time is
recorded, a countdown runs, the fastest gets a shield (if enabled), then the app
switches the *same map* to Knockout and plays to a winner — which records into the
`botd` cup and auto-completes. Survives a PyPlanet restart mid-event.

---

## Testing

The pure core runs without PyPlanet:

```bash
pip install pytest && pytest          # or, with no pytest installed:
python3 tests/test_callbacks.py        # each test file self-runs
python3 tests/test_knockout_hud.py
python3 tests/test_knockout_botd.py
python3 tests/test_knockout_aggregation.py
```

Covered: callback parsers (`callbacks.py`), score modes, BOTD time helpers,
season/marker aggregation, HUD formatting. Controllers that touch PyPlanet are
thin wrappers over these pure functions — integration-test them on a dev server
with `S_DebugBotsCount` and `//ko hud`.

---

## Upgrading the database schema

PyPlanet auto-creates missing **tables** but never adds **columns** to an existing
table. `controllers/cup.py` carries an idempotent schema guard (`_ensure_schema`)
that `ALTER TABLE`s any missing column on start — add new `(column, DDL)` pairs to
its `expected` list when a model gains a field. (A fresh install starts with the
correct schema, so the guard is a no-op until the *second* schema change.) For a
larger migration graph, adopt `peewee-migrate` later.

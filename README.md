# tm2-crew-ko

Knockout game mode and PyPlanet app for Trackmania 2 Stadium.

- Knockout mode (`Modes/Trackmania/Knockout.Script.txt`). Slowest racer(s) out each round until one winner remains.
- PyPlanet app (`apps/knockout/`). Cups, the nightly Bowl of the Night (BOTN), match HUD, season standings, optional planet payouts.

The mode sends `KO*` callbacks. The app handles scoring, UI, and scheduling.

[ManiaPlanet](http://maniaplanet.com/) · [ManiaPark](https://maniapark.com/) · [TM Exchange](https://tm.mania.exchange/) · [PyPlanet](https://pypla.net/en/latest/index.html)

Commands, shields, testing, and troubleshooting are in the [admin cheat sheet](ADMIN_CHEATSHEET.md). Updates are in [DEPLOY.md](DEPLOY.md).

---

## Install

Dedicated server. Copy into the server's `Scripts/` tree:

- `Modes/Trackmania/Knockout.Script.txt`
- `Modes/Trackmania/Libs/crew/`

Set the mode in your matchsettings playlist. Leave `S_UseLegacyXmlRpcCallbacks` off.

PyPlanet. Copy `apps/knockout/` into the project's `apps/` directory, add `'apps.knockout'` to `APPS`, and point `DEDICATED` at the server's XML-RPC port and SuperAdmin password. See `pyplanet_settings_example.py`.

Cup presets (`friday`, `weekly`, `quick`) ship in `apps/knockout/presets.json` and load on their own. Set `KNOCKOUT_CUP_PRESETS_PATH` in `settings/base.py` only if you need custom cups. The live equivalent is `cup_presets_path`.

To update a server that already runs this, see [DEPLOY.md](DEPLOY.md). It covers the path map, files a release deletes, and why an update needs a restart rather than `//reload`.

---

## Knockout cup

A multi-map competition. Each map is one knockout. Placements earn cup points. Between cups the server sits in TimeAttack.

Friday cup, whole playlist, shields on:

```
//cup on friday
```

That stops BOTN if it is running, loads Knockout with the Friday settings, and starts a cup across the playlist. `//cup setup knockout_friday` loads the mode without starting a cup.

Deploy both the app and the mode script. Cup points and auto-complete only fire when Knockout finishes a map and emits `KOMatchStandings`. An old mode script can loop forever, or play a clean knockout that sends nothing. If `//ko hud` shows every `KO*` count at 0, deploy both halves and restart both services.

The cup auto-completes after every map in the playlist has been recorded. Chat prints `Cup … — map X / Y recorded`. Then it announces the winner and top 3, opens standings, and returns to TimeAttack. Points on the left HUD update after each recorded map, not mid-race.

| Map count | Behaviour |
|---|---|
| `all` | Whole playlist, then completes |
| `7` (or any number) | Completes after that many maps |
| `0` | Open-ended, never auto-completes |

A plain `//cup on` with no preset is open-ended. Use a preset or `//cup mapcount all`. If a fixed-length cup does not auto-complete, `//cup end` finishes it. It tries to save the current map first, same idea as `//botn end`.

**Warm-up.** Friday: two practice rounds per map (`S_WarmUpNb=2`). BOTN uses `botn_warmup_laps`. A round ends when every player has finished. `S_WarmUpDuration=120` is a 2-minute cap for stragglers, not the round length. Give-up respawns you on the start line. The app zeroes warm-up settings whenever it hands the server back to TimeAttack, otherwise idle maps keep warming up.

**Shields.** Friday on, BOTN off. After warm-up, the second-slowest finish banks a save, but only with 5 or more players in the field. Shields stack up to three (`S_MaxShields`) and carry across every map of the cup. A shield is spent only to save last place, not on DNF or give-up, and it does not knock the next player. The left HUD shows one `+` per banked shield. A new cup or `//ko shields reset` clears the bank. Full rules are in the [cheat sheet](ADMIN_CHEATSHEET.md).

**HUD.** Always on during cups and BOTN. Left match board (practice times, then live knockout order with cup points), checkpoint splits during scored rounds (not warm-up), finish countdown. Stream ticker and elimination lower-third go to pure spectators automatically. Racers do not see them. If the stream machine is not a pure spectator, `/ko stream on`.

---

## Bowl of the Night (BOTN)

A nightly event over a weekly playlist. One map per night, tracked as a weekly cup.

1. Practice. TimeAttack on tonight's map until cutoff (default 17:00). Overlay: `PRACTICE ENDS IN`.
2. Knockout. Same map, short countdown, warm-up, then eliminations. Overlay: `STARTING IN`. No shields.
3. Next night. Next playlist map in TimeAttack, tomorrow's cutoff re-armed.

After the last map the weekly cup completes and a new one opens.

BOTN writes its own knockout settings at the practice-to-knockout handoff, including rounds per map, double-KO, finish countdown, laps, and warm-up. A leftover cup preset cannot change how the knockout runs.

Boot mode in `settings/base.py`:

```python
KNOCKOUT_STARTUP_MODE = 'botn'   # 'knockout' | 'botn' | 'none'
```

| Boot mode | On startup |
|---|---|
| `none` | Leave the server's configured mode alone |
| `knockout` | TimeAttack idle, waiting for `//cup on` |
| `botn` | Auto-start BOTN practice |

---

## Commands

Admin commands use `//`. Public commands use `/`. The [admin cheat sheet](ADMIN_CHEATSHEET.md) has the full list, plus testing tools and troubleshooting.

| Command | What it does |
|---|---|
| `//cup on friday` | Friday cup (playlist, warm-up, shields) |
| `//cup on quick` | 3-map cup |
| `//cup off` | Stop the cup, return to TimeAttack |
| `//cup end` | End now: announce winner, open standings |
| `//botn on` | Start BOTN practice |
| `//botn start` | Skip practice, start knockout |
| `//botn end` | Unstick a knockout, return to practice |
| `//ko hud` | HUD / scoring diagnostic |
| `/cup results` | Standings |
| `/botn status` | BOTN phase and cutoff |

---

## Settings

Change most options with `//settings`. No restart.

| Setting | Default | Notes |
|---|---|---|
| `startup_mode` | `none` | Overridden by `KNOCKOUT_STARTUP_MODE` in the settings file |
| `botn_cutoff_time` | `17:00` | When practice ends |
| `botn_countdown_seconds` | `900` | Practice to knockout delay |
| `botn_warmup_laps` | `3` | Warm-up laps before eliminations |
| `cup_results_autohide` | `60` | Seconds the cup-end results window stays up (`0` = until dismissed) |
| `show_match_hud` | on | Left-side match HUD |
| `cup_presets_path` | blank | Override path. Blank uses bundled `apps/knockout/presets.json` |

Cup presets JSON lives in `apps/knockout/presets.json`. `presets_example.json` is a reference copy.

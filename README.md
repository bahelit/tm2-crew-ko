# tm2-crew-ko

Knockout game mode and PyPlanet app for **Trackmania 2 Stadium**.

- **Knockout mode** (`Modes/Trackmania/Knockout.Script.txt`) — slowest racer(s) eliminated each round until one winner remains.
- **PyPlanet app** (`apps/knockout/`) — runs cups, the daily **Bowl of the Night (BOTN)**, match HUD, season standings, and optional planet payouts.

The mode sends `KO*` callbacks; the app handles everything else (scoring, UI, scheduling).

**Links:** [ManiaPlanet](http://maniaplanet.com/) · [ManiaPark](https://maniapark.com/) · [TM Exchange](https://tm.mania.exchange/) · [PyPlanet](https://pypla.net/en/latest/index.html)

---

## Install

**Dedicated server** — copy into the server's `Scripts/` tree:

- `Modes/Trackmania/Knockout.Script.txt`
- `Modes/Trackmania/Libs/crew/`

Set the mode in your matchsettings playlist. Do not enable `S_UseLegacyXmlRpcCallbacks`.

**PyPlanet** — copy `apps/knockout/` into your project's `apps/` directory, add `'apps.knockout'` to `APPS`, and point `DEDICATED` at the server's XML-RPC port and SuperAdmin password. See `pyplanet_settings_example.py`.

Cup presets (`friday`, `weekly`, `quick`) ship inside `apps/knockout/presets.json` and load automatically — no extra install step. Override with `KNOCKOUT_CUP_PRESETS_PATH` in `settings/base.py` (or the live `cup_presets_path` setting) only if you need custom cups.

---

## Game modes

### Knockout cup

A multi-map competition. Each map is one knockout match; placements earn cup points. The server idles in **TimeAttack** between cups.

**Typical Friday cup** (whole playlist, shields on):

```
//cup on friday
```

That one command stops any running BOTN, loads the Knockout mode with the Friday settings (warm-up, shields, …), and starts a cup that spans the whole playlist. (`//cup setup knockout_friday` is still available if you only want to load the mode without starting a cup.)

**Deploy both the app and the mode script.** Cup points and auto-complete only fire when Knockout finishes a map and emits `KOMatchStandings`. That requires the repo’s `Modes/Trackmania/Knockout.Script.txt` on the dedicated server (not only `apps/knockout/`). An old mode script can loop rounds forever so maps never score.

The cup auto-completes after every map in the playlist has been **recorded** (chat: `Cup … — map X / Y recorded`), announces the **winner** and top 3 in chat, opens standings for everyone online, and returns to TimeAttack. Points on the left HUD update after each recorded map — not mid-race.

| Map count | Behaviour |
|---|---|
| `all` | Spans the whole playlist, then completes |
| `7` (or any number) | Completes after that many maps |
| `0` | Open-ended — never auto-completes |

A plain `//cup on` with no preset defaults to open-ended. Use a preset or `//cup mapcount all`. If a fixed-length cup does not auto-complete, use `//cup end` (best-effort saves the current map first, same idea as `//botn end`).

**Smoke test:** `//cup on quick` or `//cup on friday` then `//cup mapcount 1`, finish one knockout map, confirm chat `map 1 / 1 recorded` and `//cup results` has points. `//ko hud` should show `KOMatchStandings` ≥ 1 after a finished map.

During cups and BOTN the player HUD package is always on (no admin toggles needed): left-side match board (practice times / warm-up, then live knockout order with cup points), bottom checkpoint **splits during scored KO rounds** (not during warm-up), and the finish countdown.

**Stream box:** the ticker + elimination lower-third go to **pure spectators automatically** (your dedicated spectator capture client). During warm-up the ticker shows `PRACTICE`; during rounds it shows racing count / danger bubble. Racers do not see them. If the stream machine is not a pure spectator, run `/ko stream on` (or `/ko stream status` to check). Admins can push them to *everyone* with `show_overlays` in `//settings`.

**Shields** (Friday preset on, BOTN off): after the map’s warm-up laps, the **fastest warm-up finish** earns one save. It is spent only when that player would be eliminated as last place (not on DNF/give-up), and it does **not** push the knock onto the next player. The left match HUD shows `✚` next to holders until the shield is used. Deploy both `apps/knockout/` and `Modes/Trackmania/Knockout.Script.txt` for this to take effect (the mode must include `KO_WarmUp` so warm-up times are recorded for the award).

### Bowl of the Night (BOTN)

A nightly event over a weekly playlist — **one map per night**, tracked as a weekly cup.

1. **Practice** — server runs **TimeAttack** on tonight's map until the cutoff time (default 17:00). Overlay shows **PRACTICE ENDS IN**.
2. **Knockout** — same map switches to knockout after a short countdown. Warm-up laps, then eliminations to a winner. Overlay shows **STARTING IN**. No shields.
3. **Next night** — server advances to the next playlist map in TimeAttack and re-arms tomorrow's cutoff.

After the last map, the weekly cup completes and a new one opens automatically.

Set boot mode in `settings/base.py`:

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

### Admin (`//`)

| Command | Description |
|---|---|
| `//cup on [key] [name]` | Start a cup; `friday` / `weekly` / `quick` apply the linked mode + map count |
| `//cup off` | Stop the cup; return to TimeAttack |
| `//cup end` | End the cup now (announce winner + open standings, same as auto-complete); forces TimeAttack |
| `//cup setup <preset>` | Load a mode preset now (`knockout_friday`, or a cup key like `friday`) |
| `//cup mapcount <n\|all>` | Set map count (`all` = playlist, `0` = open-ended) |
| `//cup edition <n>` | Set edition number |
| `//cup scoremode <id>` | Points table: `default`, `f1`, `flat`, `survival` |
| `//cup edit <index>` | Toggle whether a map counts |
| `//cup export` | Write CSV + Discord standings |
| `//cup pay [payout]` | Pay planets to winners (needs `cup_payouts_enabled`) |
| `//botn on [HH:MM]` | Start BOTN (optional cutoff override) |
| `//botn off` | Stop BOTN |
| `//botn start` | End practice now, start knockout |
| `//botn end` | Fallback: force a stuck knockout to end (record result, return to practice) |
| `//botn countdown <seconds>` | Handoff countdown (e.g. `30` for testing) |
| `//ko hud` | HUD diagnostic |

### Public (`/`)

| Command | Description |
|---|---|
| `/cup status` | Active cup progress |
| `/cup results` | Standings (auto-opens on cup end; still works afterward) |
| `/cup matches` | Maps played |
| `/cup season [key]` | Season leaderboard |
| `/cup stats <login>` | Player cup history |
| `/botn status` | BOTN phase and cutoff time |
| `/ko stream [on/off/status]` | Personal stream overlays (ticker/lower-third); spectators already get them |

---

## Settings

Most options are changed live with `//settings` (no restart). Key ones:

| Setting | Default | Notes |
|---|---|---|
| `startup_mode` | `none` | Overridden by `KNOCKOUT_STARTUP_MODE` in settings file |
| `botn_cutoff_time` | `17:00` | When practice ends |
| `botn_countdown_seconds` | `900` | Practice → knockout delay |
| `botn_warmup_laps` | `3` | Warm-up laps before eliminations |
| `show_match_hud` | on | Left-side match HUD |
| `cup_presets_path` | blank | Override path; blank uses bundled `apps/knockout/presets.json` |

Cup presets JSON format: see `apps/knockout/presets.json` (or the reference copy `presets_example.json`).
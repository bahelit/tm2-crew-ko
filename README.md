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

Optional: copy `presets_example.json` and set `KNOCKOUT_CUP_PRESETS_PATH` in `settings/base.py`.

---

## Game modes

### Knockout cup

A multi-map competition. Each map is one knockout match; placements earn cup points. The server idles in **TimeAttack** between cups.

**Typical Friday cup** (whole playlist, shields on):

```
//cup setup knockout_friday
//cup on friday
```

The cup auto-completes after every map in the playlist has been played, announces the top 3, and returns to TimeAttack.

| Map count | Behaviour |
|---|---|
| `all` | Spans the whole playlist, then completes |
| `7` (or any number) | Completes after that many maps |
| `0` | Open-ended — never auto-completes |

A plain `//cup on` with no preset defaults to open-ended. Use a preset or `//cup mapcount all`. If a fixed-length cup does not auto-complete, use `//cup end`.

During cups and BOTN the left-side match HUD is on by default (practice times in TimeAttack, then the live knockout board with cup points).

Shields (earned one-time saves) are a mode setting — enabled in the Friday preset, off for BOTN.

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
| `//cup on [key] [name]` | Start a cup (key can match a preset) |
| `//cup off` | Stop the cup; return to TimeAttack |
| `//cup end` | End the cup now (announce top 3, same as auto-complete) |
| `//cup setup <preset>` | Load a preset's mode script and settings |
| `//cup mapcount <n\|all>` | Set map count (`all` = playlist, `0` = open-ended) |
| `//cup edition <n>` | Set edition number |
| `//cup scoremode <id>` | Points table: `default`, `f1`, `flat`, `survival` |
| `//cup edit <index>` | Toggle whether a map counts |
| `//cup export` | Write CSV + Discord standings |
| `//cup pay [payout]` | Pay planets to winners (needs `cup_payouts_enabled`) |
| `//botn on [HH:MM]` | Start BOTN (optional cutoff override) |
| `//botn off` | Stop BOTN |
| `//botn start` | End practice now, start knockout |
| `//botn countdown <seconds>` | Handoff countdown (e.g. `30` for testing) |
| `//ko hud` | HUD diagnostic |

### Public (`/`)

| Command | Description |
|---|---|
| `/cup status` | Active cup progress |
| `/cup results` | Standings (works after cup ends) |
| `/cup matches` | Maps played |
| `/cup season [key]` | Season leaderboard |
| `/cup stats <login>` | Player cup history |
| `/botn status` | BOTN phase and cutoff time |

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
| `cup_presets_path` | blank | Presets JSON for `//cup on` / `//cup setup` |

Cup presets JSON format: see `presets_example.json` (`names`, `presets`, `payouts`).
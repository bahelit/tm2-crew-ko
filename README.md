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

**Deploy both the app and the mode script.** Cup points and auto-complete only fire when Knockout finishes a map and emits `KOMatchStandings`. That requires the repo’s `Modes/Trackmania/Knockout.Script.txt` on the dedicated server (not only `apps/knockout/`). An old mode script can loop rounds forever so maps never score — or, worse, play a flawless knockout while sending no callbacks at all. If `//ko hud` shows every `KO*` count at 0, deploy both halves and restart both services. Three independent breaks in that one path were fixed on 2026-08-02, any one of which silenced the lot:

1. The mode sent `KO*` through the legacy XmlRpc lib, whose enable flag the ModeBase2 chain never sets.
2. The v2 lib boots disabled and PyPlanet sends `XmlRpc.EnableCallbacks` only once, when it connects — so every mode script loaded afterwards (exactly what `//cup on` does) started up mute. The mode now enables the library itself and the app re-arms it each map.
3. The app registered its callbacks under `ModeScriptCallback`, the name of the *transport* callback. PyPlanet dispatches script callbacks as `Script.<name>` (`GbxRemote.handle_scripted`), so nothing was ever routed to them and all eight shared one registry key.

None of the three produced an error on either side — the knockout plays, chats and crowns a winner while the app records nothing.

The cup auto-completes after every map in the playlist has been **recorded** (chat: `Cup … — map X / Y recorded`), announces the **winner** and top 3 in chat, opens standings for everyone online, and returns to TimeAttack. Points on the left HUD update after each recorded map — not mid-race.

| Map count | Behaviour |
|---|---|
| `all` | Spans the whole playlist, then completes |
| `7` (or any number) | Completes after that many maps |
| `0` | Open-ended — never auto-completes |

A plain `//cup on` with no preset defaults to open-ended. Use a preset or `//cup mapcount all`. If a fixed-length cup does not auto-complete, use `//cup end` (best-effort saves the current map first, same idea as `//botn end`).

**Smoke test:** `//cup on quick` or `//cup on friday` then `//cup mapcount 1`, finish one knockout map, confirm chat `map 1 / 1 recorded` and `//cup results` has points. `//ko hud` should show `KOMatchStandings` ≥ 1 after a finished map.

If a map's scores cannot be written to the database, the app now says so in chat and `//ko hud` reports the last score-capture error — `KOMatchStandings` arriving is not by itself proof a map was recorded.

**Testing solo.** Racing alone records nothing: the mode waits for 2 players in `Rounds_WaitForPlayers` before starting a knockout, so maps rotate with an empty `KOMatchStandings` and no cup points — `//ko hud` reports this case explicitly. `//ko fake 6` fixes it by connecting six fake players *and* setting `S_DebugBotsCount=6` so the mode re-creates them at each map start (needed because `Match_StartMap` otherwise zeroes that pool). That setting is Knockout-only, so running `//ko fake` while the server idles in TimeAttack stores the count and applies it when the cup loads the mode — either order works. They fill slots and show on the HUD but never drive, so all of them DNF and the map ends in one round — enough for player counts, HUD layout and a real end-to-end scoring run, not enough for elimination order, warm-up early-end or shields. `//ko fake off` clears them. `//ko simulate 5` skips racing entirely and pushes five fabricated maps through the same `record_match` path a finished map uses, exercising the database writes, cup points, map counter and auto-complete in seconds. Both write real rows, and simulated players use `*simbot1*`-style logins — run them against a throwaway cup.

During cups and BOTN the player HUD package is always on (no admin toggles needed): left-side match board (practice times / warm-up, then live knockout order with cup points), bottom checkpoint **splits during scored KO rounds** (not during warm-up), and the finish countdown.

**Stream box:** the ticker + elimination lower-third go to **pure spectators automatically** (your dedicated spectator capture client). During warm-up the ticker shows `PRACTICE`; during rounds it shows racing count / danger bubble. Racers do not see them. If the stream machine is not a pure spectator, run `/ko stream on` (or `/ko stream status` to check). Admins can push them to *everyone* with `show_overlays` in `//settings`.

**Warm-up (Friday and BOTN):** two practice rounds per map on Friday (`S_WarmUpNb=2`; BOTN reads `botn_warmup_laps`). A round ends as soon as **every player has finished their lap** — `S_WarmUpDuration=120` is only a 2-minute cap for stragglers, not the round length. **Give-up restarts the lap:** the warm-up is practice, so a player who gives up respawns on the start line instead of being parked for the rest of the round (the stock warm-up library sits them out; the mode re-arms them). The round still cannot hang — the library arms its own finish timeout once the first player finishes, and the cap applies regardless. Deploy the mode script so warm-up rounds end early instead of running out the clock.

Warm-up only applies to a knockout: the app zeroes `S_WarmUpNb` / `S_WarmUpDuration` whenever it hands the server back to TimeAttack (cup finished, `//cup off`, BOTN practice). Mode settings are stored server-wide by *name* and outlive the script that set them, so without that reset TimeAttack — which declares the same two settings and runs `MB_WarmUp()` with them — would open every idle map with the knockout's warm-up rounds.

**Shields** (Friday preset on, BOTN off): after the map’s warm-up, the **fastest warm-up finish** earns one save. It is spent only when that player would be eliminated as last place (not on DNF/give-up), and it does **not** push the knock onto the next player. The left match HUD shows `✚` next to holders until the shield is used. Deploy both `apps/knockout/` and `Modes/Trackmania/Knockout.Script.txt` for this to take effect (the mode must include `KO_WarmUp` so warm-up times are recorded for the award).

### Bowl of the Night (BOTN)

A nightly event over a weekly playlist — **one map per night**, tracked as a weekly cup.

1. **Practice** — server runs **TimeAttack** on tonight's map until the cutoff time (default 17:00). Overlay shows **PRACTICE ENDS IN**.
2. **Knockout** — same map switches to knockout after a short countdown. Warm-up laps, then eliminations to a winner. Overlay shows **STARTING IN**. No shields.
3. **Next night** — server advances to the next playlist map in TimeAttack and re-arms tomorrow's cutoff.

After the last map, the weekly cup completes and a new one opens automatically.

**BOTN sets its own knockout configuration** at the practice→knockout handoff — rounds per map, double-KO threshold, finish countdown, laps, warm-up laps (`botn_warmup_laps`) and the 2-minute warm-up cap — instead of inheriting whatever cup preset ran last. Mode settings are stored server-wide by *name*, so an un-set value is simply the previous event's: run `//cup on weekly` (whose preset sets `S_RoundsPerMap=1`) before a BOTN and the night's knockout would have ended after a single round. The left HUD shows which map of the week is being played (`MAP 3 of 5`), and `//ko fake` bots staged during practice are carried into the knockout load the same way a cup carries them.

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
| `//ko splits` | Splits-feed diagnostic |
| `//ko fake <n\|off>` | Testing: connect *n* fake players, or drop them all |
| `//ko simulate [maps] [players]` | Testing: record fabricated maps through the real scoring path |

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
| `cup_results_autohide` | `60` | Seconds the cup-end results window stays up (`0` = until dismissed) |
| `show_match_hud` | on | Left-side match HUD |
| `cup_presets_path` | blank | Override path; blank uses bundled `apps/knockout/presets.json` |

Cup presets JSON format: see `apps/knockout/presets.json` (or the reference copy `presets_example.json`).
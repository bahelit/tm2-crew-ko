# Knockout admin cheat sheet

Admin commands use `//`. Public commands use `/` (listed at the end for reference).

---

## Quick starts

| Goal | Command |
|---|---|
| **Friday cup** (playlist, warm-up, shields) | `//cup on friday` |
| **Quick 3-map cup** | `//cup on quick` |
| **Weekly 5-map cup** | `//cup on weekly` |
| Load Friday mode only (no cup tracking) | `//cup setup friday` |
| Start **Bowl of the Night** | `//botn on` |
| BOTN with custom cutoff | `//botn on 18:30` |

`//cup on friday` stops BOTN if it’s running, loads Knockout + Friday settings, and starts cup tracking.

---

## Cup (`//cup`)

### Run / stop

| Command | What it does |
|---|---|
| `//cup on [key] [name…]` | Start a cup. Keys: `friday`, `weekly`, `quick` (or a custom key from presets). Optional display name after the key. |
| `//cup off` | Stop the cup; return to TimeAttack. |
| `//cup end` | End **now** (announce winner + open standings for everyone, same as auto-complete). Best-effort records the current map first, then forces TimeAttack. |
| `//cup setup <preset>` | Apply mode + settings only (`friday` / `knockout_friday`, etc.). Does **not** start cup scoring. |

### During a cup

| Command | What it does |
|---|---|
| `//cup mapcount <n\|all\|0>` | Set length: number, `all` = whole playlist, `0` = open-ended. |
| `//cup edition <n>` | Set edition number. |
| `//cup scoremode <id>` | Points table: `default`, `f1`, `flat`, `survival`. |
| `//cup edit <index>` | Toggle whether map *index* counts toward the cup. |
| `//cup export` | Write CSV + Discord standings export. |
| `//cup pay [payout]` | Pay planets to winners (only if payouts are enabled in settings). |

### Cup keys (bundled)

| Key | Name | Mode preset | Maps |
|---|---|---|---|
| `friday` | Friday Knockout Cup | `knockout_friday` (2× 2-min WU, shields on) | whole playlist |
| `weekly` | Weekly Knockout Cup | `knockout_rotate` | 5 |
| `quick` | Quick Knockout | `knockout_single` | 3 |

---

## Bowl of the Night (`//botn`)

| Command | What it does |
|---|---|
| `//botn on [HH:MM]` | Start BOTN practice → knockout at cutoff (default from settings, often `17:00`). |
| `//botn off` | Stop BOTN entirely. |
| `//botn start` | Skip remaining practice; start knockout now. |
| `//botn end` | **Fallback:** force a stuck knockout to end, record result, return to practice. |
| `//botn countdown <seconds>` | Practice→KO delay (e.g. `30` for testing; default often `900`). |

BOTN runs **without shields**. One map per night over the weekly playlist.

At the cutoff BOTN pushes its whole knockout configuration (rounds per map, double-KO, finish countdown, laps, warm-up laps + 2-minute cap), so a cup preset that ran earlier cannot bleed into the night — notably `//cup on weekly`, whose `S_RoundsPerMap=1` used to end the BOTN knockout after one round. `//ko fake` bots staged during practice are carried into the knockout load too.

---

## Tools & diagnostics (`//ko`)

| Command | What it does |
|---|---|
| `//ko hud` | Match HUD diagnostic: phase, callback counts, shields held, force-refresh + test render. |
| `//ko splits` | Splits-feed diagnostic: waypoint/finish signal counts, last waypoint payload, round gate, test render. |
| `//ko fake <n\|off>` | Testing: connect *n* fake players (or drop them all). |
| `//ko simulate [maps] [players]` | Testing: record fabricated maps through the real scoring path. |
| `//ko streamstart` | Mark t=0 for VOD highlight timestamps. |
| `//ko mark [note…]` | Manual VOD highlight marker. |

### Testing solo

Two tools for when you are the only one on the server.

**Racing alone scores nothing.** The mode waits for `C_RequiredPlayersNb` (2) players in `Rounds_WaitForPlayers` before it starts a knockout. Solo, warm-up runs and then the map just rotates: `KOMatchStandings` still fires but is **empty**, so no maps are recorded, no cup points appear, and there is no error to explain it. `//ko hud` now says so explicitly.

`//ko fake 6` connects six fake players via the dedicated server's own debug method *and* sets `S_DebugBotsCount=6` so the mode re-creates them at every map start — both are needed, since `Match_StartMap` calls `Users_SetNbFakeUsers(S_DebugBotsCount, 0)` over the same pool and would otherwise wipe them on the next map. They fill slots and appear on the HUD, but **fake players never drive** — so all of them DNF, the mode knocks the whole field in one round, and you win. Good for player counts, HUD layout and a genuine end-to-end scoring run; useless for elimination order, warm-up early-end or shields, none of which can happen without real lap times. `//ko fake off` clears both.

`S_DebugBotsCount` exists only in Knockout, and the server idles in TimeAttack between cups — so running `//ko fake` first cannot push it (the dedicated server rejects unknown settings). That case is handled: the count is remembered and applied automatically when the cup loads Knockout, and chat says so. Either order works.

`//ko simulate 5` fabricates five knockout maps and pushes them through the same `record_match` path a finished map uses — database writes, cup point table, map counter, auto-complete, `/cup results`. No racing at all, so a full cup takes seconds. Field size defaults to 6 and puts connected players first; `//ko simulate 5 8` uses an 8-player field.

**These write real rows.** Synthetic players get `*simbot1*`-style logins so simulated cups are obvious in `/cup results` — run them on a throwaway cup (`//cup on quick`), not the cup you mean to keep.

---

## Shields (Friday)

No admin command — driven by the mode when `S_EnableShields` is on (Friday preset).

| | |
|---|---|
| **Earn** | Fastest warm-up finish → one shield |
| **Spend** | Only when that player would be eliminated (not DNF / give-up) |
| **Effect** | Saves them only; does not knock the next player |
| **HUD** | `✚` next to holders on the left match board |
| **Warm-up** | Friday: **2 rounds** (`S_WarmUpNb=2`); each ends when everyone has finished, capped at 2 min (`S_WarmUpDuration=120`). BOTN uses the same cap with `botn_warmup_laps` rounds. Give-up respawns the player at the start (practice lap, not a withdrawal) — Friday and BOTN alike |
| **Back to TA** | Warm-up settings are zeroed on every return to TimeAttack — mode settings persist by name, so otherwise the idle server keeps warming up |

Deploy **both** `apps/knockout/` and `Modes/Trackmania/Knockout.Script.txt` or mode behavior (warm-up clock, shields, scoring callbacks) won’t match the app.

Shields need the mode’s `KO_WarmUp` (tracks warm-up finish times). An old script that only calls stock `MB_WarmUp` never awards shields.

---

## Troubleshooting

| Problem | Try |
|---|---|
| Cup title shows, no points / never ends | Check `//ko hud`. An *EMPTY standings* line means you are testing with <2 players and no knockout ever ran — use `//ko fake 3`. A *score-capture error* line means the database write failed. `KOMatchStandings=0` with **all** the other `KO*` counts also 0 means the mode is not reporting at all — the knockout plays and chats normally but PyPlanet never hears it. Deploy the latest mode script **and** app, then restart both. Three separate causes were fixed on 2026-08-02, each of which alone silenced all eight: the mode sent through the legacy XmlRpc lib (never enabled in the ModeBase2 chain); the v2 lib boots disabled and PyPlanet only enables it once, at connect, so any mode loaded later by `//cup on` came up mute; and the app registered its callbacks under the transport name `ModeScriptCallback` instead of the `Script.KO*` key PyPlanet actually dispatches to, so payloads that did arrive were dropped inside PyPlanet. |
| HUD `CUP` column stuck on 0 | Normal until a map is **recorded** — it refreshes on map start / map recorded, never mid-race. `//ko hud` prints `maps_played` and the points-cache size; `maps_played=0` means nothing has been recorded yet. |
| `//ko fake` says Knockout is not loaded | Expected before `//cup on` — the idle mode is TimeAttack, which has no `S_DebugBotsCount`. The bots connect anyway and the count is applied when the cup starts. |
| Cup ends a map early (3-map cup done after 2) | The map counter counts **recorded** maps, so a map stored twice ends the cup a map short. `/cup matches` names them — the same map listed twice is the tell. Fixed on 2026-08-02: every map start allocated a match id but only knockout maps ever consumed one, so ids left over from TimeAttack maps and `RestartMap` (`//cup off`, `//cup on`'s mode switch, a BOTN teardown) piled up, and the rotation after the first knockout map "salvaged" a stale one by storing that map again. `//ko hud` now prints the capture state (`stored=`, `this map=`, `awaiting standings for=`) next to `maps_played`. |
| KO stuck / infinite rounds | `//cup end` or `//botn end` (as appropriate). Deploy mode script with BestRace knockout fix. |
| No left HUD | `//ko hud` — reads state and force-renders a test HUD. |
| No bottom splits feed | `//ko splits` — waypoint/finish signal counts, last payload, round gate, force-renders a test panel. |
| Stream box missing ticker | Pure spectators get it automatically; else `/ko stream on` on the stream client. |
| Want mode without scoring | `//cup setup friday` instead of `//cup on friday`. |

---

## Public commands (players / stream)

| Command | What it does |
|---|---|
| `/cup status` | Active cup progress |
| `/cup results` | Standings (auto-opens for everyone on cup end, then closes itself after `cup_results_autohide` seconds — default 60; still works afterward, and reopened by hand it stays until dismissed) |
| `/cup matches` | Maps played |
| `/cup season [key]` | Season leaderboard |
| `/cup stats <login>` | Player cup history |
| `/botn status` | BOTN phase + cutoff |
| `/ko stream [on\|off\|status]` | Personal stream overlays (ticker / lower-third) |

---

## One-liners to remember

```
//cup on friday          # normal Friday event
//cup end                # finish cup now (stuck or early close)
//botn on                # nightly BOTN
//botn start             # skip practice → KO now
//botn end               # unstick BOTN knockout
//ko hud                 # “why is the HUD / scoring weird?”
```

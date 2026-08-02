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
| `friday` | Friday Knockout Cup | `knockout_friday` (3× 2-min WU, shields on) | whole playlist |
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

`//ko fake 6` connects six fake players via the dedicated server's own debug method. They fill slots and appear on the HUD, but **fake players never drive** — so all of them DNF, the mode knocks the whole field in one round, and you win. Good for player counts, HUD layout and a genuine end-to-end scoring run; useless for elimination order, warm-up early-end or shields, none of which can happen without real lap times. `//ko fake off` removes them.

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
| **Warm-up** | Friday: **3 rounds** (`S_WarmUpNb=3`); each ends when everyone has finished or given up, capped at 2 min (`S_WarmUpDuration=120`) |

Deploy **both** `apps/knockout/` and `Modes/Trackmania/Knockout.Script.txt` or mode behavior (warm-up clock, shields, scoring callbacks) won’t match the app.

Shields need the mode’s `KO_WarmUp` (tracks warm-up finish times). An old script that only calls stock `MB_WarmUp` never awards shields.

---

## Troubleshooting

| Problem | Try |
|---|---|
| Cup title shows, no points / never ends | Check `//ko hud`. An *EMPTY standings* line means you are testing with <2 players and no knockout ever ran — use `//ko fake 3`. A *score-capture error* line means the database write failed. `KOMatchStandings=0` with no other line means the mode is not reporting at all — deploy the latest mode script. |
| HUD `CUP` column stuck on 0 | Normal until a map is **recorded** — it refreshes on map start / map recorded, never mid-race. `//ko hud` prints `maps_played` and the points-cache size; `maps_played=0` means nothing has been recorded yet. |
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
| `/cup results` | Standings (auto-opens for everyone on cup end; still works afterward) |
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

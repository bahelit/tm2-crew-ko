# Knockout + Bowl of the Evening — Rebuild Spec

> Greenfield spec for rebuilding the TM2 **Knockout** game mode and the **Bowl of
> the Evening (BOTD)** orchestrator from scratch in a new repository. Derived from
> the existing `tm2-title-packs` implementation; this document is the plan, not a
> port. Where the old design has known rough edges they're called out as
> **Lessons** so the rebuild can do better.

---

## 1. What this is

A nightly, livestreamed **Trackmania Stadium 2 (TM2)** event system:

- A **Knockout** game mode (ManiaScript) where the slowest racer(s) are eliminated
  each round until one winner remains.
- A **Bowl of the Evening (BOTD)** — a daily one-map event: the map runs as open
  TimeAttack practice, then at a configured local time it flips the *same map* into
  Knockout and plays to a single winner. (Called "Cup of the Day / COTD" in the old
  code; renaming to BOTD for the rebuild.)
- A **PyPlanet server-controller app** (Python) that orchestrates cups, the BOTD
  clock, live broadcast overlays, an always-on match HUD, season leaderboards,
  planet payouts, and VOD highlight markers.

**Primary audience is a livestream.** Both the player experience *and* the
viewer/spectator experience are first-class. Overlays, HUD readability, and
"cool for viewers" carry equal weight with gameplay. TM2 server-side
spectator-camera control is unreliable, so director-cam features must be delivered
as on-screen overlays + caster hints, never automated camera cuts.

---

## 2. Goals & non-goals

### Goals
- A clean Knockout mode that emits a stable, documented callback contract.
- A PyPlanet app split into small, testable controllers (no god-object).
- Self-healing state: survives a PyPlanet restart or plugin reload mid-match.
- Broadcast-quality overlays and an always-on match HUD.
- BOTD timing driven entirely from Python (ManiaScript has no wall clock).
- Season leaderboards that are deterministic regardless of later setting changes.
- Pure, unit-testable core logic (scoring, aggregation, time parsing, HUD format).

### Non-goals
- Automated spectator camera control (unreliable in TM2 — overlays only).
- Matchmaking / ELO / cross-server play.
- A web frontend. (A read-only data export is in scope; a hosted site is not.)
- Supporting modes other than Knockout in the same app.

---

## 3. System architecture

Two cooperating halves connected by **ModeScript callbacks** (mode → app) and
**mode settings / script switches** (app → mode).

```
┌────────────────────────┐   ModeScript callbacks    ┌───────────────────────────┐
│  Knockout.Script.txt    │ ────────────────────────▶ │   PyPlanet app (Python)    │
│  (ManiaScript mode)     │                           │   apps/knockout/           │
│                        │ ◀──────────────────────── │                           │
│  - round loop           │   set script / settings   │  controllers + views       │
│  - elimination logic    │   RestartMap              │  DB models                 │
│  - shields              │                           │  overlays / HUD            │
└────────────────────────┘                           └───────────────────────────┘
```

### 3.1 Mode → app callback contract (authoritative)

The mode MUST emit these. The app subscribes to them. **This contract is the
integration boundary — design it first and freeze it.**

| Callback | Payload | Purpose |
|---|---|---|
| `KOPlayerAdded` | `login` | Player entered the knockout (fresh match start). Join notice + seed racing set. |
| `KOPlayerRemoved` | `login` | Player eliminated this round. Elimination overlay + VOD marker. |
| `KOSendWinner` | `login` | Single winner determined. Winner overlay + records the match. |
| `KOMatchStandings` | array of `login:survivalScore` | Final per-player survival scores at map end → cup points. **Required for cups.** |
| `KORoundOrder` | array of `login:rank:cps:time:finished` | Live running order each round → danger highlighting + HUD. |
| `KORoundStart` | `round:total` | Round number / total (0 total = unbounded) → HUD "ROUND x / y". |
| `KOShieldAwarded` | `login` | A racer banked a shield → overlay + marker. |
| `KOShieldUsed` | `login` | A racer auto-spent a shield to survive → overlay + marker. |

**Lesson:** the old app had to *self-heal* when it started mid-match (it never saw
`KOPlayerAdded`, so the racing set was empty and the HUD stayed hidden). It
recovered by seeding the racing set from `KORoundOrder`. Keep `KORoundOrder`
carrying the full currently-racing set every round so this recovery stays cheap —
and make every callback's payload self-describing rather than positional where
practical.

### 3.2 App → mode control

- `mode_manager.set_next_script(script)` + `gbx('RestartMap')` to switch
  TimeAttack ↔ Knockout on the *same map* (BOTD handoff).
- Stage mode settings before a script load (`update_next_settings`, fall back to
  `update_settings`) — e.g. `S_EnableShields` + `S_PreShieldLogins` for the
  fastest-practice shield.

---

## 4. The Knockout game mode (ManiaScript)

### 4.1 Mechanics
- Free-for-all race. Each round, the **slowest** finisher(s) are knocked out.
- **Double-knockout**: knock 2 at once while the field is large, drop to 1 near the
  end (threshold `S_DoubleKnockUntil`).
- **Practice rounds**: opening N rounds with no eliminations (`S_PracticeRounds`).
- **Earned shields**: optionally, the round winner banks a one-time auto-spent save
  that protects them from one elimination (`S_EnableShields`). Pre-granted shields
  via `S_PreShieldLogins` (used by the BOTD fastest-practice reward).
- Minimum 2 players to start. Plays to a single winner.

### 4.2 Mode settings (`<script_settings>` in the playlist XML)

| Setting | Default | Description |
|---|---|---|
| `S_RoundsPerMap` | `0` | Rounds per map (0 = infinite, plays to a winner). |
| `S_DoubleKnockUntil` | `20` | Knock 2 at once until this many remain (0 = off). |
| `S_PracticeRounds` | `0` | Opening rounds with no eliminations (0 = off). |
| `S_EnableShields` | `false` | Round winner banks a one-time save. |
| `S_FinishTimeout` | `20` | Seconds between rounds. |
| `S_ForceLapsNb` | `0` | Laps per round (0 = 1). |
| `S_PreShieldLogins` | `""` | Logins granted a shield at match start (BOTD handoff). |
| `S_AdminHoldStart` / `S_AdminSetPause` | `false` | Admin pause controls. |
| `S_ShowMultilapInfo` | `true` | Show multi-lap info on screen. |
| `S_CustomLayerPath` | `""` | Optional custom background layer XML. |
| `S_DebugBotsCount` | `0` | Fake players for testing. |

**Lesson:** PyPlanet forces `S_UseLegacyXmlRpcCallbacks` to `0`. The mode's custom
callbacks must work in that regime — document it and test it, since "callbacks not
firing" was the top support issue.

### 4.3 Built on
- **Base mode:** `#Extends "Modes/TrackMania/RoundsBase2.Script.txt"`. The old mode
  extended `RoundsBase.Script.txt` (now **deprecated**). Both are the *same*
  ManiaPlanet-4-era framework — the modern `MB_*` block-extension engine with the
  `XmlRpc::`, `Scores::`, `TM::`, `UIModules::`, and `Pause::` libraries. Inheritance
  chain: `Knockout` → `RoundsBase2` → `ModeTrackmania` → `ModeMatchmaking2` →
  `ModeBase2` → `ModeBase`. **This means the rebuild is a re-base, not a rewrite:**
  the old Knockout's callback-emission code and most of its game logic already target
  this framework and port over largely intact (see §4.4 for the deltas).
- **Support libraries — our own, no domino54.** The old mode `#Include`d
  `domino54/SentenceBank` and `domino54/Translations`. The rebuild does **not** copy
  or depend on the domino54 tree. Write our own minimal ManiaScript libraries
  providing only what this mode actually uses (e.g. message/sentence formatting, any
  translation helper) — or drop them entirely in favour of the stock `TextLib` +
  inline strings, since the mode's text needs are small. Keep anything we do write
  small, self-owned, and under our own namespace.

### 4.4 RoundsBase2 / ModeBase integration map

The full plug list comes from `ModeTrackmania.Script.txt`
(`Server → Match → Map → Round → Turn → PlayLoop`, each with Init/Start/End plugs,
prefixed `Match_` for our use). The Knockout layer hooks these:

| Knockout job | Plug / override | Source file |
|---|---|---|
| Register the `KO*` callbacks; init roster | `Match_LoadLibraries` + `Match_StartMap` | RoundsBase2 / ModeTrackmania |
| Read `S_PreShieldLogins`, emit `KOPlayerAdded`, reset survival state | `Match_StartMap` | confirmed (RoundsBase2:113) |
| Emit `KORoundStart`, reset per-round flags | `Match_StartRound` / `Match_InitRound` | confirmed (RoundsBase2:131/137) |
| Live running order each round → `KORoundOrder` | `Match_PlayLoop` (watch waypoints) | confirmed (RoundsBase2:255) |
| **Rank finishers, eliminate slowest 1–2, bank/spend shields, emit `KOPlayerRemoved`** | `Match_EndRound` | ModeTrackmania:570 (`MB_Private_EndRound`) |
| Spawn **survivors only** next round | override `---Rounds_CanSpawn---` | confirmed (RoundsBase2:118) |
| Emit `KOMatchStandings` + `KOSendWinner` | `Match_EndMap` | ModeTrackmania:582 |
| Unregister callbacks | `Match_UnloadLibraries` | confirmed (RoundsBase2:56) |

**Callback emission is unchanged from the old mode.** It already uses the framework's
`XmlRpc::RegisterCallback(name, sig)` / `XmlRpc::CallbackIsAllowed(name)` /
`XmlRpc::SendCallback(...)` idiom (old `Knockout.Script.txt:92–138`, `665–672`, and
the `XmlRpc_KO*` helper functions). PyPlanet receives these as `ModeScriptCallback` —
no change to the §3.1 contract. **Lesson:** the old mode throttles duplicate
`KORoundOrder` emissions with a signature string (`G_PrevRoundOrderSig`); keep that —
the play loop fires every tick and PyPlanet should not be spammed.

**Finish ranking — use the `Scores::` API.** To order a round's racers at
`Match_EndRound`, rank by `Scores::GetPlayerPrevRaceTime(Score)` (this round's
finish time); break out DNFs by `Scores::GetPlayerBestRaceCheckpointsProgress(Score)`
so the player who got furthest survives over one who got less far. The base already
broadcasts standard scores via `Scores::XmlRpc_SendScores(...)` at end-round/map
(ModeBase2:210/226) — the Knockout **survival score** is tracked separately and sent
in `KOMatchStandings`, exactly as the old mode did. Do **not** fight the base's
`Scores::` points repartition; keep survival points in our own per-player variable.

### 4.5 Port checklist (old `Knockout.Script.txt` → RoundsBase2)

**Framework-generation correction.** An earlier draft called this a near-verbatim
re-base. After reading the whole chain that's only half right, and the distinction
matters:

- **Same library generation.** `ModeBase.Script.txt` already `#Include`s the exact
  libs the old mode uses — `ScoresTable2` (`ST2`), `TrackMania/TM2` (`TM2`),
  `WarmUp`, and `TrackMania/XmlRpc` (`XmlRpc`) — and declares `MB_StopRound` /
  `MB_StopMap` as assignable Booleans (ModeBase:154/156). So `ST2::*`, `TM2::*`,
  `XmlRpc::*`, `MB_Sleep`, `MB_SectionRoundNb`, and `MB_StopRound = True` all keep
  working unchanged. The whole `XmlRpc_KO*` callback block (old:683–814) and the
  `RegisterCallback` / `UnregisterCallback` lists port **verbatim**.
- **Different plug skeleton.** The old mode extends the *legacy* `RoundsBase`, whose
  round plugs are **un-prefixed** (`StartServer`, `StartRound`, `PlayLoop`,
  `EndRound`, `EndMap`…). RoundsBase2 sits under `ModeTrackmania`, which splits every
  plug into `Lobby_*` / `Match_*`. So **every plug the old mode defines must be
  renamed to its `Match_*` form**, and a few behaviours move to RoundsBase2's
  narrower hooks. That's real translation work, not a copy.

ManiaScript stacks all `***Label***` definitions across the `#Extends` chain at the
single `+++Label+++` site (parent code first, then child) — which is why the old mode
can define `***StartServer***` without erasing the base's. The Knockout layer relies
on this: its `***Match_StartRound***` / `***Match_PlayLoop***` run **after**
RoundsBase2's.

**Plug rename map:**

| Old plug (legacy RoundsBase) | New plug (RoundsBase2 / ModeTrackmania) | Notes |
|---|---|---|
| `LogVersion` | `Match_LogVersions` | RoundsBase2 uses singular `Match_LogVersion` — **verify** which the chain actually injects (possible upstream typo). |
| `StartServer` | `Match_StartServer` | Callback registration + scores-table setup move here; stacks after RoundsBase2's. |
| `Yield` | `Match_Yield` | Fake-bot + message loop. |
| `InitMap` | `Match_InitMap` | |
| `StartMap` | `Match_StartMap` | `MB_WarmUp` signature **changed** — see below. |
| `StartRound` | `Match_StartRound` | **Drop the manual spawn loop** (`TM2::StartRace/WaitRace` by `IsRacing`); move survivor-gating to the `Rounds_CanSpawn` override. Keep `XmlRpc_KORoundStart` + footer. |
| `PlayLoop` | `Match_PlayLoop` | Waypoint/finish/giveup handling + throttled `XmlRpc_KORoundOrder`. Stacks after RoundsBase2's own play loop (which already force-ends rounds); confirm no double-stop. |
| `EndRound` | `Match_EndRound` | Still an open ModeTrackmania plug (RoundsBase2 doesn't fill it). The elimination logic lands here largely intact. |
| `EndMap` | `Match_EndMap` | `KOMatchStandings` + `KOSendWinner` here. Open plug. |
| `EndServer` | `Match_EndServer` | `UnregisterCallback` list + layer teardown. |
| `---Laps---`, `---TimeAttack---` | *(keep as mode-private overrides)* | These are the old mode's own override blocks, not base hooks — carry over as-is. |

**Spawn-model change (the one structural rewrite).** RoundsBase2 owns
`Match_StartRound` and spawns via the overridable `---Rounds_CanSpawn---`
(RoundsBase2:118, 180). Replace the old mode's manual per-round spawn loop with a
`Rounds_CanSpawn` override that sets `CanSpawn = IsRacing(Score.User)`. This is
cleaner than the legacy approach and is the idiomatic way to express "eliminated
players don't respawn." Eliminations still happen in `Match_EndRound`
(remove from `G_PlayersRacing`); the override just reflects that next round.

**API / call translations to make:**

- `MB_WarmUp(timeLimit)` → `MB_WarmUp(nbWarmUps, timeLimit)` — the v2 signature
  takes a warm-up **count** first (ModeTrackmania:1046). Decide a count (likely 0/1).
- `Scores_Sort(...)` / `Scores_Clear()` (legacy RoundsBase helpers) → `MB_SortScores(...)`
  (ModeTrackmania:1056) + `Scores::` calls; confirm no `Scores_Sort` shim survives.
- **Disable matchmaking:** set `MB_Settings_UseDefaultMatchmaking = False` in
  `Match_Settings` so the `MM_*` gating in RoundsBase2's `Rounds_CanSpawn` /
  `Rounds_PlayLoopSpawnPlayers` and the matchmaking-helper warning stay out of the
  way of a plain FFA knockout night.
- Move "wait for ≥2 players" into the `+++Rounds_WaitForPlayers+++` hook
  (RoundsBase2:176) instead of a bespoke `WaitForPlayers()` inside StartMap.

**Settings reconciliation — both decisions locked:**

- **`S_FinishTimeout` → use the RoundsBase2 mechanism (chosen).** Drop the old
  custom `GetFinishTimeout()` + `CutOffTimeLimit = GetFinishTimeout()` path. Rely on
  the base's `S_UseAlternateRules` + `CutOffTimeLimit` cutoff (RoundsBase2:143). Do
  not redeclare `S_FinishTimeout` with the old "seconds after leader" meaning.
- **Keep `KORoundOrder` de-duplication (chosen).** Carry over `G_PrevRoundOrderSig`
  and the "skip send when signature unchanged" guard verbatim (old:752–777).

**Validate first (highest-risk items):**

1. **Plug stacking actually fires** for `Match_StartRound` / `Match_PlayLoop` defined
   in a child of RoundsBase2 (smoke-test with a log line) — the entire port assumes
   this.
2. The `Match_LogVersions` vs `Match_LogVersion` naming above.
3. That `Match_EndRound` / `Match_EndMap` are genuinely unfilled by RoundsBase2 (grep
   said so) so the elimination/standings code can inject cleanly.

---

## 5. The PyPlanet app

Package `apps/knockout/`. The old app concentrated wiring in one `__init__.py`;
the rebuild should keep the `AppConfig` thin and push behavior into controllers.

### 5.1 Controllers (one responsibility each)

| Controller | Responsibility |
|---|---|
| `CupController` | Active-cup lifecycle (start/stop/complete), links finished matches to a cup, persists state across restarts. One active cup at a time. |
| `CaptureController` | Listens for `KOMatchStandings`, persists `MatchInfo` + `PlayerScore` rows per finished map. |
| `LiveController` | Tracks the *currently-playing* match (racing set, round, danger bubble, phase) and drives overlays + HUD + markers in real time. |
| `BotdController` (was `CotdController`) | BOTD lifecycle: TimeAttack practice → cutoff clock → countdown → Knockout handoff. App-driven clock. |
| `ResultsController` | Compute cup standings, announce top N at cup completion. |
| `SeasonController` | Aggregate standings across all editions of a cup key into a season leaderboard. |
| `MarkersController` | File-based VOD highlight markers (timestamped events). |
| `PayoutsController` | Planet payouts by placement (opt-in, real money). |
| `CommandsController` | Registers all `/` and `//` chat commands, delegates to the above. |

### 5.2 Views (Manialink overlays)

| View | What it shows | Default |
|---|---|---|
| `MatchHud` | Always-on left-side HUD: match #, round x/y, players alive, KOs/round, running order with gap-to-leader, optional season-points column. | on |
| `CupTicker` | Broadcast top-bar ticker: players remaining. | off (stream opt-in) |
| `CupLowerThird` | Transient lower-third: eliminations, winner, shield events. | off (stream opt-in) |
| `CupWidget` | Live cup standings widget. | off (experimental) |

**Lesson:** gate each view on the **live setting value** at refresh time, not a
cached boolean, so toggling `show_match_hud` via `//settings` takes effect with no
app reload. A failed setting read should default the always-on HUD to *visible*, so
a transient error never blanks the broadcast. Provide a `//ko hud` diagnostic that
prints live state, callback counts, and the last refresh error.

### 5.3 Data model (DB tables, PyPlanet/peewee)

| Model | Table | Key fields |
|---|---|---|
| `MatchInfo` | `knockout_match` | `map_start_time` (unique id), `mode_script`, `map_name`, `map_uid` |
| `PlayerScore` | `knockout_playerscore` | `map_start_time`, `login`, `nickname`, `country`, `score` (survival), `score2` (reserved) |
| `CupInfo` | `knockout_cup` | `cup_key`, `name`, `edition`, `map_count`, `score_mode`, `mode_script`, `is_active`, `count_in_season` |
| `CupMatch` | `knockout_cupmatch` | FK `cup`, `map_start_time`, `map_index`, `counts` |

A match is identified by **`map_start_time`** (server-side). Placement is derived by
sorting a match's `PlayerScore` rows by `score`. A cup is a set of `CupMatch` links;
`counts` lets an admin exclude a map. `count_in_season` is stamped at cup creation
from the `save_to_season` setting so season totals stay deterministic.

**Lesson — migrations:** PyPlanet auto-creates missing *tables* but never adds new
*columns*. Adding `count_in_season` to an existing DB crashed the first query. The
old app added a **self-healing schema guard** that `ALTER TABLE`s missing columns on
start. For the rebuild, **adopt a real lightweight migration step** (or keep the
idempotent column-reconcile guard) and bake it in from day one rather than bolting
it on. Document the upgrade path in the README.

### 5.4 Score modes (pure logic)

Points-by-placement tables turning each map's finishing order into cup points.
Tied players (same survival score on a map) share a placement and its points.

| Id | Points |
|---|---|
| `default` | 10, 8, 6, 5, 4, 3, 2, 1 |
| `f1` | 25, 18, 15, 12, 10, 8, 6, 4, 2, 1 |
| `flat` | 1 for the win |
| `survival` | sum of raw knockout survival points |

Keep this a **pure module** (`score_modes.py`): `cup_points(mode_id, placement,
ko_points)`. Already unit-tested in the old repo — carry the tests over.

---

## 6. Bowl of the Evening (BOTD) flow

A daily one-map event recorded as a one-map cup with `cup_key = botd`, so each
evening is an edition and the season leaderboard tracks it.

1. Pick the day's map (matchsettings / current map).
2. `//botd on` (or `//botd on 18:30` to override the cutoff once). App starts a
   one-map cup, loads **TimeAttack**, and arms an `asyncio` waiter for the cutoff.
3. During practice the app tracks each login's best lap (`finish` callback).
4. At the cutoff: practice locks, the fastest practice time is recorded, a
   **countdown** runs (`botd_countdown_seconds`, default 900s) re-announcing at
   10m/5m/2m/1m/30s/10s marks below the total.
5. App stages `S_EnableShields` + `S_PreShieldLogins=<fastest>` (if
   `botd_fastest_shield`), then switches to **Knockout** and `RestartMap` on the
   *same map*.
6. Knockout plays to a winner → records into the `botd` cup → auto-completes.
7. `//botd start` skips the countdown; `//botd off` cancels.

**Restart resilience:** on app start, if a `botd` cup is still active, detect the
current script: `knockout` → resume in the knockout phase; otherwise recompute
today's cutoff and re-arm the practice waiter.

**Lesson:** all BOTD timing is Python because ManiaScript has no wall clock; it
uses the **dedicated server's local clock**. Keep the time parsing
(`parse_hhmm`, `next_occurrence`, `human_duration`, `pick_fastest`) as pure,
unit-tested helpers.

---

## 7. Commands

**Admin (`//`)**

| Command | Description |
|---|---|
| `//cup on [key] [name]` | Start a cup (`key` can match a preset). |
| `//cup off` | Stop the active cup. |
| `//cup setup <preset>` | Push a preset's mode script + settings. |
| `//cup mapcount <n>` | Maps in the cup (0 = open-ended). |
| `//cup edition <n>` | Set edition/week number. |
| `//cup scoremode <id>` | Points table (`default`/`f1`/`flat`/`survival`). |
| `//cup edit <index>` | Toggle whether a map counts. |
| `//cup export` | Write CSV + Discord-markdown standings. |
| `//cup pay [payout]` | Pay planets (needs `cup_payouts_enabled`). |
| `//botd on [HH:MM]` | Start a Bowl of the Evening (optional cutoff override). |
| `//botd off` | Cancel it. |
| `//botd start` | End practice now, start the knockout. |
| `//botd countdown <seconds>` | Set practice→knockout countdown. |
| `//ko hud` | Print HUD live state + force a test render. |
| `//ko streamstart` | Mark t=0 for VOD markers. |
| `//ko mark <note>` | Write a manual VOD marker. |

**Public (`/`)**

| Command | Description |
|---|---|
| `/cup status` | Active cup and progress. |
| `/cup results` | Cup standings window. |
| `/cup matches` | Maps played in the cup. |
| `/cup season [key]` | Season leaderboard across all editions. |
| `/cup stats <login>` | A player's cup history. |
| `/botd status` | BOTD phase, cutoff, current fastest practice time. |

---

## 8. Settings (PyPlanet `//settings`)

**App / notifications**

| Setting | Default | Description |
|---|---|---|
| `notifications` | `true` | Master switch for all chat messages. |
| `show_join` / `show_knockout` / `show_winner` | `true` | Join / KO / winner chat notices. |
| `show_match_hud` | `true` | Always-on left-side match HUD. |
| `show_season_points` | `true` | Add a season-total PTS column to the HUD during a cup. |
| `show_overlays` | `false` | Broadcast ticker + elimination lower-third. |
| `show_cup_widget` | `false` | Live cup standings widget (experimental). |
| `save_to_season` | `true` | Off = new cups excluded from the season leaderboard. |
| `botd_cutoff_time` | `"17:00"` | Server-local `HH:MM` when practice ends and the knockout begins. |
| `botd_countdown_seconds` | `900` | Seconds between practice closing and knockout start. |
| `botd_fastest_shield` | `true` | Grant the fastest practice time a one-time shield. |
| `vod_markers_enabled` | `false` | Append timestamped highlight markers to a file. |
| `vod_markers_path` | `""` | Path to the VOD markers file (blank = disabled). |

**Cup**

| Setting | Default | Description |
|---|---|---|
| `cup_presets_path` | `""` | Path to the presets JSON file. |
| `cup_default_score_mode` | `default` | Score mode for cups started without a preset. |
| `cup_payouts_enabled` | `false` | Allow `//cup pay` to send real planets. |
| `cup_export_path` | `""` | Directory for `//cup export` files (blank = working dir). |

---

## 9. Presets file (JSON)

`cup_presets_path` points at a JSON file with three sections:

- **names** — cup definitions: display name + linked `preset` / `payout` /
  `scoremode` / `mapcount`.
- **presets** — a mode `script` + `settings` to push with `//cup setup`.
- **payouts** — planet amounts by placement, e.g. `[500, 250, 100]`.

`//cup on weekly` pulls name/score mode/map count from the `weekly` definition;
`//cup setup weekly` applies that preset's script + settings.

---

## 10. Testing strategy

Keep the **pure core** independent of PyPlanet so it runs under plain `pytest`:

- `score_modes` — points by placement, ties, survival pass-through.
- BOTD time helpers — `parse_hhmm`, `next_occurrence`, `human_duration`,
  `pick_fastest`, countdown mark selection.
- Standings aggregation — per-map placement, cup totals, season rollup, `counts`
  exclusion, `count_in_season` determinism.
- HUD formatting — gap-to-leader, danger highlighting, column layout (the old repo
  has `test_knockout_hud.py`, `test_knockout_aggregation.py`, `test_knockout_cotd.py`
  to port).
- Callback parsers — `KORoundOrder` / `KORoundStart` payload normalization across
  the shapes a ModeScript array callback arrives in (`_flatten`).

Controllers that touch PyPlanet (`instance.chat`, `mode_manager`, DB) are thin
wrappers around the pure functions; integration-test those against a live/dev
server manually with `//ko hud` and `S_DebugBotsCount`.

---

## 11. Repository layout (proposed)

```
new-repo/
├── README.md                 # install, commands, settings, troubleshooting
├── KNOCKOUT_REBUILD_SPEC.md  # this file
├── pyproject.toml            # app package + pytest config
├── apps/
│   └── knockout/
│       ├── __init__.py       # thin AppConfig: register settings, wire controllers
│       ├── config.py         # presets file loader
│       ├── score_modes.py    # pure: points tables
│       ├── controllers/
│       │   ├── cup.py
│       │   ├── capture.py
│       │   ├── live.py
│       │   ├── botd.py
│       │   ├── results.py
│       │   ├── season.py
│       │   ├── markers.py
│       │   ├── payouts.py
│       │   └── commands.py
│       ├── models/           # MatchInfo, PlayerScore, CupInfo, CupMatch
│       ├── views/            # hud, ticker, lower_third, widget (+ templates/)
│       └── callbacks.py      # parsers + Callback registrations
├── modescript/
│   ├── Knockout.Script.txt       # the game mode (#Extends RoundsBase2)
│   ├── RoundsBase2.Script.txt    # v2 base, shipped for review/build-on
│   └── libs/                     # our own minimal ManiaScript libs (no domino54)
└── tests/                    # pure-core pytest suite
```

(Old repo nests everything under a ManiaPlanet title-pack tree; the rebuild can
flatten to just the app + the one mode script, its v2 base, and our own libs.)

---

## 12. Migration / install notes

- Copy `apps/knockout/` into `<pyplanet>/apps/`, add `apps.knockout` to
  `APPS` in `config.yaml`.
- Copy the mode script, its `RoundsBase2` base, and our own libs under
  `<tm2>/Scripts/`.
- Set the mode in the playlist XML; remove `S_UseLegacyXmlRpcCallbacks` (PyPlanet
  forces `0`).
- Restart PyPlanet — tables are auto-created on first start; columns via the
  migration step (§5.3).

---

## 13. Settled decisions

- **Naming — BOTD everywhere.** No COTD history exists, so there is nothing to keep
  backward-compatible with. Use **BOTD** throughout: commands (`//botd`,
  `/botd`), settings (`botd_*`), and `cup_key = botd`. No `cotd` aliases.
- **Fresh start — no migration of anything.** The new repo begins with an empty
  database and carries over **no** records, settings, or state from the old
  knockout. Season history accrues from the first BOTD/cup run in the new system.
- **Base mode — `RoundsBase2.Script.txt`.** Build the Knockout mode on the v2 base
  (the new directory ships a copy to review); `RoundsBase.Script.txt` is deprecated.
- **Support libraries — build our own.** No domino54 (or any third-party)
  ManiaScript libraries. Write minimal, self-owned libs covering only what the mode
  uses.

## 14. Open questions (decide before building)

1. **Migrations:** adopt a real migration tool (e.g. peewee-migrate) vs. keep the
   idempotent self-healing column guard? (Less urgent now that the DB starts empty,
   but still matters for the *second* schema change.)
2. **Data export:** is a machine-readable results feed (JSON) for an external
   overlay/site in scope, beyond the current CSV + Discord-markdown export?
```

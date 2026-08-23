# Updating a live server

For first-time setup see **Install** in [README.md](README.md). This page is for
pushing a *new version* to a server that already runs the mode and the app.

The work is: copy files into three places, delete anything the release removed,
then restart. There is no build step and no database migration.

---

## 1. Where each file goes

Paths are relative to your dedicated-server root (the directory holding
`GameData/`, `UserData/` and your PyPlanet project).

| In this repo | On the server |
|---|---|
| `Modes/Trackmania/Knockout.Script.txt` | `GameData/Scripts/Modes/TrackMania/Knockout.Script.txt` |
| `Modes/Trackmania/Libs/crew/` | `GameData/Scripts/Libs/crew/` |
| `apps/knockout/` | `<pyplanet-project>/apps/knockout/` |

Two things catch people out:

- The server spells it **`TrackMania`** (capital M); the repo folder is
  `Modes/Trackmania`. On a case-sensitive filesystem a copy into the wrong
  spelling silently creates a second directory the server never reads.
- **`Libs/crew/` is not under `Modes/` on the server.** It sits at
  `GameData/Scripts/Libs/crew/`, one level up from the modes.

`settings/apps.py`, `settings/base.py` and `settings/local.py` belong to *your*
PyPlanet project and are **not** in this repo. A release never overwrites them.
If a release needs one changed, it is called out explicitly in its notes below.

---

## 2. Update procedure

**Do this while nothing is live.** A restart drops everyone mid-race, and
restarting during a cup or BOTN loses the current map's standings if they have
not been recorded yet. Between events, or on a quiet server.

1. **Get the new files.**

   ```
   git pull
   ```

2. **Back up what you are about to replace.** The convention on this server is a
   dated suffix, so the old copy stays next to the new one:

   ```
   cp GameData/Scripts/Modes/TrackMania/Knockout.Script.txt \
      GameData/Scripts/Modes/TrackMania/Knockout.Script.txt.bak-$(date +%F)
   cp -r <pyplanet-project>/apps/knockout <pyplanet-project>/apps/knockout.bak-$(date +%F)
   ```

3. **Copy the mode script and libs.**

   ```
   cp Modes/Trackmania/Knockout.Script.txt \
      GameData/Scripts/Modes/TrackMania/Knockout.Script.txt
   cp -r Modes/Trackmania/Libs/crew/. GameData/Scripts/Libs/crew/
   ```

4. **Copy the app.** Use `--exclude` so you do not wipe the server-side
   `migrations/` directory, which is not in the repo:

   ```
   rsync -a --exclude migrations --exclude __pycache__ \
     apps/knockout/ <pyplanet-project>/apps/knockout/
   ```

   Without `rsync`, `cp -r apps/knockout/. <pyplanet-project>/apps/knockout/`
   works too — it overwrites files and leaves `migrations/` alone. Note that
   neither command **deletes** anything, which is why step 5 exists.

5. **Delete files the release removed.** `cp` and plain `rsync` only add and
   overwrite; a file dropped from the repo stays on the server forever and will
   still be imported. Check the release notes below and remove them by hand.

6. **Clear stale bytecode.** Python can otherwise import a `.pyc` for a module
   whose source you just deleted:

   ```
   find <pyplanet-project>/apps/knockout -name __pycache__ -type d -exec rm -rf {} +
   ```

7. **Restart PyPlanet** — see the next section.

---

## 3. Restart, do not `//reload`

`APPS` in `settings/apps.py` is read **only at boot**. Enabling or disabling a
contrib app therefore has no effect until the process restarts, no matter how
many times you `//reload`.

Mode script changes also need the mode reloaded (`//cup on` switches scripts, or
restart), since the server holds the compiled script in memory.

A full restart is the one procedure that is correct in every case, so just do
that after an update. Use whatever you normally use — commonly one of:

```
systemctl restart pyplanet
```
```
cd <pyplanet-project> && ./manage.py stop && ./manage.py start
```

Restarting PyPlanet does **not** restart the dedicated server, so players stay
connected — but see the note on stale overlays below.

### Stale overlays on already-connected clients

A ManiaLink page stays painted on a client until something replaces it. If a
release retires an overlay, players who were connected across the restart may
keep seeing it until they reconnect. This app sends a one-shot clear on
`on_start()` for overlays it retires itself, but it cannot do that for a
third-party app you disable. If a ghost panel lingers, reconnecting fixes it.

---

## 4. Verify

1. Watch the log on startup — the app logs under `Knockout:`. A traceback
   naming `apps.knockout` means a file did not land; re-check step 4.
2. `//ko hud` — force-renders the match HUD with placeholder rows in its
   tightest layout. If it draws, the templates and geometry are good.
3. `//ko splits` — same for the splits feed.
4. Start a short cup (`//cup on quick`) with `//ko fake 3` and confirm points
   land after the first map.

---

## 5. Rollback

Restore the dated backups from step 2 and restart:

```
cp GameData/Scripts/Modes/TrackMania/Knockout.Script.txt.bak-<date> \
   GameData/Scripts/Modes/TrackMania/Knockout.Script.txt
rm -rf <pyplanet-project>/apps/knockout
mv <pyplanet-project>/apps/knockout.bak-<date> <pyplanet-project>/apps/knockout
```

Then restart. Nothing in a release writes to the database in a way that needs
undoing, so a rollback is just files.

---

## Release notes

### 2026-08-19 — stacking shields and a stable splits board

Two changes, and they need **both halves deployed together**.

*Shields now stack and carry.* An unspent shield used to evaporate at the map change
(`StartKnockout` runs every map and zeroed the bank). Shields now bank up to
`S_MaxShields` (new mode setting, default **3**) and survive every map of a cup. The
bank is cleared only when a new cup starts or an admin runs `//ko shields reset` —
both of which travel as a bumped `S_ShieldEpoch` (new hidden mode setting). A ninth
mode callback, `KOShieldState`, carries the authoritative `login:count` bank so the
app can show a stack it never saw earned (carried over, or earned while the app was
reloading).

*The SPLITS panel is a standings board.* It was a rolling newest-first feed of the
last six crossings, so every checkpoint anybody hit shoved every name down a row. It
is now one row per player ordered by race progress; a row moves only when its player
is genuinely overtaken. Same six rows, same geometry.

**Files to copy:** the whole of `apps/knockout/` plus
`Modes/Trackmania/Knockout.Script.txt`. **Copy the mode script first.**

**Files to DELETE on the server:** none.

**Half-deploy symptoms.** New app + old script: `//ko shields` reports that the
running mode has no `S_ShieldEpoch` / `S_MaxShields`, and `//ko shields reset` is a
silent no-op (nothing else breaks — the app probes before pushing, so it never faults
the settings batch). New script + old app: shields carry correctly mode-side but the
HUD shows at most one `✚` and loses it at each map change.

**The mode script needs a reload, not just a file copy.** The dedicated server holds
it compiled in memory. After restarting PyPlanet, run `//cup setup knockout_friday`
(or `//cup on quick`, or restart the dedicated server) so the new script actually
loads.

### 2026-08-08 — one left-side HUD panel

Two panels were being drawn in the same top-left corner and overlapped during
cups and BOTN. This release leaves exactly one.

**Files to copy:** the whole of `apps/knockout/` plus
`Modes/Trackmania/Knockout.Script.txt` (a comment-only change there — the
recorded HUD footprint changed from `x -159..-95` to `x -159..-113`).

**Files to DELETE on the server** — step 5 above. Both are gone from the repo,
so a copy-based update will not remove them:

```
rm <pyplanet-project>/apps/knockout/views/widget.py
rm <pyplanet-project>/apps/knockout/templates/widget.xml
```

Leaving them is not harmless: `views/__init__.py` no longer imports `CupWidget`,
but a leftover `widget.py` alongside a stale `__pycache__` is exactly the kind of
thing that resurfaces on a later reload. Delete both, then clear bytecode.

**Server settings change (not in this repo).** PyPlanet's Live Rankings widget
sits around `x -124.75` and lands on the match HUD during the BOTN warm-up, the
cup warm-up and the cup match. Comment it out in your `settings/apps.py`:

```python
#'pyplanet.apps.contrib.live_rankings',
```

Back the file up first. This is read only at boot, so it needs the restart in
step 3 — `//reload` will not drop the app.

**What changed on screen:**

- The blue cup standings box is gone. Everything it showed (rank, name, cup
  points) is already on the match HUD, which also has gap times, the elimination
  divider and the bubble highlight.
- The match HUD is now a fixed 46 units wide, down from 64 during a cup, and
  spans `x -159..-113`.
- Long nicknames now clip at roughly 13 characters during a cup. This is the
  cost of the narrower panel. If it reads too short, the tuning knob is `TIME_W`
  in `apps/knockout/views/hud.py`: every unit taken off it goes to the name
  column. It is set to `12` with deliberate headroom, so `11` is safe and `10`
  is probably fine — but the time column has to keep fitting a race over a
  minute, so drop it one unit at a time and check with `//ko hud`, whose top row
  renders `1:01.470` for exactly this reason.
- Long titles step down a font tier rather than wrapping into the stats block.

**Settings removed:** `show_cup_widget` no longer exists. PyPlanet leaves an
orphan row in its settings table; it is inert and needs no cleanup.

**After restarting,** run `//ko hud`. It now renders the tightest layout the
panel has — all four columns, the `MAP` line, a long cup title and an
over-length nickname — so one command shows whether anything clips.

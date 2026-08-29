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

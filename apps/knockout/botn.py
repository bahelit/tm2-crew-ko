"""
Bowl of the Night (BOTN) orchestration.

A nightly event over a weekly playlist. Each night the server runs that night's map
as open **TimeAttack** practice until a configured local time (default 17:00), then
the app switches the *same map* into Knockout (after a few warm-up laps) and runs it
to a single winner. When the knockout ends the server advances to the next playlist
map back in TimeAttack and the cutoff re-arms for the next night. The whole playlist
is one weekly cup (one map per night); when it completes a fresh weekly cup opens so
the cycle continues. Because ManiaScript has no wall-clock access, all timing lives
here in Python.

A right-side overlay counts down the whole time: "PRACTICE ENDS IN" to the cutoff
during practice, then "STARTING IN" through the short handoff window before the
knockout loads.

BOTN re-creates TrackMania 2020's Cup of the Day: a plain knockout with **no shields**.
Only the knockout warm-up length (``S_WarmUpNb``) is staged into the knockout settings at
the cutoff (and shields are forced off); see ``Knockout.Script.txt``. The earned-shield
feature stays available to the Friday knockout cup via its preset's ``S_EnableShields``.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

KNOCKOUT_SCRIPT = 'Modes/TrackMania/Knockout.Script.txt'
TIMEATTACK_SCRIPT = 'TimeAttack.Script.txt'

# BOTN practice is open-ended: the wall-clock cutoff ends it, not the map's own timer.
# Stock TimeAttack defaults S_TimeLimit to 300s, so left alone the practice map would
# auto-advance to the next playlist map every 5 minutes. Setting it to 0 disables that
# auto-advance (TimeAttack's SetTimeLimit installs no cutoff for a non-positive value).
# Re-applied on every practice map_start (PyPlanet stages next-settings only on
# server_start, not RestartMap). If the playlist still advances, on_map_start jumps
# back to the pinned practice map. Resting S_TimeLimit is restored on //botn off.
PRACTICE_TIMELIMIT = 0


# --------------------------------------------------------------------- pure helpers

def parse_hhmm(text, default=(17, 0)):
	"""Parse a ``"HH:MM"`` string into ``(hour, minute)``, falling back to ``default``
	on anything malformed or out of range."""
	try:
		parts = str(text).strip().split(':')
		hour = int(parts[0])
		minute = int(parts[1]) if len(parts) > 1 else 0
		if 0 <= hour <= 23 and 0 <= minute <= 59:
			return (hour, minute)
	except (ValueError, IndexError, AttributeError):
		pass
	return default


def next_occurrence(now, hour, minute):
	"""Return the next ``datetime`` at ``hour:minute`` at or after ``now`` (today if
	still in the future, otherwise tomorrow)."""
	target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
	if target <= now:
		target += timedelta(days=1)
	return target


def pick_fastest(best_times):
	"""Return the login with the lowest (best) practice time, or None if empty.
	``best_times`` is ``{login: race_time_ms}``."""
	if not best_times:
		return None
	return min(best_times, key=lambda login: best_times[login])


def resolve_map_count(raw, playlist_length):
	"""Resolve a configured/typed cup map count. The sentinel ``"all"`` (case-
	insensitive) or a negative number means 'span the whole playlist' and resolves to
	``playlist_length``; anything else is a plain count (0 = open-ended; unparseable
	input falls back to 0). Shared by the weekly BOTN cup and the Friday 'all maps'
	knockout cup."""
	if isinstance(raw, str) and raw.strip().lower() == 'all':
		return playlist_length
	try:
		count = int(raw)
	except (TypeError, ValueError):
		return 0
	return playlist_length if count < 0 else count


def human_duration(seconds):
	"""Human-friendly countdown text: '15 minutes', '1 minute', '2m 30s', '30s'."""
	seconds = max(0, int(seconds))
	if seconds >= 60 and seconds % 60 == 0:
		minutes = seconds // 60
		return '{} minute{}'.format(minutes, '' if minutes == 1 else 's')
	if seconds >= 60:
		minutes, secs = divmod(seconds, 60)
		return '{}m {}s'.format(minutes, secs)
	return '{}s'.format(seconds)


def practice_map_action(phase, force_ta_next, practice_uid, current_uid):
	"""Decide what ``on_map_start`` should do for a live BOTN session.

	Returns one of:
	  * ``'force_ta'`` — post-knockout handoff: reload this map in TimeAttack and pin it.
	  * ``'snap_back'`` — practice/countdown drifted off tonight's map; jump back.
	  * ``'hold'`` — still on the pinned map (or no pin yet); re-apply open-ended TA limit.
	  * ``'idle'`` — not in a phase that needs practice-map enforcement.
	"""
	if force_ta_next:
		return 'force_ta'
	if phase not in ('practice', 'countdown'):
		return 'idle'
	if practice_uid and current_uid and practice_uid != current_uid:
		return 'snap_back'
	return 'hold'


# Remaining-time marks (seconds) at which the countdown re-announces. Only those
# strictly below the total countdown are used, so a 30s countdown warns at 10s and a
# 15-minute one steps down through 10m / 5m / 2m / 1m / 30s / 10s.
COUNTDOWN_MARKS = (600, 300, 120, 60, 30, 10)


# --------------------------------------------------------------------- controller

class BotnController:
	"""Owns the BOTN lifecycle: start practice, schedule the cutoff, and hand off to
	the knockout. One BOTN at a time, mirroring the single active cup."""

	def __init__(self, app):
		self.app = app
		self.instance = app.instance
		self.active = False
		self.phase = 'idle'        # 'idle' | 'practice' | 'countdown' | 'knockout'
		self.best = {}             # login -> best practice time (ms)
		self.cutoff_ts = None      # epoch seconds of the cutoff
		self._task = None          # asyncio waiter for the cutoff
		self._resting_timelimit = None  # server's normal TA S_TimeLimit, to restore on stop
		# Tonight's practice map (UID). Practice must not advance the playlist; if the
		# 5-minute stock TA timer still fires, on_map_start snaps back here.
		self._practice_map_uid = None
		# Guard against a failed JumpToMapIdent looping map_start forever.
		self._snap_back_uid = None
		# Countdown-overlay state, so a player who connects mid-countdown can be sent
		# the overlay with their correct remaining time (the BOTN auto-starts at boot
		# with nobody connected, so the initial display() reaches no one).
		self._overlay_active = False
		self._overlay_ends = None  # epoch seconds the current countdown ends at
		self._overlay_header = 'STARTING IN'
		# Set when a knockout map has just been recorded: the next map that opens must
		# come up in TimeAttack. A queued next-script alone is not enough -- a normal
		# map rotation keeps the running Knockout script -- so on_map_start reloads the
		# map in TimeAttack if the rotation did not switch it. One-shot.
		self._force_ta_next_map = False

	def arm_handoff_immediately(self):
		"""Set the one-shot flag synchronously so map_start cannot win the race."""
		self._force_ta_next_map = True

	async def on_start(self):
		# Always listen for finishes; the handler ignores them unless we are in the
		# practice phase, so this is cheap when no BOTN is running.
		from pyplanet.apps.core.trackmania import callbacks as tm_signals
		from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
		self.app.context.signals.listen(tm_signals.finish, self.on_practice_finish)
		# Catch players who connect while a countdown is on screen (notably the BOTN
		# auto-started at boot, where the first display() reaches nobody).
		self.app.context.signals.listen(mp_signals.player.player_connect, self.on_player_connect)
		# Enforce the knockout->TimeAttack handoff on the map that opens after a knockout
		# (see _force_ta_next_map / on_map_start).
		self.app.context.signals.listen(mp_signals.map.map_start, self.on_map_start)
		# Re-arm after a PyPlanet restart if a BOTN cup is still active and we are
		# back in (or never left) the TimeAttack practice phase.
		await self._maybe_resume()

	async def on_player_connect(self, player=None, **kwargs):
		"""Send the live countdown to a player who just connected, with their correct
		remaining time, so late joiners (and everyone after a boot-time auto-start) see
		it. Existing players are not re-sent, so their running clocks are undisturbed."""
		if not self._overlay_active or self._overlay_ends is None or player is None:
			return
		remaining = int(self._overlay_ends - time.time())
		if remaining <= 0:
			return
		cd = getattr(self.app, 'botn_countdown', None)
		if cd is None:
			return
		try:
			await cd.start(remaining, self._overlay_header, player=player)
		except Exception:
			logger.exception('Knockout: BOTN countdown re-send on connect failed')

	async def on_map_start(self, *args, **kwargs):
		"""Keep BOTN practice on tonight's map with an open-ended TimeAttack limit.

		Two jobs:
		1. Post-knockout handoff (``_force_ta_next_map``): a queued next-script alone does
		   not switch the running mode on a plain rotation, so reload this map in
		   TimeAttack and pin it as the new night's practice map.
		2. Practice/countdown hold: re-apply ``S_TimeLimit=0`` every map start (staging via
		   ``update_next_settings`` only flushes on server_start, so a one-shot write at
		   practice load can miss). If the playlist still advanced, jump back to the pin.
		"""
		if not self.active:
			return
		current_uid = self._current_map_uid()
		action = practice_map_action(
			self.phase, self._force_ta_next_map, self._practice_map_uid, current_uid)

		if action == 'force_ta':
			self._force_ta_next_map = False
			self._snap_back_uid = None
			# Hold this map open through the practice phase (open-ended limit), then reload
			# it in TimeAttack. _load_script does set_next_script + RestartMap, whose map
			# reload is what actually applies the new script.
			await self._hold_practice_timelimit(restart=True)
			self._pin_practice_map()
			logger.info('Knockout: BOTN forced TimeAttack on the post-knockout map')
			return

		if action == 'idle':
			return

		if action == 'snap_back':
			# JumpToMapIdent fires another map_start; if we already tried this pin from
			# this drifted map and are still wrong, stop to avoid a loop.
			if self._snap_back_uid == self._practice_map_uid:
				logger.warning(
					'Knockout: BOTN practice snap-back to %s failed (still on %s); giving up',
					self._practice_map_uid, current_uid)
				self._snap_back_uid = None
				return
			self._snap_back_uid = self._practice_map_uid
			logger.info(
				'Knockout: BOTN practice map drifted to %s; jumping back to %s',
				current_uid, self._practice_map_uid)
			await self._jump_to_practice_map()
			return

		# hold: correct map (or no pin yet) — re-apply open-ended limit and ensure pin.
		self._snap_back_uid = None
		if not self._practice_map_uid:
			self._pin_practice_map()
		await self._hold_practice_timelimit(restart=False)

	async def _maybe_resume(self):
		cup = getattr(self.app.cup, 'active_cup', None)
		if not cup or cup.cup_key != 'botn':
			return
		try:
			script = (await self.instance.mode_manager.get_current_script()) or ''
		except Exception:
			return
		if 'knockout' in script.lower():
			self.active, self.phase = True, 'knockout'
			return
		# Still in practice (TimeAttack loaded): recompute today's cutoff and re-arm. Push
		# the open-ended time limit onto the running map so the resumed practice holds the
		# map until the cutoff instead of cycling on the stock 5-minute timer.
		self.active, self.phase = True, 'practice'
		await self._capture_resting_timelimit()
		await self._hold_practice_timelimit(restart=False)
		self._pin_practice_map()
		await self._arm_from_setting()
		await self._arm_practice_overlay()
		logger.info('Knockout: resumed BOTN practice, cutoff re-armed')

	# ------------------------------------------------------------------ lifecycle

	async def start(self, player=None, time_override=None):
		if self.active:
			await self.instance.chat('$f00>>> A Bowl of the Night is already running. //botn off first.', player)
			return

		hour, minute = parse_hhmm(
			time_override or await self.app.setting_botn_cutoff_time.get_value())
		self.cutoff_ts = next_occurrence(datetime.now(), hour, minute).timestamp()

		# Weekly cup spanning the whole playlist: one map per night, the cup completes
		# (and crowns a weekly champion) after the last map's knockout. A new weekly cup
		# is opened automatically when one completes, so the nightly cycle continues.
		score_mode = await self.app.setting_default_score_mode.get_value()
		await self.app.cup.start_cup(
			cup_key='botn', name='BOTN {}'.format(datetime.now().strftime('%Y-%m-%d')),
			map_count=self.app.playlist_length(), score_mode=score_mode,
		)

		self.best = {}
		self.active, self.phase = True, 'practice'
		self._snap_back_uid = None
		await self._load_practice_script()
		self._pin_practice_map()
		self._arm_cutoff()
		await self._arm_practice_overlay()
		await self.app.commands._refresh_hud_season()

		await self.instance.chat(
			'$09f>>> $fffBowl of the Night$09f started — practice until $fff{:02d}:{:02d}$09f, '
			'then the knockout begins.'.format(hour, minute))

	async def start_fresh(self):
		"""Clear any resumed/stale session and start a brand-new BOTN. Used by the
		startup-mode boot path when a leftover knockout (or other active cup) should be
		replaced with a fresh practice phase. ``start`` closes the stale cup for us when
		it opens the new one, so we only need to reset our own in-memory flags first."""
		self._cancel_task()
		await self._hide_countdown_overlay()
		self.active, self.phase = False, 'idle'
		self.best = {}
		self._practice_map_uid = None
		self._snap_back_uid = None
		await self.start()

	async def stop(self, player=None):
		if not self.active:
			await self.instance.chat('$f00>>> No Bowl of the Night is running.', player)
			return
		self._cancel_task()
		await self._hide_countdown_overlay()
		# Land //botn off on tonight's map if practice drifted, then clear the pin.
		await self._ensure_practice_map()
		self.active, self.phase = False, 'idle'
		self.best = {}
		self._practice_map_uid = None
		self._snap_back_uid = None
		await self.app.cup.stop_cup()
		# Drop the server back to its TimeAttack resting state, restoring the normal map
		# time limit we suppressed for the open-ended practice phase.
		await self._restore_resting_timelimit()
		await self.app.return_to_timeattack()
		await self.app.commands._refresh_hud_season()
		await self.instance.chat('$09f>>> Bowl of the Night stopped.')

	async def force_start(self, player=None):
		"""Admin override: end practice and start the knockout immediately."""
		if not self.active or self.phase != 'practice':
			await self.instance.chat('$f00>>> No BOTN practice phase to start the knockout from.', player)
			return
		self._cancel_task()
		await self._on_cutoff()

	async def end_now(self, player=None):
		"""Admin fallback: force a stuck knockout to conclude (``//botn end``).

		The night's knockout should end on its own (last survivor -> the mode emits
		KOMatchStandings -> the map records and we return to practice). If it ever gets
		stuck, this: (1) best-effort records the current standings through the normal
		capture path so the result is saved and the cup/HUD/transition state update, then
		(2) forces the current map to reload in TimeAttack -- ManiaScript keeps looping a
		stuck knockout no matter what the plugin records, so only a RestartMap actually
		breaks it -- landing the server back in the next practice phase."""
		if not self.active:
			await self.instance.chat('$f00>>> No Bowl of the Night is running.', player)
			return
		if self.phase != 'knockout':
			await self.instance.chat(
				'$f00>>> BOTN is in the $fff{}$f00 phase, not a knockout. Use $fff//botn start$f00 '
				'to begin the knockout, or $fff//botn off$f00 to stop.'.format(self.phase), player)
			return

		# (1) Save the result + run the normal end-of-knockout transition. record_match
		# fans out to on_knockout_recorded (re-arms the next cutoff, opens a fresh weekly
		# cup if this map completed it). If nothing recorded, drive the transition directly
		# so our state still advances.
		await self.app.force_record_current_match(reason='botn end')
		if self.phase == 'knockout':
			await self.on_knockout_recorded()

		# (2) Break the still-running (stuck) knockout: reload the current map in
		# TimeAttack now rather than waiting for a map rotation that will never come.
		await self._force_practice_reload()
		await self.instance.chat(
			'$09f>>> Forced the Bowl of the Night knockout to end — back to practice.', player)

	async def _force_practice_reload(self):
		"""Reload the current map in TimeAttack immediately (set_next_script + RestartMap)
		and hold it open for practice. Used by ``end_now`` to break a stuck knockout that
		will not end on its own. on_knockout_recorded has already flipped us to the
		practice phase and re-armed the cutoff/overlay; this just forces the live mode
		switch, so the one-shot map-rotation handoff is cleared to avoid a double reload."""
		self._force_ta_next_map = False
		await self._hold_practice_timelimit(restart=True)
		self._pin_practice_map()

	async def on_knockout_recorded(self):
		"""The night's knockout map just finished (its standings were recorded). Return
		the server to TimeAttack and re-arm tomorrow's cutoff; the mode's own map-end
		then advances the server to the next playlist map, which loads in TimeAttack.

		If that map completed the weekly cup (the last map of the playlist), the cup
		controller has already crowned the week's champion -- open a fresh weekly cup so
		the nightly cycle continues into the next week."""
		if not self.active or self.phase != 'knockout':
			return

		if getattr(self.app.cup, 'active_cup', None) is None:
			score_mode = await self.app.setting_default_score_mode.get_value()
			await self.app.cup.start_cup(
				cup_key='botn', name='BOTN {}'.format(datetime.now().strftime('%Y-%m-%d')),
				map_count=self.app.playlist_length(), score_mode=score_mode,
			)
			await self.app.commands._refresh_hud_season()

		self.phase = 'practice'
		self.best = {}
		self._snap_back_uid = None
		# Stage the open-ended time limit so the next night's practice map holds until its
		# cutoff instead of cycling on the stock 5-minute TimeAttack timer. (Staging only
		# flushes on server_start; on_map_start / _hold_practice_timelimit re-apply live.)
		await self._apply_mode_settings({'S_TimeLimit': PRACTICE_TIMELIMIT}, stage=True)
		if self.app.playlist_length() <= 1:
			# Single-map playlist: there is no real rotation, so the mode loops a fresh
			# knockout on the *same* map without firing a map_start. The _force_ta_next_map
			# hook below would then never run and the knockout would replay (the reported
			# bug). Force the switch to TimeAttack now via the proven RestartMap reload, then
			# push the open-ended limit straight onto the running script.
			await self._hold_practice_timelimit(restart=True)
			self._pin_practice_map()
		else:
			# Multi-map playlist: queue TimeAttack for the next map WITHOUT a RestartMap so
			# the knockout's map-end advances to the next playlist map on its own (one map
			# per night) and our queued script loads with it. A queued next-script alone does
			# not switch the running mode on a plain rotation, so enforce the switch when the
			# next map opens (which also re-pins that map as the new night's practice map).
			# Clear the old pin so a mid-rotation map_start does not snap back to last night.
			self._practice_map_uid = None
			await self.app.queue_timeattack()
			self._force_ta_next_map = True
		await self._arm_from_setting()
		await self._arm_practice_overlay()
		when = datetime.fromtimestamp(self.cutoff_ts).strftime('%H:%M') if self.cutoff_ts else '—'
		await self.instance.chat(
			'$09f>>> Knockout done. Next map opens in $fffTimeAttack$09f practice — '
			'next Bowl of the Night at $fff{}$09f.'.format(when))

	async def status(self, player=None):
		if not self.active:
			await self.instance.chat('$bbb>>> No Bowl of the Night is running.', player)
			return
		when = datetime.fromtimestamp(self.cutoff_ts).strftime('%H:%M') if self.cutoff_ts else '—'
		fastest = pick_fastest(self.best)
		fastest_txt = await self._name(fastest) if fastest else 'nobody yet'
		await self.instance.chat(
			'$bbb>>> BOTN phase: $fff{}$bbb, knockout at $fff{}$bbb, fastest practice: $fff{}$bbb.'.format(
				self.phase, when, fastest_txt), player)

	# ------------------------------------------------------------- practice tracking

	async def on_practice_finish(self, player=None, race_time=None, **kwargs):
		if self.phase != 'practice':
			return
		login = getattr(player, 'login', None) or (str(player) if player else '')
		if not login:
			return
		try:
			ms = int(race_time)
		except (TypeError, ValueError):
			return
		if ms <= 0:
			return
		best = self.best.get(login)
		if best is None or ms < best:
			self.best[login] = ms
			live = getattr(self.app, 'live', None)
			if live is not None:
				await live._refresh_overlays()

	# ------------------------------------------------------------------ the cutoff

	def _arm_cutoff(self):
		self._cancel_task()
		delay = max(0.0, (self.cutoff_ts or time.time()) - time.time())
		self._task = asyncio.ensure_future(self._cutoff_waiter(delay))

	async def _arm_from_setting(self):
		hour, minute = parse_hhmm(await self.app.setting_botn_cutoff_time.get_value())
		self.cutoff_ts = next_occurrence(datetime.now(), hour, minute).timestamp()
		self._arm_cutoff()

	async def _cutoff_waiter(self, delay):
		try:
			await asyncio.sleep(delay)
			await self._on_cutoff()
		except asyncio.CancelledError:
			pass
		except Exception:
			logger.exception('Knockout: BOTN cutoff waiter failed')

	def _cancel_task(self):
		if self._task is not None and not self._task.done():
			self._task.cancel()
		self._task = None

	async def _on_cutoff(self):
		if not self.active or self.phase != 'practice':
			return
		# Practice is locked in at the cutoff; the countdown is just a heads-up before the
		# knockout loads. BOTN re-creates TM2020's Cup of the Day: a plain knockout with no
		# shields, so we only stage the warm-up laps (no S_EnableShields / pre-shield).
		self.phase = 'countdown'
		fastest = pick_fastest(self.best)

		# Stage the knockout warm-up so it is present when the mode's warm-up / StartKnockout
		# runs after the script switch.
		settings = {}
		try:
			warmup = max(0, int(await self.app.setting_botn_warmup_laps.get_value() or 0))
		except (TypeError, ValueError):
			warmup = 3
		settings['S_WarmUpNb'] = warmup
		# Shields stay off for BOTN (Cup of the Day style); they remain available to the
		# Friday knockout cup via its preset's S_EnableShields.
		settings['S_EnableShields'] = False
		settings['S_PreShieldLogins'] = ''

		fastest_txt = await self._name(fastest) if fastest else 'nobody'
		try:
			total = max(0, int(await self.app.setting_botn_countdown_seconds.get_value() or 0))
		except (TypeError, ValueError):
			total = 900
		await self._run_countdown(total, fastest_txt)

		# Practice may have drifted if the stock TA timer still fired; land KO on the pin.
		await self._ensure_practice_map()
		await self._switch_to_knockout(settings)
		self.phase = 'knockout'
		await self.instance.chat('$09f>>> $fffBowl of the Night$09f knockout is GO!')

	async def _run_countdown(self, total, fastest_txt):
		"""Announce the knockout start, then re-announce at each COUNTDOWN_MARK below
		the total, sleeping the remainder before the handoff. The right-side overlay
		switches to "STARTING IN" and ticks the same countdown client-side."""
		await self.instance.chat(
			'$09f>>> Practice closed — fastest: $fff{}$09f. Knockout in $fff{}$09f!'.format(
				fastest_txt, human_duration(total)))
		await self._show_countdown_overlay(total, 'STARTING IN')
		try:
			remaining = total
			for mark in COUNTDOWN_MARKS:
				if mark >= remaining:
					continue
				await asyncio.sleep(remaining - mark)
				remaining = mark
				await self.instance.chat(
					'$09f>>> Knockout in $fff{}$09f — get ready!'.format(human_duration(mark)))
			if remaining > 0:
				await asyncio.sleep(remaining)
		finally:
			# Always clear the overlay -- including when the BOTN is stopped mid
			# countdown (which cancels the waiter task and unwinds through here).
			await self._hide_countdown_overlay()

	async def _arm_practice_overlay(self):
		"""Show the right-side overlay counting down to the cutoff for the whole
		practice phase ("PRACTICE ENDS IN"). Skipped if the cutoff is already due."""
		remaining = int((self.cutoff_ts or time.time()) - time.time())
		if remaining <= 0:
			return
		await self._show_countdown_overlay(remaining, 'PRACTICE ENDS IN')

	async def _show_countdown_overlay(self, total, header):
		cd = getattr(self.app, 'botn_countdown', None)
		if cd is None or total <= 0:
			return
		# Track the target end time + header so on_player_connect can catch up a late
		# joiner with the right remaining time.
		self._overlay_active = True
		self._overlay_ends = time.time() + total
		self._overlay_header = header
		try:
			await cd.start(total, header)
		except Exception:
			logger.exception('Knockout: BOTN countdown overlay failed to show')

	async def _hide_countdown_overlay(self):
		self._overlay_active = False
		self._overlay_ends = None
		cd = getattr(self.app, 'botn_countdown', None)
		if cd is None:
			return
		try:
			await cd.hide()
		except Exception:
			pass

	async def set_countdown(self, player, seconds):
		try:
			seconds = max(0, int(seconds))
		except (TypeError, ValueError):
			await self.instance.chat('$f00>>> Countdown must be a whole number of seconds.', player)
			return
		await self.app.setting_botn_countdown_seconds.set_value(seconds)
		await self.instance.chat(
			'$09f>>> BOTN countdown set to $fff{}$09f.'.format(human_duration(seconds)), player)

	# --------------------------------------------------------------------- helpers

	async def _load_script(self, script):
		"""Switch the mode script and restart the current map so it loads (keeping the
		same daily map for both practice and the knockout)."""
		try:
			await self.instance.mode_manager.set_next_script(script)
			await self.instance.gbx('RestartMap')
		except Exception:
			logger.exception('Knockout: BOTN failed to load script %s', script)

	async def _load_practice_script(self):
		"""Load TimeAttack for the practice phase with an open-ended time limit so the map
		holds until the wall-clock cutoff.

		Capture the normal limit first (to restore on stop), then load TA and push
		``S_TimeLimit=0`` live. PyPlanet's ``update_next_settings`` only flushes on
		``server_start`` (not ``RestartMap``), so staged writes are best-effort; live
		``update_settings`` plus ``on_map_start`` re-application are the real hold.
		Verify after a short settle and re-apply if the stock 300s default is still set."""
		await self._capture_resting_timelimit()
		await self._hold_practice_timelimit(restart=True)
		await self._verify_practice_timelimit()

	async def _hold_practice_timelimit(self, restart=False):
		"""Push open-ended ``S_TimeLimit`` onto TimeAttack. When ``restart`` is True, also
		queue TimeAttack and RestartMap (practice load / post-KO force / //botn end)."""
		settings = {'S_TimeLimit': PRACTICE_TIMELIMIT}
		# Best-effort staging for hosts that flush next-settings on server_start; live
		# update below (and on_map_start) is what actually holds the map open.
		await self._apply_mode_settings(settings, stage=True)
		if restart:
			# Practice is plain TimeAttack: clear any warm-up rounds a previous
			# knockout left in the server's settings before it loads.
			await self.app.clear_knockout_warmup()
			await self._load_script(TIMEATTACK_SCRIPT)
			if await self._await_script(TIMEATTACK_SCRIPT):
				await self._apply_mode_settings(settings, stage=False)
		else:
			await self._apply_mode_settings(settings, stage=False)

	async def _verify_practice_timelimit(self):
		"""Re-read ``S_TimeLimit`` after the practice load and re-apply if still positive."""
		await asyncio.sleep(0.5)
		try:
			settings = await self.instance.mode_manager.get_settings()
			raw = settings.get('S_TimeLimit')
			value = int(raw) if raw is not None else 0
		except Exception:
			logger.exception('Knockout: BOTN could not verify practice S_TimeLimit')
			return
		if value > 0:
			logger.warning(
				'Knockout: BOTN practice S_TimeLimit still %s after load; re-applying 0', value)
			await self._apply_mode_settings({'S_TimeLimit': PRACTICE_TIMELIMIT}, stage=False)

	def _current_map_uid(self):
		"""UID of the currently loaded map, or None if unknown."""
		try:
			current = self.instance.map_manager.current_map
			return getattr(current, 'uid', None) or None
		except Exception:
			return None

	def _pin_practice_map(self):
		"""Remember the current map as tonight's BOTN practice map."""
		uid = self._current_map_uid()
		if uid:
			self._practice_map_uid = uid
			self._snap_back_uid = None

	async def _jump_to_practice_map(self):
		"""Jump the dedicated server back to the pinned practice map."""
		uid = self._practice_map_uid
		if not uid:
			return
		try:
			await self.instance.map_manager.set_current_map(uid)
		except Exception:
			logger.exception('Knockout: BOTN failed to jump back to practice map %s', uid)
			# Allow a later map_start to retry once the pin is still set.
			self._snap_back_uid = None

	async def _ensure_practice_map(self):
		"""If practice drifted off the pin, jump back before KO handoff or stop."""
		uid = self._practice_map_uid
		if not uid:
			return
		current = self._current_map_uid()
		if current and current != uid:
			logger.info(
				'Knockout: BOTN ensuring practice map %s (currently %s)', uid, current)
			await self._jump_to_practice_map()
			# Brief settle so JumpToMapIdent can land before a script switch.
			await asyncio.sleep(0.5)

	async def _capture_resting_timelimit(self):
		"""Remember the server's normal TimeAttack ``S_TimeLimit`` the first time we override
		it, so ``stop`` can restore it. Mode settings persist across same-script reloads, so a
		plain return-to-TimeAttack would otherwise leave practice's open-ended limit in place
		and the resting server would never cycle maps. A non-positive current value means we
		are already overriding (e.g. a resumed practice), so there is nothing new to capture."""
		if self._resting_timelimit is not None:
			return
		try:
			settings = await self.instance.mode_manager.get_settings()
			raw = settings.get('S_TimeLimit')
			value = int(raw) if raw is not None else 0
		except Exception:
			return
		if value > 0:
			self._resting_timelimit = value

	async def _restore_resting_timelimit(self):
		"""Restore the server's normal TimeAttack time limit (live + staged) so the resting
		server cycles maps again after practice's open-ended override."""
		if self._resting_timelimit is None:
			return
		settings = {'S_TimeLimit': self._resting_timelimit}
		# Stage for any upcoming server_start flush; also push live so RestartMap in
		# return_to_timeattack does not leave S_TimeLimit=0 if staging never runs.
		await self._apply_mode_settings(settings, stage=True)
		await self._apply_mode_settings(settings, stage=False)
		self._resting_timelimit = None

	async def _switch_to_knockout(self, settings):
		"""Hand the daily map from TimeAttack practice into the Knockout, making sure the
		staged knockout settings -- notably the warm-up lap count -- are actually in place
		before the mode reads them.

		The handoff is a race: set_next_script + RestartMap loads the knockout, whose
		Match_StartMap calls MB_WarmUp(S_WarmUpNb, ...). Staging the settings as "next"
		alone proved unreliable -- they could land just after the warm-up count was read,
		giving zero warm-up laps. So we (1) stage them for the load, (2) switch + restart,
		then (3) once the knockout is confirmed live, push them straight onto the running
		script. The mode reads the warm-up count only after a short "New match" settle at
		map start, so this second push lands in time. See Knockout.Script.txt."""
		if settings:
			await self._apply_mode_settings(settings, stage=True)
		await self._load_script(KNOCKOUT_SCRIPT)
		if settings and await self._await_script(KNOCKOUT_SCRIPT):
			await self._apply_mode_settings(settings, stage=False)

	async def _await_script(self, script, timeout=8.0, interval=0.25):
		"""Poll (bounded) until ``script`` is the running mode script. Returns True once it
		matches, False on timeout -- so a stuck switch degrades to 'no re-apply' rather
		than hanging the handoff."""
		name = script.lower().rsplit('/', 1)[-1].split('.')[0]   # e.g. 'knockout'
		deadline = time.time() + timeout
		while time.time() < deadline:
			if name in (await self._current_script()).lower():
				return True
			await asyncio.sleep(interval)
		logger.warning(
			'Knockout: BOTN %s did not load within %ss; warm-up settings may not apply',
			script, timeout)
		return False

	async def _current_script(self, refresh=True):
		"""Current mode script name (live query when supported), or '' on error."""
		mm = self.instance.mode_manager
		try:
			return (await mm.get_current_script(refresh=refresh)) or ''
		except TypeError:
			try:
				return (await mm.get_current_script()) or ''
			except Exception:
				return ''
		except Exception:
			return ''

	async def _apply_mode_settings(self, settings, stage=True):
		"""Push mode-script settings (knockout warm-up, TimeAttack time limit) either staged
		for the next script load (``stage=True``, via ``update_next_settings``) or straight
		onto the running script (``stage=False``, via ``update_settings``). Staging falls back
		to a direct update when the host lacks ``update_next_settings``."""
		mm = self.instance.mode_manager
		try:
			if stage:
				fn = getattr(mm, 'update_next_settings', None)
				if fn is not None:
					await fn(settings)
					return
			await mm.update_settings(settings)
		except Exception:
			logger.exception('Knockout: BOTN failed to apply knockout settings (stage=%s)', stage)

	async def _name(self, login):
		try:
			player = await self.instance.player_manager.get_player(login=login)
			return player.nickname
		except Exception:
			return login or '—'

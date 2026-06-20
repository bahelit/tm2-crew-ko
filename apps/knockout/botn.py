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
during practice, then "KNOCKOUT IN" through the short handoff window before the
knockout loads.

The knockout warm-up length (``S_WarmUpNb``) and the fastest practice time's one-time
shield (``S_PreShieldLogins``) are staged into the knockout settings at the cutoff;
see ``Knockout.Script.txt``.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

KNOCKOUT_SCRIPT = 'Modes/TrackMania/Knockout.Script.txt'
TIMEATTACK_SCRIPT = 'TimeAttack.Script.txt'


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
		# Countdown-overlay state, so a player who connects mid-countdown can be sent
		# the overlay with their correct remaining time (the BOTN auto-starts at boot
		# with nobody connected, so the initial display() reaches no one).
		self._overlay_active = False
		self._overlay_ends = None  # epoch seconds the current countdown ends at
		self._overlay_header = 'KNOCKOUT IN'

	async def on_start(self):
		# Always listen for finishes; the handler ignores them unless we are in the
		# practice phase, so this is cheap when no BOTN is running.
		from pyplanet.apps.core.trackmania import callbacks as tm_signals
		from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
		self.app.context.signals.listen(tm_signals.finish, self.on_practice_finish)
		# Catch players who connect while a countdown is on screen (notably the BOTN
		# auto-started at boot, where the first display() reaches nobody).
		self.app.context.signals.listen(mp_signals.player.player_connect, self.on_player_connect)
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
		# Still in practice (TimeAttack loaded): recompute today's cutoff and re-arm.
		self.active, self.phase = True, 'practice'
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
		await self._load_script(TIMEATTACK_SCRIPT)
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
		await self.start()

	async def stop(self, player=None):
		if not self.active:
			await self.instance.chat('$f00>>> No Bowl of the Night is running.', player)
			return
		self._cancel_task()
		await self._hide_countdown_overlay()
		self.active, self.phase = False, 'idle'
		self.best = {}
		await self.app.cup.stop_cup()
		# Drop the server back to its TimeAttack resting state.
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
		# Queue TimeAttack for the next map WITHOUT a RestartMap: the knockout's map-end
		# advances the server to the next playlist map on its own, and our queued script
		# loads with it.
		await self.app.queue_timeattack()
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
		# Practice (and so the fastest-lap shield race) is locked in at the cutoff; the
		# countdown is just a heads-up before the knockout loads.
		self.phase = 'countdown'
		fastest = pick_fastest(self.best)

		# Stage the knockout settings (warm-up laps + fastest-practice shield) so they
		# are present when the mode's warm-up / StartKnockout runs after the script switch.
		settings = {}
		try:
			warmup = max(0, int(await self.app.setting_botn_warmup_laps.get_value() or 0))
		except (TypeError, ValueError):
			warmup = 3
		settings['S_WarmUpNb'] = warmup
		if fastest and await self.app.setting_botn_fastest_shield.get_value():
			settings['S_EnableShields'] = True
			settings['S_PreShieldLogins'] = fastest

		fastest_txt = await self._name(fastest) if fastest else 'nobody'
		try:
			total = max(0, int(await self.app.setting_botn_countdown_seconds.get_value() or 0))
		except (TypeError, ValueError):
			total = 900
		await self._run_countdown(total, fastest_txt)

		if settings:
			await self._apply_knockout_settings(settings)
		await self._load_script(KNOCKOUT_SCRIPT)
		self.phase = 'knockout'
		await self.instance.chat('$09f>>> $fffBowl of the Night$09f knockout is GO!')

	async def _run_countdown(self, total, fastest_txt):
		"""Announce the knockout start, then re-announce at each COUNTDOWN_MARK below
		the total, sleeping the remainder before the handoff. The right-side overlay
		switches to "KNOCKOUT IN" and ticks the same countdown client-side."""
		await self.instance.chat(
			'$09f>>> Practice closed — fastest: $fff{}$09f. Knockout in $fff{}$09f!'.format(
				fastest_txt, human_duration(total)))
		await self._show_countdown_overlay(total, 'KNOCKOUT IN')
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

	async def _apply_knockout_settings(self, settings):
		mm = self.instance.mode_manager
		# Prefer staging for the next script load; fall back to a direct update.
		fn = getattr(mm, 'update_next_settings', None)
		try:
			if fn is not None:
				await fn(settings)
			else:
				await mm.update_settings(settings)
		except Exception:
			logger.exception('Knockout: BOTN failed to apply knockout settings')

	async def _name(self, login):
		try:
			player = await self.instance.player_manager.get_player(login=login)
			return player.nickname
		except Exception:
			return login or '—'

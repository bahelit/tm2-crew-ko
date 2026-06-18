"""
Bowl of the Evening (BOTD) orchestration.

A daily one-map event: the server runs the day's map as open **TimeAttack**
practice until a configured local time (default 17:00), then the app switches the
*same map* into Knockout and runs it to a single winner. Because ManiaScript has no
wall-clock access, all timing lives here in Python.

The fastest practice time can be granted a one-time shield in the knockout (the mode
reads ``S_PreShieldLogins`` at match start; see ``Knockout.Script.txt``).
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

class BotdController:
	"""Owns the BOTD lifecycle: start practice, schedule the cutoff, and hand off to
	the knockout. One BOTD at a time, mirroring the single active cup."""

	def __init__(self, app):
		self.app = app
		self.instance = app.instance
		self.active = False
		self.phase = 'idle'        # 'idle' | 'practice' | 'knockout'
		self.best = {}             # login -> best practice time (ms)
		self.cutoff_ts = None      # epoch seconds of the cutoff
		self._task = None          # asyncio waiter for the cutoff

	async def on_start(self):
		# Always listen for finishes; the handler ignores them unless we are in the
		# practice phase, so this is cheap when no BOTD is running.
		from pyplanet.apps.core.trackmania import callbacks as tm_signals
		self.app.context.signals.listen(tm_signals.finish, self.on_practice_finish)
		# Re-arm after a PyPlanet restart if a BOTD cup is still active and we are
		# back in (or never left) the TimeAttack practice phase.
		await self._maybe_resume()

	async def _maybe_resume(self):
		cup = getattr(self.app.cup, 'active_cup', None)
		if not cup or cup.cup_key != 'botd':
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
		logger.info('Knockout: resumed BOTD practice, cutoff re-armed')

	# ------------------------------------------------------------------ lifecycle

	async def start(self, player, time_override=None):
		if self.active:
			await self.instance.chat('$f00>>> A Bowl of the Evening is already running. //botd off first.', player)
			return

		hour, minute = parse_hhmm(
			time_override or await self.app.setting_botd_cutoff_time.get_value())
		self.cutoff_ts = next_occurrence(datetime.now(), hour, minute).timestamp()

		# One-map cup so the knockout result auto-completes the BOTD.
		score_mode = await self.app.setting_default_score_mode.get_value()
		await self.app.cup.start_cup(
			cup_key='botd', name='BOTD {}'.format(datetime.now().strftime('%Y-%m-%d')),
			map_count=1, score_mode=score_mode,
		)

		self.best = {}
		self.active, self.phase = True, 'practice'
		await self._load_script(TIMEATTACK_SCRIPT)
		self._arm_cutoff()
		await self.app.commands._refresh_hud_season()

		await self.instance.chat(
			'$09f>>> $fffBowl of the Evening$09f started — practice until $fff{:02d}:{:02d}$09f, '
			'then the knockout begins.'.format(hour, minute))

	async def stop(self, player):
		if not self.active:
			await self.instance.chat('$f00>>> No Bowl of the Evening is running.', player)
			return
		self._cancel_task()
		self.active, self.phase = False, 'idle'
		self.best = {}
		await self.app.cup.stop_cup()
		await self.app.commands._refresh_hud_season()
		await self.instance.chat('$09f>>> Bowl of the Evening stopped.')

	async def force_start(self, player):
		"""Admin override: end practice and start the knockout immediately."""
		if not self.active or self.phase != 'practice':
			await self.instance.chat('$f00>>> No BOTD practice phase to start the knockout from.', player)
			return
		self._cancel_task()
		await self._on_cutoff()

	async def status(self, player):
		if not self.active:
			await self.instance.chat('$bbb>>> No Bowl of the Evening is running.', player)
			return
		when = datetime.fromtimestamp(self.cutoff_ts).strftime('%H:%M') if self.cutoff_ts else '—'
		fastest = pick_fastest(self.best)
		fastest_txt = await self._name(fastest) if fastest else 'nobody yet'
		await self.instance.chat(
			'$bbb>>> BOTD phase: $fff{}$bbb, knockout at $fff{}$bbb, fastest practice: $fff{}$bbb.'.format(
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
		hour, minute = parse_hhmm(await self.app.setting_botd_cutoff_time.get_value())
		self.cutoff_ts = next_occurrence(datetime.now(), hour, minute).timestamp()
		self._arm_cutoff()

	async def _cutoff_waiter(self, delay):
		try:
			await asyncio.sleep(delay)
			await self._on_cutoff()
		except asyncio.CancelledError:
			pass
		except Exception:
			logger.exception('Knockout: BOTD cutoff waiter failed')

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

		# Stage the knockout settings (fastest-practice shield) so they are present
		# when the mode's StartKnockout runs after the script switch.
		settings = {}
		if fastest and await self.app.setting_botd_fastest_shield.get_value():
			settings = {'S_EnableShields': True, 'S_PreShieldLogins': fastest}

		fastest_txt = await self._name(fastest) if fastest else 'nobody'
		try:
			total = max(0, int(await self.app.setting_botd_countdown_seconds.get_value() or 0))
		except (TypeError, ValueError):
			total = 900
		await self._run_countdown(total, fastest_txt)

		if settings:
			await self._apply_knockout_settings(settings)
		await self._load_script(KNOCKOUT_SCRIPT)
		self.phase = 'knockout'
		await self.instance.chat('$09f>>> $fffBowl of the Evening$09f knockout is GO!')

	async def _run_countdown(self, total, fastest_txt):
		"""Announce the knockout start, then re-announce at each COUNTDOWN_MARK below
		the total, sleeping the remainder before the handoff. A right-side overlay
		ticks the same countdown client-side for everyone watching."""
		await self.instance.chat(
			'$09f>>> Practice closed — fastest: $fff{}$09f. Knockout in $fff{}$09f!'.format(
				fastest_txt, human_duration(total)))
		await self._show_countdown_overlay(total)
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
			# Always clear the overlay -- including when the BOTD is stopped mid
			# countdown (which cancels the waiter task and unwinds through here).
			await self._hide_countdown_overlay()

	async def _show_countdown_overlay(self, total):
		cd = getattr(self.app, 'botd_countdown', None)
		if cd is None or total <= 0:
			return
		try:
			await cd.start(total)
		except Exception:
			logger.exception('Knockout: BOTD countdown overlay failed to show')

	async def _hide_countdown_overlay(self):
		cd = getattr(self.app, 'botd_countdown', None)
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
		await self.app.setting_botd_countdown_seconds.set_value(seconds)
		await self.instance.chat(
			'$09f>>> BOTD countdown set to $fff{}$09f.'.format(human_duration(seconds)), player)

	# --------------------------------------------------------------------- helpers

	async def _load_script(self, script):
		"""Switch the mode script and restart the current map so it loads (keeping the
		same daily map for both practice and the knockout)."""
		try:
			await self.instance.mode_manager.set_next_script(script)
			await self.instance.gbx('RestartMap')
		except Exception:
			logger.exception('Knockout: BOTD failed to load script %s', script)

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
			logger.exception('Knockout: BOTD failed to apply knockout settings')

	async def _name(self, login):
		try:
			player = await self.instance.player_manager.get_player(login=login)
			return player.nickname
		except Exception:
			return login or '—'

import logging

from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from pyplanet.apps.core.trackmania import callbacks as tm_signals

from ..models import MatchInfo
from ..callbacks import parse_round_order, parse_round_start, first_login, register
from ..hud_format import format_race_time, format_gap, split_cp_label

logger = logging.getLogger(__name__)

# Most recent checkpoint crossings kept in the bottom splits feed (newest first).
CP_FEED_MAX = 6


class LiveController:
	"""
	Tracks the state of the Knockout match that is being played right now, so the
	broadcast overlays can react in real time. The mode only persists final map
	standings (see capture.py); this controller layers on the live picture:

	* ``racing`` - logins still in the match.
	* ``count``  - how many are still racing.
	* ``danger`` - the player(s) currently on the elimination bubble (from the
	  KORoundOrder callback added to the mode).
	* ``phase``  - 'idle' | 'racing' | 'showdown' (final two) | 'ended'.

	Player added/removed/winner events are routed in from the app's existing
	notification handler so we do not register those signals twice; KORoundOrder
	and the shield callbacks are owned here.
	"""

	# Number of trailing players treated as "in danger" when double-knockout is
	# not active. Re-derived from S_DoubleKnockUntil at map start.
	def __init__(self, app):
		self.app = app
		self.instance = app.instance
		self.racing = []
		self.order = []
		self.phase = 'idle'
		self.round = 0
		self.total_rounds = 0
		# 1-based number of the match being played, shown as the HUD title. Filled
		# from the database at each map_start (count of recorded matches + 1).
		self.match_number = 0
		# Best lap time (ms) seen per login on the current map, from the finish
		# callback. Populated during warm-up too, so the HUD can show times before
		# any KO round data arrives. Reset each map.
		self.best_times = {}
		# Checkpoint splits feed: cp_best maps a checkpoint ordinal -> the best race
		# time (ms) seen at it this round; cp_feed is the newest-first list of recent
		# crossings (ready-to-render row dicts). Both reset each round and map.
		self.cp_best = {}
		self.cp_feed = []
		# Running cup total (login -> points so far in the active cup), shown as the
		# HUD's points column. Cached because compute_standings sums every counted map
		# and the HUD refreshes on every live event; only refreshed on the infrequent
		# paths (map start, match recorded, cup start/stop). ``cup_active`` lets the HUD
		# show the column (with zeros) from the first map, before any map is recorded.
		self.season_points = {}
		self.cup_active = False
		# Seconds the mode gives stragglers to finish after the first finisher
		# (S_FinishCountdown), read at map start. The finish-countdown overlay is
		# armed once per round on the first finish; this flag prevents re-arming.
		self._finish_seconds = 0
		self._countdown_armed = False
		# Whether the current mode script is a Knockout mode. The HUD is always-on
		# during Knockout but should not appear in other modes; default True so it
		# shows until the first map_start tells us otherwise.
		self.is_knockout = True
		self._double_until = 0
		self._order_signal = None
		self._round_signal = None
		# Diagnostics surfaced by //ko hud: how many of each mode callback we have
		# received, and the last HUD refresh error (if any).
		self.callbacks_seen = {
			'KOPlayerAdded': 0, 'KOPlayerRemoved': 0, 'KOSendWinner': 0,
			'KORoundOrder': 0, 'KORoundStart': 0,
		}
		# Last exception raised by the real HUD refresh path, surfaced by //ko hud.
		# The test render (show_test) reports its own errors to chat, but the real
		# refresh is fire-and-forget from callbacks, so we stash it here instead.
		self.last_hud_error = None

	@property
	def count(self):
		return len(self.racing)

	async def on_start(self):
		# KORoundOrder: live ordering of the racing players (added in the mode).
		self._order_signal = register(
			self.app, 'KORoundOrder', self.on_round_order, target=parse_round_order)

		# KORoundStart: the round number at the start of each round (added in the
		# mode), so the HUD can show "ROUND x / y".
		self._round_signal = register(
			self.app, 'KORoundStart', self.on_round_start, target=parse_round_start)

		# Shield earned / spent (added in the mode); simple single-login payloads.
		register(self.app, 'KOShieldAwarded', self.on_shield_awarded)
		register(self.app, 'KOShieldUsed', self.on_shield_used)

		# Best-lap tracking for the HUD's times column. The finish callback fires
		# during warm-up as well as scored rounds, so the HUD has times to show
		# before the KO round callbacks start arriving.
		self.app.context.signals.listen(tm_signals.finish, self.on_finish)

		# Checkpoint crossings drive the bottom splits feed during live rounds.
		self.app.context.signals.listen(tm_signals.waypoint, self.on_waypoint)

		# Keep the warm-up roster current as players come and go.
		self.app.context.signals.listen(mp_signals.player.player_connect, self.on_roster_change)
		self.app.context.signals.listen(mp_signals.player.player_disconnect, self.on_roster_change)

		# Reset the live picture whenever a new map (and so a new match) starts.
		self.app.context.signals.listen(mp_signals.map.map_start, self.on_map_start)

		# Paint the HUD once now, so it appears immediately on startup/reload for
		# whoever is already connected -- without waiting for the next map_start,
		# finish, or connect. Otherwise the always-on HUD only shows after one of
		# those fires (or after //ko hud force-renders it). Seed the per-map state
		# the same way on_map_start does so the first paint has the right context.
		self.is_knockout = await self._read_is_knockout()
		self.match_number = await self._read_match_number()
		self._double_until = await self._read_double_until()
		await self._refresh_season_points()
		await self._refresh_overlays()

	# ----------------------------------------------------------------- lifecycle

	async def on_map_start(self, *args, **kwargs):
		self.racing = []
		self.order = []
		self.phase = 'idle'
		self.round = 0
		self.total_rounds = 0
		self.best_times = {}
		self.cp_best = {}
		self.cp_feed = []
		# Only show the HUD while a Knockout mode is loaded.
		self.is_knockout = await self._read_is_knockout()
		# Number this match for the HUD title ("MATCH n").
		self.match_number = await self._read_match_number()
		# Cache the double-knockout threshold so danger highlighting matches how
		# many players the mode will actually knock out this round.
		self._double_until = await self._read_double_until()
		# New map: drop any leftover finish countdown and re-read its length.
		self._finish_seconds = await self._read_finish_countdown()
		self._countdown_armed = False
		await self._hide_countdown()
		await self._refresh_season_points()
		markers = getattr(self.app, 'markers', None)
		if markers is not None:
			try:
				current = self.instance.map_manager.current_map
				await markers.log('map_start', current.name if current else '')
			except Exception:
				logger.exception('Knockout: failed to log map_start marker')
		await self._refresh_overlays()

	async def _refresh_season_points(self):
		"""Recompute the cached running cup total (placement points so far this cup) for
		the HUD's points column. ``cup_active`` is set so the HUD shows the column --
		with zeros -- from the first map, before any map has been recorded. No cup ->
		empty + inactive. Called only on infrequent paths (map start, match recorded,
		cup start/stop), never per-render, since compute_standings sums every map."""
		cup = getattr(self.app.cup, 'active_cup', None) if getattr(self.app, 'cup', None) else None
		if not cup:
			self.season_points = {}
			self.cup_active = False
			return
		self.cup_active = True
		try:
			standings = await self.app.results.compute_standings(cup)
			self.season_points = {row['login']: row['cup_points'] for row in standings}
		except Exception:
			logger.exception('Knockout: failed to refresh cup points')
			self.season_points = {}

	async def _read_double_until(self):
		try:
			settings = await self.instance.mode_manager.get_settings()
		except Exception:
			return 0
		try:
			return int(settings.get('S_DoubleKnockUntil', 0) or 0)
		except (TypeError, ValueError):
			return 0

	async def _read_finish_countdown(self):
		"""Seconds the mode DNF-times stragglers after the first finisher
		(S_FinishCountdown). Defaults to 30 when it can't be read."""
		try:
			settings = await self.instance.mode_manager.get_settings()
		except Exception:
			return 30
		try:
			return int(settings.get('S_FinishCountdown', 30) or 30)
		except (TypeError, ValueError):
			return 30

	async def _read_is_knockout(self):
		try:
			script = await self.instance.mode_manager.get_current_script()
		except Exception:
			return True  # can't tell -> leave the HUD enabled
		return 'knockout' in (script or '').lower()

	async def _read_match_number(self):
		"""The 1-based number of the match about to be played: the count of matches
		already recorded plus one. DB-backed so it survives a plugin reload mid-cup.
		Returns 0 (HUD shows "KNOCKOUT") if the count can't be read."""
		try:
			rows = list(await MatchInfo.execute(MatchInfo.select()))
		except Exception:
			return 0
		return len(rows) + 1

	# --------------------------------------------------- best-lap / roster

	async def on_finish(self, player=None, race_time=None, **kwargs):
		"""Track each player's best lap this map so the HUD can show times during
		warm-up (and as a fallback before KORoundOrder carries them)."""
		login = getattr(player, 'login', None) or (str(player) if player else '')
		if not login:
			return
		try:
			ms = int(race_time)
		except (TypeError, ValueError):
			return
		if ms <= 0:
			return
		best = self.best_times.get(login)
		if best is None or ms < best:
			self.best_times[login] = ms
			await self._refresh_overlays()

		# First finisher of a live round arms the lower-right DNF countdown (the
		# mode arms the same cut-off server-side). Gated to scored rounds so warm-up
		# finishes don't trigger it; armed once per round (reset at round start).
		if (not self._countdown_armed and self._finish_seconds > 0
				and self.round > 0 and self.phase in ('racing', 'showdown')):
			self._countdown_armed = True
			await self._show_countdown()

	async def on_waypoint(self, player=None, race_time=None, race_cps=None, is_end_race=False, **kwargs):
		"""Feed the bottom splits panel. On each checkpoint crossing during a live
		scored round, record the player's split versus the best time seen at that
		checkpoint so far: the leading split shows as an absolute time, the rest as a
		``+gap``. Only live rounds count, so warm-up driving never clutters the feed."""
		if not (self.round > 0 and self.phase in ('racing', 'showdown')):
			return
		login = getattr(player, 'login', None) or (str(player) if player else '')
		if not login:
			return
		try:
			ms = int(race_time)
		except (TypeError, ValueError):
			return
		if ms < 0:
			return
		# Checkpoint ordinal: how many checkpoints have been crossed this lap so far.
		try:
			count = len(race_cps) if race_cps else 0
		except TypeError:
			count = 0
		if count <= 0:
			return
		prev_best = self.cp_best.get(count)
		if prev_best is None or ms <= prev_best:
			self.cp_best[count] = ms
			split_text = format_race_time(ms)
		else:
			split_text = format_gap(ms - prev_best)
		name = await self._player_name(login)
		self.cp_feed.insert(0, dict(
			name=name,
			cp=split_cp_label(count, is_end_race),
			split=split_text,
			color='66FF66',
		))
		del self.cp_feed[CP_FEED_MAX:]
		await self._refresh_splits()

	async def on_roster_change(self, *args, **kwargs):
		"""A player connected/disconnected; repaint the warm-up roster."""
		await self._refresh_overlays()

	def best_time(self, login):
		"""Best lap (ms) recorded for ``login`` this map, or -1 if none yet."""
		return self.best_times.get(login, -1)

	async def roster_logins(self):
		"""Logins to list on the HUD. During a live round this is the racing set;
		before that (warm-up) it is the players currently on the server, so the HUD
		is populated even with no round data yet. Pure spectators are excluded."""
		if self.racing:
			return list(self.racing)
		try:
			online = self.instance.player_manager.online
		except Exception:
			return []
		logins = []
		for entry in online:
			login = getattr(entry, 'login', None)
			if not login:
				continue
			flow = getattr(entry, 'flow', None)
			if flow is not None and getattr(flow, 'is_spectator', False):
				continue
			logins.append(login)
		return logins

	# ------------------------------------------------- routed from app handlers

	async def on_player_added(self, login):
		self.callbacks_seen['KOPlayerAdded'] += 1
		if login and login not in self.racing:
			self.racing.append(login)
		self.phase = 'showdown' if self.count == 2 else 'racing'
		await self._refresh_overlays()

	async def on_player_removed(self, login):
		self.callbacks_seen['KOPlayerRemoved'] += 1
		if login in self.racing:
			self.racing.remove(login)
		self.order = [e for e in self.order if e['login'] != login]
		# Eliminations happen as the round resolves -> the countdown is done.
		await self._hide_countdown()
		await self._flash_elimination(login)
		await self._mark('eliminated', login)
		if self.count == 2 and self.phase != 'showdown':
			self.phase = 'showdown'
			await self._mark('showdown', '')
		elif self.count <= 1:
			self.phase = 'ended'
		await self._refresh_overlays()

	async def on_winner(self, login):
		self.callbacks_seen['KOSendWinner'] += 1
		self.phase = 'ended'
		await self._hide_countdown()
		await self._flash_winner(login)
		await self._mark('winner', login)
		await self._refresh_overlays()

	# ------------------------------------------------------- owned callbacks

	async def on_round_order(self, order=None, **kwargs):
		self.callbacks_seen['KORoundOrder'] += 1
		self.order = order or []
		# The mode only emits KOPlayerAdded at the start of a fresh match, so if
		# the plugin started/reloaded mid-match we never learned who is racing and
		# the phase is stuck at 'idle' (HUD/overlays hidden). KORoundOrder carries
		# the currently-racing logins every round, so seed the racing set from it
		# when we have none -- this lets the HUD self-heal a round or so in.
		if self.order and not self.racing and self.phase in ('idle', 'ended'):
			self.racing = [entry['login'] for entry in self.order]
			self.phase = 'showdown' if self.count == 2 else 'racing'
		await self._refresh_overlays()

	async def on_round_start(self, round=0, total=0, **kwargs):
		self.callbacks_seen['KORoundStart'] += 1
		self.round = round
		self.total_rounds = total
		# New round: clear last round's finish countdown so the next first-finisher
		# re-arms it, and reset the per-round checkpoint splits.
		self._countdown_armed = False
		self.cp_best = {}
		self.cp_feed = []
		await self._hide_countdown()
		await self._refresh_overlays()

	async def on_shield_awarded(self, signal=None, **kwargs):
		login = first_login(kwargs.get('player_login') or kwargs.get('login'))
		await self._flash_shield(login, awarded=True)
		await self._mark('shield_awarded', login)

	async def on_shield_used(self, signal=None, **kwargs):
		login = first_login(kwargs.get('player_login') or kwargs.get('login'))
		await self._flash_shield(login, awarded=False)
		await self._mark('shield_used', login)

	# --------------------------------------------------------------- derived

	@property
	def danger_count(self):
		"""How many trailing players the mode will knock out this round."""
		if self._double_until and self.count > self._double_until:
			return 2
		return 1

	def danger_logins(self):
		"""
		Logins currently on the elimination bubble: the worst-ranked racing
		players who have not yet safely finished. Empty until KORoundOrder data
		arrives, or once the match has ended.
		"""
		if self.phase == 'ended' or not self.order:
			return []
		live = [e for e in self.order if e['login'] in self.racing and not e['finished']]
		if not live:
			return []
		live.sort(key=lambda e: e['rank'])
		return [e['login'] for e in live[-self.danger_count:]]

	# --------------------------------------------------------------- helpers

	async def _refresh_overlays(self):
		# Broadcast ticker (stream overlays, opt-in) and the always-on match HUD
		# are gated independently; refresh whichever is enabled.
		ticker = getattr(self.app, 'ticker', None)
		if getattr(self.app, '_overlays_enabled', False) and ticker is not None:
			try:
				await ticker.refresh(self)
			except Exception:
				logger.exception('Knockout: failed to refresh live ticker')

		# The match HUD is on by default. Gate it on the LIVE setting value rather
		# than a cached flag, so setting show_match_hud (or starting up with it on)
		# always takes effect immediately -- no app reload, no stale-cache footgun.
		# A failed read defaults to on so a transient error never hides the HUD.
		hud = getattr(self.app, 'hud', None)
		if hud is not None:
			try:
				hud_enabled = await self.app.setting_show_match_hud.get_value()
			except Exception:
				hud_enabled = True
			# Keep the cached flag in sync purely for the //ko hud diagnostic.
			self.app._match_hud_enabled = hud_enabled
			if hud_enabled:
				try:
					await hud.refresh(self)
					self.last_hud_error = None
				except Exception as exc:
					self.last_hud_error = repr(exc)
					logger.exception('Knockout: failed to refresh match HUD')
			else:
				try:
					await hud.hide()
				except Exception:
					logger.exception('Knockout: failed to hide match HUD')

		await self._refresh_splits()

	async def _refresh_splits(self):
		"""Show the bottom splits feed during a live round (gated on the match-HUD
		toggle), and hide it the moment the round ends, warm-up returns, or the feed
		is empty -- so it never lingers between rounds."""
		view = getattr(self.app, 'splits', None)
		if view is None:
			return
		live_round = self.round > 0 and self.phase in ('racing', 'showdown')
		try:
			enabled = await self.app.setting_show_match_hud.get_value()
		except Exception:
			enabled = True
		try:
			if enabled and live_round and self.cp_feed:
				await view.refresh(self.cp_feed)
			else:
				await view.hide()
		except Exception:
			logger.exception('Knockout: failed to refresh splits HUD')

	async def _show_countdown(self):
		"""Show the lower-right DNF countdown (respects the match-HUD toggle)."""
		view = getattr(self.app, 'finish_countdown', None)
		if view is None:
			return
		try:
			if await self.app.setting_show_match_hud.get_value():
				await view.start(self._finish_seconds)
		except Exception:
			logger.exception('Knockout: failed to show finish countdown')

	async def _hide_countdown(self):
		view = getattr(self.app, 'finish_countdown', None)
		if view is None:
			return
		try:
			await view.hide()
		except Exception:
			logger.exception('Knockout: failed to hide finish countdown')

	async def _player_name(self, login):
		try:
			player = await self.instance.player_manager.get_player(login=login)
			return player.nickname
		except Exception:
			return login

	async def _flash_elimination(self, login):
		lower = self._lower_third()
		if lower is None:
			return
		name = await self._player_name(login)
		left = self.count
		await lower.flash('$f00❌ $fff{}$f00 knocked out — $fff{}$f00 left'.format(name, left))

	async def _flash_winner(self, login):
		lower = self._lower_third()
		if lower is None:
			return
		name = await self._player_name(login)
		await lower.flash('$0f0★ $fff{}$0f0 wins the round!'.format(name))

	async def _flash_shield(self, login, awarded):
		lower = self._lower_third()
		if lower is None or not login:
			return
		name = await self._player_name(login)
		# U+271A (✚, Dingbats block) renders in the ManiaPlanet font; the U+1F6E1
		# shield emoji is supplementary-plane and showed as an empty box. Matches the
		# ❌/★ glyphs used by the elimination/winner flashes above.
		if awarded:
			msg = '$09f✚ $fff{}$09f earned a shield!'.format(name)
		else:
			msg = '$09f✚ $fff{}$09f used a shield to survive!'.format(name)
		await lower.flash(msg)

	def _lower_third(self):
		if not getattr(self.app, '_overlays_enabled', False):
			return None
		return getattr(self.app, 'lower_third', None)

	async def _mark(self, event, login):
		markers = getattr(self.app, 'markers', None)
		if markers is None:
			return
		try:
			name = await self._player_name(login) if login else ''
			await markers.log(event, name or login)
		except Exception:
			logger.exception('Knockout: failed to log VOD marker')

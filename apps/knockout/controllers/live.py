import asyncio
import logging
import time

from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from pyplanet.apps.core.trackmania import callbacks as tm_signals

from ..models import MatchInfo
from ..callbacks import (
	parse_round_order, parse_round_start, parse_shield_state, callback_login, register)
from ..hud_format import (
	format_race_time, format_gap, split_cp_label, waypoint_cp_count, describe_payload,
	apply_shield_delta, order_split_rows, MAX_SHIELD_MARKS, SHIELD_MARK, SPLITS_ROWS)

logger = logging.getLogger(__name__)

# Minimum wall-clock gap between two splits repaints, in seconds.
#
# Checkpoint crossings arrive in bursts -- a 16-player pack hits the same checkpoint
# inside about two seconds -- and every one of them used to render the board and
# broadcast a full ManiaLink page to every client. On a 16-player round over a 4-CP
# map that is ~80 broadcasts from crossings alone, before the HUD and ticker repaints
# that ride along with them, all landing in the ~45 seconds when the server is
# busiest. Clients pay a layout hitch per page replacement, which is the stutter
# players report while the splits panel is filling up.
#
# Callbacks now only mark the board dirty (_queue_splits); one coalescing task does
# the painting, at most this often. The first crossing of a burst still paints
# immediately -- the delay only ever applies to a repaint that follows a recent one --
# so the board stays responsive while the burst behind it collapses into one send.
SPLITS_REFRESH_INTERVAL = 0.5


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
		# Logins knocked out this map, earliest first (from KOPlayerRemoved). Kept so
		# the //botn end / //cup end admin fallback can synthesise a full-field result
		# (survivors + everyone eliminated) if the mode ever fails to emit
		# KOMatchStandings; see synth_standings.
		self.eliminated = []
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
		# Checkpoint splits standings board (NOT a feed -- one row per player, so a name
		# only moves when its player is actually overtaken). cp_best maps a checkpoint
		# ordinal -> the best race time (ms) seen at it this round; cp_rows maps a login
		# to that player's latest crossing as a ready-to-render row dict; _cp_seq is a
		# monotonic crossing counter used as the ordering tie-break (see split_rank_key).
		# All reset each round and map.
		self.cp_best = {}
		self.cp_rows = {}
		self._cp_seq = 0
		# Splits repaint coalescing (see SPLITS_REFRESH_INTERVAL). _splits_dirty says a
		# repaint is owed; _splits_task is the coroutine that pays it. The task is
		# short-lived on purpose -- it exits as soon as it finds nothing owed -- so there
		# is no background loop to tear down when the app stops.
		self._splits_dirty = False
		self._splits_task = None
		# How many times a callback asked for a repaint. Reported by //ko splits next to
		# the view's own send count, so the coalescing can be checked on a live server.
		self.splits_requests = 0
		# Same idea for the match HUD, which _refresh_overlays repaints on every
		# KORoundOrder and every best-lap improvement. Reported by //ko hud.
		self.overlay_refreshes = 0
		# Fallback checkpoint counter, login -> [crossings so far, last race_time].
		# Used when the waypoint payload carries no usable ordinal (see _cp_ordinal).
		self.cp_counts = {}
		# Diagnostics for //ko splits: how many raw PyPlanet race signals arrived, a
		# one-line summary of the last waypoint payload, and the last splits render
		# error. The splits feed is fire-and-forget from callbacks, so without these
		# a silent failure anywhere along the chain looks identical from in-game.
		self.signals_seen = {'waypoint': 0, 'finish': 0}
		self.last_waypoint_note = ''
		self.last_splits_error = None
		# Running cup total (login -> points so far in the active cup), shown as the
		# HUD's points column. Cached because compute_standings sums every counted map
		# and the HUD refreshes on every live event; only refreshed on the infrequent
		# paths (map start, match recorded, cup start/stop). ``cup_active`` lets the HUD
		# show the column (with zeros) from the first map, before any map is recorded.
		self.season_points = {}
		self.cup_active = False
		self.cup_name = ''
		# Cup progress for the HUD's MAP line: maps already recorded, and the target
		# map count (0 = open-ended). Refreshed alongside season_points.
		self.cup_maps_played = 0
		self.cup_map_count = 0
		# True when the active cup is a Bowl of the Night, so the HUD can show the
		# "BOWL OF THE NIGHT" title instead of the generic "MATCH n".
		self.is_botn = False
		# Seconds the mode gives stragglers to finish after the first finisher
		# (S_FinishCountdown), read at map start. The finish-countdown overlay is
		# armed once per round on the first finish; this flag prevents re-arming.
		self._finish_seconds = 0
		self._countdown_armed = False
		# Monotonic deadline of the countdown currently on screen, so a client that
		# arrives mid-round can be handed the time that is actually left.
		self._countdown_ends_at = 0.0
		# Whether the current mode script is a Knockout mode. The HUD is always-on
		# during Knockout but should not appear in other modes; default True so it
		# shows until the first map_start tells us otherwise.
		self.is_knockout = True
		self._double_until = 0
		self._order_signal = None
		self._round_signal = None
		# Shields banked per login (login -> count >= 1). Authoritative from KOShieldState;
		# KOShieldAwarded / KOShieldUsed fold in an optimistic +-1 as they land. NOT cleared
		# per map -- stacks carry across every map of a cup, and are only reset by the mode
		# (new cup, or //ko shields reset), which force-sends KOShieldState.
		self.shield_counts = {}
		# Cap the mode is enforcing (S_MaxShields), re-read each map for the HUD/diagnostics.
		self.max_shields = MAX_SHIELD_MARKS
		# Diagnostics surfaced by //ko hud: how many of each mode callback we have
		# received, and the last HUD refresh error (if any).
		self.callbacks_seen = {
			'KOPlayerAdded': 0, 'KOPlayerRemoved': 0, 'KOSendWinner': 0,
			'KORoundOrder': 0, 'KORoundStart': 0, 'KOMatchStandings': 0,
			'KOShieldAwarded': 0, 'KOShieldUsed': 0, 'KOShieldState': 0,
		}
		# Maps that ended with an EMPTY KOMatchStandings payload, i.e. the mode
		# reported at map end but no knockout had been raced (it waits for
		# C_RequiredPlayersNb players before starting the round loop, so racing alone
		# rotates maps with nothing to score). Counted separately from the callback
		# total because "sent, but empty" and "never sent" need opposite fixes.
		self.empty_standings_seen = 0
		# Last exception raised while recording a finished map's scores (capture ->
		# database), surfaced by //ko hud. Set by CaptureController; kept here so the
		# one diagnostic command reports the whole scoring chain.
		self.last_capture_error = None
		# Last exception raised by the real HUD refresh path, surfaced by //ko hud.
		# The test render (show_test) reports its own errors to chat, but the real
		# refresh is fire-and-forget from callbacks, so we stash it here instead.
		self.last_hud_error = None

	@property
	def count(self):
		return len(self.racing)

	@property
	def shield_holders(self):
		"""Logins holding at least one shield. Kept because the match HUD and stream
		tooling asked for the old set before shields could stack."""
		return {login for login, count in self.shield_counts.items() if count > 0}

	async def on_start(self):
		# KORoundOrder: live ordering of the racing players (added in the mode).
		self._order_signal = register(
			self.app, 'KORoundOrder', self.on_round_order, target=parse_round_order)

		# KORoundStart: the round number at the start of each round (added in the
		# mode), so the HUD can show "ROUND x / y".
		self._round_signal = register(
			self.app, 'KORoundStart', self.on_round_start, target=parse_round_start)

		# Shield earned / spent (added in the mode); simple single-login payloads. They
		# drive the lower-third flash and the VOD markers, and fold an optimistic +-1 into
		# the bank -- KOShieldState right behind them carries the authoritative counts
		# (and is the only way we learn about a stack carried over from a previous map).
		register(self.app, 'KOShieldAwarded', self.on_shield_awarded)
		register(self.app, 'KOShieldUsed', self.on_shield_used)
		register(self.app, 'KOShieldState', self.on_shield_state, target=parse_shield_state)

		# Best-lap tracking for the HUD's times column. The finish callback fires
		# during warm-up as well as scored rounds, so the HUD has times to show
		# before the KO round callbacks start arriving.
		self.app.context.signals.listen(tm_signals.finish, self.on_finish)

		# Checkpoint crossings drive the bottom splits feed during live rounds.
		self.app.context.signals.listen(tm_signals.waypoint, self.on_waypoint)

		# Keep the warm-up roster current as players come and go. Also re-target
		# stream overlays when someone connects/disconnects or flips spectator.
		self.app.context.signals.listen(mp_signals.player.player_connect, self.on_roster_change)
		self.app.context.signals.listen(mp_signals.player.player_disconnect, self.on_roster_change)
		info_signal = getattr(mp_signals.player, 'player_info_changed', None) or getattr(
			mp_signals.player, 'player_info_change', None)
		if info_signal is not None:
			self.app.context.signals.listen(info_signal, self.on_roster_change)

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
		self.eliminated = []
		self.phase = 'idle'
		self.round = 0
		self.total_rounds = 0
		self.best_times = {}
		self.cp_best = {}
		self.cp_rows = {}
		self._cp_seq = 0
		self.cp_counts = {}
		# NOTE: shield_counts is deliberately NOT cleared here. Shields bank up to
		# S_MaxShields and carry across every map of a cup; the mode re-announces the
		# whole bank with KOShieldState once the new map's knockout is seeded.
		# Only show the HUD while a Knockout mode is loaded.
		self.is_knockout = await self._read_is_knockout()
		if not self.is_knockout:
			# Left Knockout (TimeAttack rotation, BOTN practice): no mode will ever send
			# a KOShieldState to clear these, and a stale marker on the practice roster
			# would claim a save that cannot be spent.
			self.shield_counts = {}
		self.max_shields = await self._read_max_shields()
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
		cup_ctrl = getattr(self.app, 'cup', None)
		cup = getattr(cup_ctrl, 'active_cup', None) if cup_ctrl else None
		if not cup:
			self.season_points = {}
			self.cup_active = False
			self.cup_name = ''
			self.cup_maps_played = 0
			self.cup_map_count = 0
			self.is_botn = False
			return
		self.cup_active = True
		self.cup_name = getattr(cup, 'name', '') or ''
		self.cup_maps_played = int(getattr(cup_ctrl, 'maps_played', 0) or 0)
		self.cup_map_count = int(getattr(cup, 'map_count', 0) or 0)
		self.is_botn = (getattr(cup, 'cup_key', None) == 'botn')
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

	async def _read_max_shields(self):
		"""How many shields the mode lets a player bank (S_MaxShields). Falls back to the
		HUD's own marker cap, which matches the mode's default."""
		try:
			settings = await self.instance.mode_manager.get_settings()
		except Exception:
			return MAX_SHIELD_MARKS
		try:
			return int(settings.get('S_MaxShields', MAX_SHIELD_MARKS) or 0)
		except (TypeError, ValueError):
			return MAX_SHIELD_MARKS

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

	async def on_finish(self, player=None, race_time=None, race_cps=None, is_end_race=False, **kwargs):
		"""Track each player's best lap this map so the HUD can show times during
		warm-up (and as a fallback before KORoundOrder carries them). Finish events
		also feed the splits panel (PyPlanet does not emit waypoint on the finish
		line — only the custom finish signal carries race_cps there)."""
		self.signals_seen['finish'] = self.signals_seen.get('finish', 0) + 1
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

		# Finish line split (waypoint is not fired on finish).
		if self.round > 0 and self.phase in ('racing', 'showdown'):
			count = waypoint_cp_count(race_cps=race_cps, **kwargs)
			if count <= 0:
				# Still show a FIN row even when the payload has no CP list: the
				# player's own crossing count gives the finish its ordinal (their
				# last checkpoint + 1), so finishers are compared against each other.
				count = self._cp_ordinal(login, ms)
			prev_best = self.cp_best.get(count)
			if prev_best is None or ms <= prev_best:
				self.cp_best[count] = ms
				split_text = format_race_time(ms)
			else:
				split_text = format_gap(ms - prev_best)
			await self._record_split(login, count, ms, split_text, True)

	async def on_waypoint(self, player=None, race_time=None, race_cps=None, is_end_race=False, raw=None, **kwargs):
		"""Feed the bottom splits panel. On each checkpoint crossing during a live
		scored round, record the player's split versus the best time seen at that
		checkpoint so far: the leading split shows as an absolute time, the rest as a
		``+gap``. Only live rounds count, so warm-up driving never clutters the feed.

		The checkpoint ordinal comes from the payload when it carries one, and from
		our own per-player counter when it does not (see ``_cp_ordinal``) -- payload
		shapes vary between PyPlanet versions and an unknown ordinal used to drop the
		crossing entirely, leaving the feed empty all round.
		"""
		self.signals_seen['waypoint'] = self.signals_seen.get('waypoint', 0) + 1
		live_round = self.round > 0 and self.phase in ('racing', 'showdown')
		login = getattr(player, 'login', None) or (str(player) if player else '')
		try:
			ms = int(race_time)
		except (TypeError, ValueError):
			ms = -1
		payload_count = waypoint_cp_count(race_cps=race_cps, raw=raw, **kwargs)
		# One-line record of what actually arrived, for //ko splits.
		self.last_waypoint_note = 'ms={} cp={} race_cps={} raw={} extra={} live={}'.format(
			ms, payload_count, describe_payload(race_cps), describe_payload(raw),
			','.join(sorted(k for k in kwargs if k != 'signal')) or '-', live_round)
		if not live_round or not login or ms < 0:
			return
		# The finish line belongs to on_finish (the finish signal is the one that
		# always carries the final race time). Skipping it here keeps exactly one FIN
		# row per lap even on setups where both signals fire for the last waypoint.
		if is_end_race:
			return
		count = payload_count if payload_count > 0 else self._cp_ordinal(login, ms)
		if count <= 0:
			return
		prev_best = self.cp_best.get(count)
		if prev_best is None or ms <= prev_best:
			self.cp_best[count] = ms
			split_text = format_race_time(ms)
		else:
			split_text = format_gap(ms - prev_best)
		await self._record_split(login, count, ms, split_text, is_end_race)

	async def _record_split(self, login, count, ms, split_text, is_end_race):
		"""Put this player's latest crossing on the splits standings board.

		One row per player: a new crossing REPLACES that player's row rather than being
		pushed onto a feed, which is what stops every name shuffling down a place each
		time somebody -- anybody -- hits a checkpoint. Ordering is applied at render time
		by order_split_rows, so a row only moves when it is genuinely overtaken.

		The latest crossing always wins, including one that goes backwards: a give-up and
		restart really has lost the progress (_cp_ordinal resets on a rewound race time
		for the same reason), and the board reports where a player is now.
		"""
		self._cp_seq += 1
		self.cp_rows[login] = dict(
			login=login,
			name=await self._player_name(login),
			cp=count,
			ms=ms,
			finished=bool(is_end_race),
			seq=self._cp_seq,
			cp_label=split_cp_label(count, is_end_race),
			split=split_text,
			color='66FF66',
		)
		self._queue_splits()

	def _cp_ordinal(self, login, ms):
		"""Checkpoint ordinal for a crossing whose payload carried none: how many
		checkpoints this player has crossed so far in the current round. A race time
		that did not advance means the player restarted, so the count starts over."""
		count, last_ms = self.cp_counts.get(login, (0, -1))
		if ms <= last_ms:
			count = 0
		count += 1
		self.cp_counts[login] = (count, ms)
		return count

	async def on_roster_change(self, *args, **kwargs):
		"""A player connected/disconnected or flipped spectator; repaint the warm-up
		roster, and catch that client up on the round already in progress.

		``_refresh_overlays`` re-pushes the match HUD, ticker and splits feed to
		everyone, so those self-heal. The finish countdown does not: it is armed
		once per round, so anyone arriving after the first finisher -- the stream
		box reconnecting, or a player just knocked into spectator -- would sit
		through the rest of the round with no card.

		The match HUD, the splits board and the stream ticker self-heal only because of
		the invalidate() calls below. All three now drop a repaint that would redraw
		what is already on screen, and "already on screen" is a statement about the
		clients that were connected last time -- not about the one that just joined
		holding no page at all. Miss one of these and a new arrival gets a permanently
		blank overlay.
		"""
		for name in ('hud', 'splits', 'ticker'):
			view = getattr(self.app, name, None)
			invalidate = getattr(view, 'invalidate', None)
			if invalidate is not None:
				invalidate()
		await self._refresh_overlays()
		player = kwargs.get('player') or (args[0] if args else None)
		await self._resend_countdown(getattr(player, 'login', None))

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
		if login and login not in self.eliminated:
			self.eliminated.append(login)
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
		self.cp_rows = {}
		self._cp_seq = 0
		self.cp_counts = {}
		# Self-heal when the plugin missed KOPlayerAdded (reload mid-map, callback
		# glitch, etc.): a real scored round means we are live. Without this, phase
		# stays 'idle', the stream ticker shows "N ON SERVER" practice chrome under
		# the Round banner, and the splits feed stays gated off.
		if self.round > 0 and self.phase in ('idle', 'ended'):
			if not self.racing:
				if self.order:
					self.racing = [entry['login'] for entry in self.order if entry.get('login')]
				else:
					self.racing = await self.roster_logins()
			self.phase = 'showdown' if self.count == 2 else 'racing'
		await self._hide_countdown()
		await self._refresh_overlays()

	async def on_shield_awarded(self, signal=None, **kwargs):
		self.callbacks_seen['KOShieldAwarded'] = self.callbacks_seen.get('KOShieldAwarded', 0) + 1
		login = callback_login(kwargs)
		if login:
			self.shield_counts = apply_shield_delta(
				self.shield_counts, login, 1, cap=self.max_shields)
		await self._flash_shield(login, awarded=True)
		await self._mark('shield_awarded', login)
		await self._refresh_overlays()

	async def on_shield_used(self, signal=None, **kwargs):
		self.callbacks_seen['KOShieldUsed'] = self.callbacks_seen.get('KOShieldUsed', 0) + 1
		login = callback_login(kwargs)
		if login:
			self.shield_counts = apply_shield_delta(
				self.shield_counts, login, -1, cap=self.max_shields)
		await self._flash_shield(login, awarded=False)
		await self._mark('shield_used', login)
		await self._refresh_overlays()

	async def on_shield_state(self, counts=None, **kwargs):
		"""The mode's authoritative shield bank. Replaces our copy wholesale, so a stack
		carried over from a previous map (or one earned while this controller was
		reloading) shows up even though we never saw the KOShieldAwarded that earned it."""
		self.callbacks_seen['KOShieldState'] = self.callbacks_seen.get('KOShieldState', 0) + 1
		self.shield_counts = dict(counts or {})
		await self._refresh_overlays()

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

	def synth_standings(self):
		"""Best-effort current knockout standings as ``[{login, points}]``, best first.

		Used only by the ``//botn end`` / ``//cup end`` admin fallback when the mode
		never emitted KOMatchStandings (a stuck knockout), so the map still records a
		sensible result. Survivors rank above eliminated players; among survivors the
		live KORoundOrder rank decides, and eliminated players rank by reverse
		elimination order (last knocked out = survived longest = better). The points are
		synthetic and only need to preserve this order -- ``compute_standings`` ranks by
		score per map, so descending integers reproduce the correct placement."""
		ranked = []
		# Survivors first, best-ranked first from the live order when we have it.
		for entry in sorted(self.order, key=lambda e: e['rank']):
			if entry['login'] in self.racing:
				ranked.append(entry['login'])
		for login in self.racing:
			if login not in ranked:
				ranked.append(login)
		# Then everyone eliminated, most-recently-eliminated first.
		ranked += list(reversed(self.eliminated))
		# Deduplicate while preserving order.
		ordered = []
		seen = set()
		for login in ranked:
			if login and login not in seen:
				seen.add(login)
				ordered.append(login)
		total = len(ordered)
		return [dict(login=login, points=total - index) for index, login in enumerate(ordered)]

	# --------------------------------------------------------------- helpers

	async def _match_hud_enabled(self):
		"""Whether the player-facing match HUD package should paint.

		Covers the left-side leaderboard, bottom splits feed, and finish countdown.
		On by default via ``show_match_hud``; always forced on during an active cup
		or BOTN so admins never need to flip settings for Friday cups / nightly BOTN.
		"""
		# Events always win: cup tracking (//cup on) or a live BOTN session.
		if self.cup_active:
			return True
		botn = getattr(self.app, 'botn', None)
		if botn and botn.active:
			return True
		try:
			return bool(await self.app.setting_show_match_hud.get_value())
		except Exception:
			# A failed read defaults to on so a transient error never hides the HUD.
			return True

	async def _refresh_overlays(self):
		# Stream ticker (spectators + /ko stream, or everyone if show_overlays) and
		# the always-on match HUD are gated independently. The HUD and splits views
		# both drop a repaint that would redraw what is already on screen, so calling
		# this often is cheap -- but see on_roster_change for what that costs.
		self.overlay_refreshes += 1
		ticker = getattr(self.app, 'ticker', None)
		if ticker is not None:
			try:
				await ticker.refresh(self)
			except Exception:
				logger.exception('Knockout: failed to refresh live ticker')

		hud = getattr(self.app, 'hud', None)
		if hud is not None:
			hud_enabled = await self._match_hud_enabled()
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

		self._queue_splits()

	def _queue_splits(self):
		"""Mark the splits board dirty and make sure a repaint is coming.

		Synchronous on purpose: this is called from race callbacks that fire once per
		checkpoint per player, and it must cost nothing but a flag. The render and the
		ManiaLink push happen in _splits_paint_loop, at most once per
		SPLITS_REFRESH_INTERVAL.
		"""
		self.splits_requests += 1
		self._splits_dirty = True
		if self._splits_task is None or self._splits_task.done():
			self._splits_task = asyncio.ensure_future(self._splits_paint_loop())

	async def _splits_paint_loop(self):
		"""Paint the splits board while repaints are owed, then exit.

		Paint-then-wait, not wait-then-paint: the first request after a quiet spell is
		served immediately, and only the requests that pile up behind it are collapsed.
		The task ends once an interval passes with nothing new, so the next burst is
		again painted on its first crossing.
		"""
		try:
			while self._splits_dirty:
				self._splits_dirty = False
				await self._refresh_splits()
				await asyncio.sleep(SPLITS_REFRESH_INTERVAL)
		except asyncio.CancelledError:
			raise
		except Exception:
			# _refresh_splits swallows its own render errors, so anything reaching here
			# is the coalescing itself failing. Log it: the next _queue_splits would
			# otherwise quietly start a fresh task over the same broken board.
			logger.exception('Knockout: splits repaint loop failed')

	async def _refresh_splits(self):
		"""Show the bottom splits standings during a live round (gated on the match-HUD
		toggle), and hide it when the round ends, warm-up returns, or nobody has crossed
		a checkpoint yet -- so it never lingers between rounds.

		Call _queue_splits() instead of this from anything a race callback can reach.
		This renders and pushes unconditionally; the queue is what keeps a burst of
		checkpoint crossings from doing so once per crossing.
		"""
		view = getattr(self.app, 'splits', None)
		if view is None:
			return
		live_round = self.round > 0 and self.phase in ('racing', 'showdown')
		enabled = await self._match_hud_enabled()
		rows = order_split_rows(self.cp_rows.values(), racing=self.racing, limit=SPLITS_ROWS)
		try:
			if enabled and live_round and rows:
				await view.refresh(rows)
			else:
				await view.hide()
			self.last_splits_error = None
		except Exception as exc:
			# Stashed for //ko splits: this path is fire-and-forget from race
			# callbacks, so a render failure is otherwise invisible in-game.
			self.last_splits_error = repr(exc)
			logger.exception('Knockout: failed to refresh splits HUD')

	async def _show_countdown(self):
		"""Show the lower-right DNF countdown (respects the match-HUD toggle)."""
		view = getattr(self.app, 'finish_countdown', None)
		if view is None:
			return
		try:
			if await self._match_hud_enabled():
				self._countdown_ends_at = time.monotonic() + self._finish_seconds
				await view.start(self._finish_seconds)
		except Exception:
			logger.exception('Knockout: failed to show finish countdown')

	async def _resend_countdown(self, login):
		"""Hand a client that just arrived (or just dropped into spectator) the
		countdown already running, with the seconds that are actually left.

		The card ticks client-side from the value it was rendered with, so a plain
		re-display would restart it at the full duration. It is only sent to that
		one login: a global re-display would visibly reset the card for everyone,
		and spectator flips fire on every elimination.
		"""
		view = getattr(self.app, 'finish_countdown', None)
		if view is None or not login or not self._countdown_armed:
			return
		remaining = self._countdown_ends_at - time.monotonic()
		if remaining < 1:
			return
		try:
			if await self._match_hud_enabled():
				await view.start(remaining, player_logins=[str(login)])
		except Exception:
			logger.exception('Knockout: failed to resend finish countdown')

	async def _hide_countdown(self):
		view = getattr(self.app, 'finish_countdown', None)
		if view is None:
			return
		self._countdown_ends_at = 0.0
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
		# ASCII marker, like SHIELD_MARK -- the game fonts have no Dingbats, so the U+274C
		# cross this used to draw came out as an empty box.
		await lower.flash('$f00X $fff{}$f00 knocked out — $fff{}$f00 left'.format(name, left))

	async def _flash_winner(self, login):
		lower = self._lower_third()
		if lower is None:
			return
		name = await self._player_name(login)
		# ASCII marker; U+2605 is outside the game fonts (see _flash_elimination).
		await lower.flash('$0f0* $fff{}$0f0 wins the round!'.format(name))

	async def _flash_shield(self, login, awarded):
		lower = self._lower_third()
		if lower is None or not login:
			return
		name = await self._player_name(login)
		count = self.shield_counts.get(login, 0)
		# Marker is SHIELD_MARK ('+') for the same reason the HUD uses it: neither the
		# U+1F6E1 shield emoji nor the U+271A cross exists in the ManiaPlanet game fonts,
		# so both drew as an empty box.
		if awarded:
			msg = '$09f{} $fff{}$09f earned a shield (2nd-to-last warm-up) — {} banked!'.format(
				SHIELD_MARK, name, count)
		else:
			msg = '$09f{} $fff{}$09f used a shield to survive — {} left!'.format(
				SHIELD_MARK, name, count)
		await lower.flash(msg)

	def _lower_third(self):
		# Audience is decided in push_stream_view (spectators / opt-in / everyone).
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

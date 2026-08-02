import asyncio
import logging
from collections import deque

from pyplanet.apps.core.maniaplanet import callbacks as mp_signals

from ..match_ids import allocate_match_start_time, dequeue_match_start_time
from ..models import MatchInfo, PlayerScore
from ..callbacks import parse_standings, register

logger = logging.getLogger(__name__)


def _player_country(player):
	"""Best-effort country/zone string for a player, or None."""
	flow = getattr(player, 'flow', None)
	if flow is None:
		return None
	return getattr(flow, 'zone', None) or getattr(flow, 'country', None)


def should_arm_cup_handoff(maps_played, map_count):
	"""True when the standings about to be recorded will finish a fixed-length cup.

	``maps_played`` is how many maps are already linked to the cup *before* this
	record; this standings event is the next one. Open-ended cups (map_count 0)
	never auto-arm TimeAttack.
	"""
	try:
		target = int(map_count or 0)
		played = int(maps_played or 0)
	except (TypeError, ValueError):
		return False
	if target <= 0:
		return False
	return played >= target - 1


def orphan_match_id(queue, last_match_id, captured):
	"""Return a match id that was allocated but never recorded, or None.

	Prefers the oldest queued id (FIFO standings), then the last allocated id.
	"""
	captured = set(captured or ())
	if queue:
		candidate = queue[0]
		if candidate not in captured:
			return candidate
		return None
	if last_match_id is not None and last_match_id not in captured:
		return last_match_id
	return None


class CaptureController:
	"""
	Records each finished Knockout map as a MatchInfo row plus one PlayerScore
	row per player. Driven by the mode's KOMatchStandings callback; map_start is
	used to allocate the match identifier.
	"""

	def __init__(self, app):
		self.app = app
		self.instance = app.instance
		self._match_start_time = None
		# One id per map_start, consumed FIFO by KOMatchStandings so a fast map
		# rotation cannot overwrite the id before the previous map is recorded.
		self._match_start_queue = deque()
		self._last_match_id = 0
		self._standings_signal = None
		self._captured = set()

	async def on_start(self):
		self._standings_signal = register(
			self.app, 'KOMatchStandings', self.on_standings, target=parse_standings)
		self.app.context.signals.listen(mp_signals.map.map_start, self.on_map_start)

	async def on_map_start(self, *args, **kwargs):
		# Capture registers map_start before LiveController, so live still holds the
		# previous map's racing/eliminated state here. Salvage first, then allocate.
		await self._salvage_unrecorded_match()

		# Allocate a stable identifier for the match that is about to be played.
		match_id = allocate_match_start_time(self._last_match_id)
		self._last_match_id = match_id
		self._match_start_time = match_id
		self._match_start_queue.append(match_id)

	async def on_standings(self, standings=None, **kwargs):
		# Count receipt BEFORE the empty check. An empty payload still means the mode
		# reported at map end; counting it afterwards left //ko hud showing
		# KOMatchStandings=0, which reads as "the mode never sent anything" -- the exact
		# opposite diagnosis from "the mode sent it but nobody was racing".
		live = getattr(self.app, 'live', None)
		if live is not None and getattr(live, 'callbacks_seen', None) is not None:
			live.callbacks_seen['KOMatchStandings'] = (
				live.callbacks_seen.get('KOMatchStandings', 0) + 1)

		if not standings:
			# The mode ends every map, but only fills standings once a knockout has
			# actually been raced: it blocks in Rounds_WaitForPlayers until
			# C_RequiredPlayersNb (2) players are present. Testing alone therefore
			# rotates maps with nothing to score -- not an error, but otherwise
			# invisible in game: no rows, no cup points, no chat, no capture error.
			logger.warning('Knockout: KOMatchStandings fired with no standings')
			if live is not None:
				live.empty_standings_seen = getattr(live, 'empty_standings_seen', 0) + 1
			return
		await self.record_match(standings)

	async def _salvage_unrecorded_match(self):
		"""If the previous Knockout map rotated without KOMatchStandings, force-record
		from the live HUD state so the active cup still gets points.

		Common when the mode is stuck and an admin //skips, or when an older mode
		script never emits Match_EndMap. No-op when there is no active cup, no
		orphan match id, or nothing useful in the live picture.
		"""
		cup = getattr(getattr(self.app, 'cup', None), 'active_cup', None)
		if cup is None:
			return
		live = getattr(self.app, 'live', None)
		if live is None or not getattr(live, 'is_knockout', False):
			return

		# Prefer the oldest queued (not yet consumed) id; fall back to the last
		# allocated id when the queue was already drained without a capture.
		orphan_id = orphan_match_id(
			self._match_start_queue, self._match_start_time, self._captured)
		if orphan_id is None:
			return

		standings = live.synth_standings()
		if not standings:
			logger.warning(
				'Knockout: map rotated with cup active but match %s was never recorded '
				'and live standings are empty (KOMatchStandings missing?)',
				orphan_id,
			)
			return

		# record_match dequeues FIFO; if the id only lived on ``_match_start_time``
		# (queue already empty), put it back so scores land under the orphaned id.
		if not self._match_start_queue or self._match_start_queue[0] != orphan_id:
			self._match_start_queue.appendleft(orphan_id)

		logger.warning(
			'Knockout: map rotated without KOMatchStandings; salvaging %d live '
			'standings for match %s',
			len(standings), orphan_id,
		)
		await self.record_match(standings)

	async def record_match(self, standings):
		# Arm the BOTN / cup TimeAttack handoff before the first await: the mode can
		# advance to the next map (and fire map_start) while we yield on DB I/O.
		self._arm_ta_handoff_if_needed()

		start_time = dequeue_match_start_time(self._match_start_queue, self._last_match_id)
		if start_time > self._last_match_id:
			self._last_match_id = start_time
		if start_time in self._captured:
			return

		# Recording is fire-and-forget from a mode callback, so an exception here used
		# to reach the log and nowhere else: a whole cup could be raced with every map
		# silently unscored (//cup results empty, the cup never auto-completing). Report
		# it in chat and to //ko hud instead.
		try:
			await self._store_match(start_time, standings)
			self._captured.add(start_time)
			if hasattr(self.app, 'on_match_recorded'):
				await self.app.on_match_recorded(start_time, standings)
		except Exception as exc:
			await self._report_capture_failure(start_time, exc)

	async def _report_capture_failure(self, start_time, exc):
		"""Surface a failed capture in game (chat + //ko hud) as well as the log."""
		logger.exception('Knockout: failed to record match %s', start_time)
		live = getattr(self.app, 'live', None)
		if live is not None:
			live.last_capture_error = '{}: {}'.format(type(exc).__name__, exc)
		try:
			await self.instance.chat(
				'$f00>>> Knockout: could not save this map\'s scores — $fff{}$f00. '
				'Run //ko hud; the server log has the detail.'.format(exc)
			)
		except Exception:
			logger.exception('Knockout: could not announce the capture failure')

	async def _store_match(self, start_time, standings):
		"""Write the MatchInfo row plus one PlayerScore row per player."""
		current = self.instance.map_manager.current_map
		mode_script = None
		try:
			mode_script = await self.instance.mode_manager.get_current_script()
		except Exception:
			pass

		existing = list(await MatchInfo.execute(
			MatchInfo.select().where(MatchInfo.map_start_time == start_time)
		))
		if not existing:
			await MatchInfo.execute(MatchInfo.insert(
				map_start_time=start_time,
				mode_script=mode_script,
				map_name=(current.name if current else None),
				map_uid=(current.uid if current else ''),
			))

		for entry in standings:
			player = None
			try:
				player = await self.instance.player_manager.get_player(login=entry['login'])
			except Exception:
				pass
			await PlayerScore.execute(PlayerScore.insert(
				map_start_time=start_time,
				login=entry['login'],
				nickname=(player.nickname if player else entry['login']),
				country=(_player_country(player) if player else None),
				score=entry['points'],
				score2=0,
			))

		logger.info(
			'Knockout: recorded %d standings for match %s on "%s"',
			len(standings), start_time, current.name if current else '?',
		)

	def _arm_ta_handoff_if_needed(self):
		"""Queue TimeAttack for the upcoming map rotation without yielding."""
		botn = getattr(self.app, 'botn', None)
		if botn is not None and botn.active and botn.phase == 'knockout':
			botn.arm_handoff_immediately()
			asyncio.ensure_future(self.app.queue_timeattack())
			return
		cup_ctrl = getattr(self.app, 'cup', None)
		cup = getattr(cup_ctrl, 'active_cup', None) if cup_ctrl else None
		if cup is None:
			return
		target = cup.map_count
		if not target:
			return
		# Last map of a fixed-length cup: same rotation race as BOTN. Count only maps
		# already linked to *this* cup (not session-wide ``_captured``, which also
		# holds earlier BOTN / other matches and would arm TA mid-cup).
		played = int(getattr(cup_ctrl, 'maps_played', 0) or 0)
		if should_arm_cup_handoff(played, target):
			self.app.arm_cup_handoff_immediately()
			asyncio.ensure_future(self.app.queue_timeattack())

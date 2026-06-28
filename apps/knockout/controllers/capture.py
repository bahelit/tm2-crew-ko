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
		# Allocate a stable identifier for the match that is about to be played.
		match_id = allocate_match_start_time(self._last_match_id)
		self._last_match_id = match_id
		self._match_start_time = match_id
		self._match_start_queue.append(match_id)

	async def on_standings(self, standings=None, **kwargs):
		if not standings:
			logger.warning('Knockout: KOMatchStandings fired with no standings')
			return
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

		self._captured.add(start_time)
		logger.info(
			'Knockout: recorded %d standings for match %s on "%s"',
			len(standings), start_time, current.name if current else '?',
		)

		# Hand off to cup logic (no-op until a cup is active, Phase 3).
		if hasattr(self.app, 'on_match_recorded'):
			await self.app.on_match_recorded(start_time, standings)

	def _arm_ta_handoff_if_needed(self):
		"""Queue TimeAttack for the upcoming map rotation without yielding."""
		botn = getattr(self.app, 'botn', None)
		if botn is not None and botn.active and botn.phase == 'knockout':
			botn.arm_handoff_immediately()
			asyncio.ensure_future(self.app.queue_timeattack())
			return
		cup = getattr(getattr(self.app, 'cup', None), 'active_cup', None)
		if cup is None:
			return
		target = cup.map_count
		if not target:
			return
		# Last map of a fixed-length cup: same rotation race as BOTN. ``_captured``
		# holds all maps already recorded; this standings event is for the next one.
		if len(self._captured) >= target - 1:
			self.app.arm_cup_handoff_immediately()
			asyncio.ensure_future(self.app.queue_timeattack())

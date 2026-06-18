import logging
import time

from pyplanet.apps.core.maniaplanet import callbacks as mp_signals

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
		self._standings_signal = None
		self._captured = set()

	async def on_start(self):
		self._standings_signal = register(
			self.app, 'KOMatchStandings', self.on_standings, target=parse_standings)
		self.app.context.signals.listen(mp_signals.map.map_start, self.on_map_start)

	async def on_map_start(self, *args, **kwargs):
		# Allocate a stable identifier for the match that is about to be played.
		self._match_start_time = int(time.time())

	async def on_standings(self, standings=None, **kwargs):
		if not standings:
			logger.warning('Knockout: KOMatchStandings fired with no standings')
			return
		await self.record_match(standings)

	async def record_match(self, standings):
		start_time = self._match_start_time or int(time.time())
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

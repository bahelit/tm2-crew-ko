import logging

from .. import score_modes
from .. import export as export_mod
from ..models import CupMatch, PlayerScore, MatchInfo
from ..views.results import CupResultsView
from ..views.matches import CupMatchesView

logger = logging.getLogger(__name__)


class ResultsController:
	"""Sums per-map scores into overall cup standings and shows the results UI."""

	def __init__(self, app):
		self.app = app
		self.instance = app.instance

	async def compute_standings(self, cup):
		"""
		Return a list of standing dicts sorted best-first:
		``{login, nickname, cup_points, ko_points, maps}``.
		"""
		if cup is None:
			return []

		matches = list(await CupMatch.execute(
			CupMatch.select()
			.where((CupMatch.cup == cup.id) & (CupMatch.counts == True))
			.order_by(CupMatch.map_index)
		))

		totals = {}
		for match in matches:
			rows = list(await PlayerScore.execute(
				PlayerScore.select().where(PlayerScore.map_start_time == match.map_start_time)
			))
			# Highest knockout score = best placement on the map.
			rows.sort(key=lambda row: row.score, reverse=True)

			placement = 0
			prev_score = None
			for position, row in enumerate(rows):
				# Competition ranking: tied scores share the same placement.
				if prev_score is None or row.score != prev_score:
					placement = position
					prev_score = row.score

				points = score_modes.cup_points(cup.score_mode, placement, row.score)
				agg = totals.setdefault(row.login, dict(
					login=row.login, nickname=row.nickname,
					cup_points=0, ko_points=0, maps=0,
				))
				agg['cup_points'] += points
				agg['ko_points'] += row.score
				agg['maps'] += 1
				agg['nickname'] = row.nickname

		standings = list(totals.values())
		standings.sort(key=lambda agg: (agg['cup_points'], agg['ko_points']), reverse=True)
		return standings

	async def show(self, player, cup=None):
		if cup is None:
			cup = self.app.cup.active_cup
		if cup is None:
			cup = await self.app.cup.last_cup()
		if cup is None:
			await self.instance.chat('$bbb>>> No cup to show results for.', player)
			return
		standings = await self.compute_standings(cup)
		view = CupResultsView(self.app, cup, standings)
		await view.display(player=player)

	async def matches_rows(self, cup):
		"""Build display rows for a cup's maps: index, name, player count, counts flag."""
		matches = await self.app.cup.cup_matches(cup)
		rows = []
		for match in matches:
			info = list(await MatchInfo.execute(
				MatchInfo.select().where(MatchInfo.map_start_time == match.map_start_time)
			))
			players = list(await PlayerScore.execute(
				PlayerScore.select().where(PlayerScore.map_start_time == match.map_start_time)
			))
			rows.append(dict(
				index=match.map_index,
				map_name=(info[0].map_name if info and info[0].map_name else '?'),
				players=len(players),
				counts=match.counts,
			))
		return rows

	async def show_matches(self, player, cup):
		rows = await self.matches_rows(cup)
		view = CupMatchesView(self.app, cup, rows)
		await view.display(player=player)

	async def export(self, cup):
		standings = await self.compute_standings(cup)
		directory = await self.app.setting_cup_export_path.get_value()
		return export_mod.write_exports(cup, standings, directory or '')

	async def show_all(self, cup):
		"""Open cup standings for every online player (cup end ceremony)."""
		if cup is None:
			return
		standings = await self.compute_standings(cup)
		if not standings:
			return
		view = CupResultsView(self.app, cup, standings)
		try:
			online = list(self.instance.player_manager.online)
		except Exception:
			logger.exception('Knockout: could not list online players for cup results')
			return
		for entry in online:
			try:
				await view.display(player=entry)
			except Exception:
				logger.exception(
					'Knockout: failed to show cup results to %s',
					getattr(entry, 'login', '?'),
				)

	async def announce_top(self, cup, count=3):
		"""Announce the cup winner and podium in public chat (after cup complete)."""
		standings = await self.compute_standings(cup)
		for line in export_mod.format_completion_messages(standings, count=count):
			await self.instance.chat(line)

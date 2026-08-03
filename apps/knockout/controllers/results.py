import asyncio
import logging

from .. import score_modes
from .. import export as export_mod
from ..models import CupMatch, PlayerScore, MatchInfo
from ..views.results import CupResultsView
from ..views.matches import CupMatchesView

logger = logging.getLogger(__name__)


class ResultsController:
	"""Sums per-map scores into overall cup standings and shows the results UI."""

	# Fallback when the cup_results_autohide setting cannot be read.
	AUTO_HIDE_DEFAULT = 60

	def __init__(self, app):
		self.app = app
		self.instance = app.instance
		# Closes the cup-end results window; see show_all.
		self._auto_hide_task = None

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
		"""Open cup standings for every online player (cup end ceremony).

		The cup completing also drops the server back to TimeAttack, so this window
		would otherwise sit over the next map until every player closed it by hand.
		It closes itself after ``cup_results_autohide`` seconds; ``/cup results``
		reopens it (its own view, which stays up until dismissed)."""
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
		await self._arm_auto_hide(view)

	async def _arm_auto_hide(self, view):
		"""Schedule the ceremony window to close itself, replacing any earlier one."""
		try:
			seconds = int(await self.app.setting_cup_results_autohide.get_value())
		except Exception:
			logger.exception('Knockout: could not read cup_results_autohide')
			seconds = self.AUTO_HIDE_DEFAULT
		self.cancel_auto_hide()
		if seconds <= 0:
			return
		self._auto_hide_task = asyncio.ensure_future(self._auto_hide(view, seconds))

	def cancel_auto_hide(self):
		"""Stop a pending auto-close (a new cup ended, or the app is shutting down)."""
		task = self._auto_hide_task
		self._auto_hide_task = None
		if task is not None and not task.done():
			task.cancel()

	async def _auto_hide(self, view, seconds):
		try:
			await asyncio.sleep(seconds)
			# hide closes it on every client; destroy then unregisters the manialink and
			# its action handlers, so a night of cups does not leave a view per cup
			# registered with the UI manager.
			await view.hide()
			await view.destroy()
		except asyncio.CancelledError:
			raise
		except Exception:
			logger.exception('Knockout: could not auto-close the cup results window')
		# _auto_hide_task is deliberately left pointing at this finished task: clearing
		# it here would race with _arm_auto_hide, which cancels the old task and then
		# stores the new one (this handler runs after that store).

	async def announce_top(self, cup, count=3):
		"""Announce the cup winner and podium in public chat (after cup complete)."""
		standings = await self.compute_standings(cup)
		for line in export_mod.format_completion_messages(standings, count=count):
			await self.instance.chat(line)

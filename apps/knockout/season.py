import logging

logger = logging.getLogger(__name__)


def accumulate_season(cup_standings):
	"""
	Pure aggregation of per-cup standings into a season leaderboard. Kept free of
	any DB/pyplanet dependency so it can be unit-tested directly.

	:param cup_standings: iterable of per-cup standings lists, each best-first and
		shaped like ResultsController.compute_standings output
		(``{login, nickname, cup_points, ko_points, maps}``).
	:return: list of ``{login, nickname, total_cup_points, wins, podiums, cups,
		total_ko_points}`` sorted by cup points, then wins, then podiums.
	"""
	totals = {}
	for standings in cup_standings:
		for placement, row in enumerate(standings):
			agg = totals.setdefault(row['login'], dict(
				login=row['login'], nickname=row['nickname'],
				total_cup_points=0, wins=0, podiums=0, cups=0, total_ko_points=0,
			))
			agg['total_cup_points'] += row['cup_points']
			agg['total_ko_points'] += row['ko_points']
			agg['cups'] += 1
			agg['nickname'] = row['nickname']
			if placement == 0:
				agg['wins'] += 1
			if placement < 3:
				agg['podiums'] += 1

	standings = list(totals.values())
	standings.sort(
		key=lambda agg: (agg['total_cup_points'], agg['wins'], agg['podiums']),
		reverse=True,
	)
	return standings


def season_points_map(standings):
	"""Reduce season standings (as from ``accumulate_season``) to a plain
	``{login: total_cup_points}`` map for quick HUD lookups."""
	return {row['login']: row['total_cup_points'] for row in standings}


def accumulate_player(login, cup_standings):
	"""
	Pure per-player history aggregation. ``cup_standings`` is an iterable of
	``(cup_name, edition, standings)`` tuples, oldest first. Returns
	``(rows, summary)`` with rows most-recent first.
	"""
	rows = []
	wins = podiums = total_cp = total_ko = place_sum = 0
	for cup_name, edition, standings in cup_standings:
		for placement, row in enumerate(standings):
			if row['login'] != login:
				continue
			place = placement + 1
			rows.append(dict(
				cup=cup_name, edition=edition, place=place,
				cup_points=row['cup_points'], ko_points=row['ko_points'],
				maps=row['maps'],
			))
			total_cp += row['cup_points']
			total_ko += row['ko_points']
			place_sum += place
			if placement == 0:
				wins += 1
			if placement < 3:
				podiums += 1
			break

	rows.reverse()  # most recent cup first
	cups = len(rows)
	summary = dict(
		cups=cups, wins=wins, podiums=podiums,
		total_cup_points=total_cp, total_ko_points=total_ko,
		avg_place=round(place_sum / cups, 1) if cups else 0,
	)
	return rows, summary


class SeasonController:
	"""
	Aggregates standings across every cup into a season-long leaderboard, and
	builds a per-player history. Reuses ResultsController.compute_standings so the
	per-cup scoring (score modes, competition ranking) stays in one place.
	"""

	def __init__(self, app):
		self.app = app
		self.instance = app.instance

	async def _cups(self, cup_key=None):
		from .models import CupInfo
		# Only cups stamped to count feed the season leaderboard (see the global
		# save_to_season setting). Cup-local results are unaffected by this filter.
		query = CupInfo.select().where(CupInfo.count_in_season == True)
		if cup_key:
			query = query.where(CupInfo.cup_key == cup_key)
		return list(await CupInfo.execute(query.order_by(CupInfo.id)))

	async def compute_season(self, cup_key=None):
		"""
		Return season standings sorted best-first:
		``{login, nickname, total_cup_points, wins, podiums, cups, total_ko_points}``.
		Ranked by total cup points, then wins, then podiums.
		"""
		per_cup = []
		for cup in await self._cups(cup_key):
			per_cup.append(await self.app.results.compute_standings(cup))
		return accumulate_season(per_cup)

	async def compute_player(self, login, cup_key=None):
		"""
		Return one player's per-cup history (most recent first) plus a summary:
		``(rows, summary)`` where each row is
		``{cup, edition, place, cup_points, ko_points, maps}`` and summary holds
		``{cups, wins, podiums, total_cup_points, total_ko_points, avg_place}``.
		"""
		per_cup = []
		for cup in await self._cups(cup_key):
			standings = await self.app.results.compute_standings(cup)
			per_cup.append((cup.name, cup.edition, standings))
		return accumulate_player(login, per_cup)

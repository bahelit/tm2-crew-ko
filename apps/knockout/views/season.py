from pyplanet.views.generics.list import ManualListView


class SeasonView(ManualListView):
	"""Paginated season leaderboard across all cups, opened via /cup season."""

	icon_style = 'Icons128x128_1'
	icon_substyle = 'Buddies'

	def __init__(self, app, standings, cup_key=None):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.standings = standings
		self.cup_key = cup_key

	async def get_title(self):
		if self.cup_key:
			return 'Season standings: {}'.format(self.cup_key)
		return 'Season standings (all cups)'

	async def get_fields(self):
		return [
			{'name': '#', 'index': 'rank', 'sorting': True, 'searching': False, 'width': 12},
			{'name': 'Player', 'index': 'nickname', 'sorting': False, 'searching': True, 'width': 80},
			{'name': 'Cup Pts', 'index': 'total_cup_points', 'sorting': True, 'searching': False, 'width': 26},
			{'name': 'Wins', 'index': 'wins', 'sorting': True, 'searching': False, 'width': 20},
			{'name': 'Podiums', 'index': 'podiums', 'sorting': True, 'searching': False, 'width': 24},
			{'name': 'Cups', 'index': 'cups', 'sorting': True, 'searching': False, 'width': 20},
		]

	async def get_data(self):
		data = []
		for rank, row in enumerate(self.standings, 1):
			data.append({
				'rank': rank,
				'nickname': row['nickname'],
				'total_cup_points': row['total_cup_points'],
				'wins': row['wins'],
				'podiums': row['podiums'],
				'cups': row['cups'],
			})
		return data


class CupStatsView(ManualListView):
	"""Per-player cup history, opened via /cup stats <login>."""

	icon_style = 'Icons128x128_1'
	icon_substyle = 'Statistics'

	def __init__(self, app, login, nickname, rows, summary):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.login = login
		self.nickname = nickname
		self.rows = rows
		self.summary = summary

	async def get_title(self):
		s = self.summary
		return '{} — {} cups, {} wins, {} podiums, {} pts'.format(
			self.nickname, s['cups'], s['wins'], s['podiums'], s['total_cup_points'])

	async def get_fields(self):
		return [
			{'name': 'Cup', 'index': 'cup', 'sorting': False, 'searching': True, 'width': 70},
			{'name': 'Ed.', 'index': 'edition', 'sorting': True, 'searching': False, 'width': 16},
			{'name': 'Place', 'index': 'place', 'sorting': True, 'searching': False, 'width': 20},
			{'name': 'Cup Pts', 'index': 'cup_points', 'sorting': True, 'searching': False, 'width': 26},
			{'name': 'KO Pts', 'index': 'ko_points', 'sorting': True, 'searching': False, 'width': 24},
			{'name': 'Maps', 'index': 'maps', 'sorting': True, 'searching': False, 'width': 20},
		]

	async def get_data(self):
		return list(self.rows)

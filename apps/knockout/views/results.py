from pyplanet.views.generics.list import ManualListView


class CupResultsView(ManualListView):
	"""Paginated cup standings window, opened via /cup results."""

	icon_style = 'Icons128x128_1'
	icon_substyle = 'Statistics'

	def __init__(self, app, cup, standings):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.cup = cup
		self.standings = standings

	async def get_title(self):
		return 'Cup: {} (edition {})'.format(self.cup.name, self.cup.edition)

	async def get_fields(self):
		return [
			{
				'name': '#',
				'index': 'rank',
				'sorting': True,
				'searching': False,
				'width': 12,
			},
			{
				'name': 'Player',
				'index': 'nickname',
				'sorting': False,
				'searching': True,
				'width': 90,
			},
			{
				'name': 'Cup Pts',
				'index': 'cup_points',
				'sorting': True,
				'searching': False,
				'width': 28,
			},
			{
				'name': 'KO Pts',
				'index': 'ko_points',
				'sorting': True,
				'searching': False,
				'width': 28,
			},
			{
				'name': 'Maps',
				'index': 'maps',
				'sorting': True,
				'searching': False,
				'width': 22,
			},
		]

	async def get_data(self):
		data = []
		for rank, row in enumerate(self.standings, 1):
			data.append({
				'rank': rank,
				'nickname': row['nickname'],
				'cup_points': row['cup_points'],
				'ko_points': row['ko_points'],
				'maps': row['maps'],
			})
		return data

from pyplanet.views.generics.list import ManualListView


class CupMatchesView(ManualListView):
	"""Read-only list of the maps in a cup and whether each counts."""

	icon_style = 'Icons128x128_1'
	icon_substyle = 'NewTrack'

	def __init__(self, app, cup, rows):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.cup = cup
		self.rows = rows

	async def get_title(self):
		return 'Cup maps: {} (edition {})'.format(self.cup.name, self.cup.edition)

	async def get_fields(self):
		return [
			{'name': '#', 'index': 'index', 'sorting': True, 'searching': False, 'width': 12},
			{'name': 'Map', 'index': 'map_name', 'sorting': False, 'searching': True, 'width': 100},
			{'name': 'Players', 'index': 'players', 'sorting': True, 'searching': False, 'width': 24},
			{'name': 'Counts', 'index': 'counts', 'sorting': True, 'searching': False, 'width': 24},
		]

	async def get_data(self):
		data = []
		for row in self.rows:
			data.append({
				'index': row['index'],
				'map_name': row['map_name'],
				'players': row['players'],
				'counts': 'Yes' if row['counts'] else '$888no',
			})
		return data

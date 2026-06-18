from pyplanet.views.template import TemplateView


class CupWidget(TemplateView):
	"""
	Small live standings widget shown during an active cup. Opt-in via the
	show_cup_widget setting; rendering is intentionally minimal.
	"""

	template_name = 'knockout/widget.xml'

	def __init__(self, app):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.id = 'knockout__cup_widget'
		self.cup = None
		self.rows = []

	async def get_context_data(self):
		data = await super().get_context_data()
		data['title'] = 'Cup: {}'.format(self.cup.name) if self.cup else 'Cup'
		data['rows'] = self.rows
		return data

	async def refresh(self, cup, standings, limit=8):
		self.cup = cup
		# y is precomputed here so the template carries no float arithmetic
		# (PyPlanet's Jinja rejects trailing-dot literals like ``-7.``).
		self.rows = [
			dict(rank=index + 1, nickname=row['nickname'], points=row['cup_points'],
				y=-7.0 - index * 4.0)
			for index, row in enumerate(standings[:limit])
		]
		await self.display()

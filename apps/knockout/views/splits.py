from pyplanet.views.template import TemplateView

# Where the first crossing sits below the header tab, and the height of each row.
FIRST_Y = -7.0
ROW_H = 4.2


class SplitsHud(TemplateView):
	"""
	Bottom centre-right rolling feed of recent checkpoint crossings, shown only
	during a live Knockout round (next to the in-game timer). Each crossing lists
	the player, the checkpoint they hit, and their split versus the best time seen
	at that checkpoint so far -- the leading split shows as an absolute time, the
	rest as a ``+gap``. Newest crossing on top; the LiveController builds the feed
	(resolving names as crossings arrive) and calls refresh()/hide().
	"""

	template_name = 'knockout/splits.xml'

	def __init__(self, app):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.id = 'knockout__splits_hud'
		self.rows = []

	async def get_context_data(self):
		data = await super().get_context_data()
		data['rows'] = self.rows
		return data

	async def refresh(self, feed):
		"""(Re)display the feed. ``feed`` is the newest-first list of crossing dicts
		(name, cp, split, color) the LiveController maintains; y is assigned here so
		the template stays arithmetic-free."""
		rows = []
		for index, entry in enumerate(feed):
			row = dict(entry)
			row['y'] = FIRST_Y - index * ROW_H
			rows.append(row)
		self.rows = rows
		if not self.rows:
			await self.hide()
			return
		await self.display()

from pyplanet.views.template import TemplateView

from ..hud_format import ml_num

# Where the first crossing sits below the header tab, and the height of each row.
FIRST_Y = -7
ROW_H = 4


class SplitsHud(TemplateView):
	"""
	Bottom middle-right rolling feed of recent checkpoint crossings, shown only
	during a live Knockout round (near the in-game timer). Each crossing lists
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
		data['body_height'] = ml_num(max(4, len(self.rows) * ROW_H + 2))
		return data

	async def refresh(self, feed):
		"""(Re)display the feed. ``feed`` is the newest-first list of crossing dicts
		(name, cp, split, color) the LiveController maintains; y is assigned here so
		the template stays arithmetic-free."""
		rows = []
		for index, entry in enumerate(feed):
			row = dict(entry)
			row['y'] = ml_num(FIRST_Y - index * ROW_H)
			rows.append(row)
		self.rows = rows
		if not self.rows:
			await self.hide()
			return
		await self.display()

	async def show_test(self, player=None):
		"""Force-render the feed with placeholder rows, ignoring match state. Used by
		the //ko splits diagnostic to prove the panel renders where it is expected.
		Shown only to ``player`` when given, otherwise to everyone."""
		feed = [
			dict(name='Test A', cp='CP 1', split='12.470', color='66FF66'),
			dict(name='Test B', cp='CP 1', split='+0.031', color='66FF66'),
			dict(name='Test C', cp='FIN', split='+0.250', color='66FF66'),
		]
		self.rows = [
			dict(entry, y=ml_num(FIRST_Y - index * ROW_H))
			for index, entry in enumerate(feed)
		]
		# player_logins, not player -- see MatchHud.show_test.
		login = getattr(player, 'login', None)
		if login:
			await self.display(player_logins=[login])
		else:
			await self.display()

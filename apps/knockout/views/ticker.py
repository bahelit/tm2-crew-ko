from pyplanet.views.template import TemplateView


class CupTicker(TemplateView):
	"""
	Persistent broadcast ticker shown during a live Knockout match: how many
	players remain, who is on the elimination bubble (tinted red), and a special
	"final two" showdown treatment. Driven by LiveController.refresh().
	"""

	template_name = 'knockout/ticker.xml'

	def __init__(self, app):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.id = 'knockout__ticker'
		self.count = 0
		self.showdown = False
		self.danger_names = []
		self.racing_names = []

	async def get_context_data(self):
		data = await super().get_context_data()
		data['count'] = self.count
		data['showdown'] = self.showdown
		data['racing_names'] = self.racing_names
		# Precompute each bubble row's y here so the template carries no float
		# arithmetic (PyPlanet's Jinja rejects trailing-dot literals like ``-5.5.``).
		data['danger_rows'] = [
			dict(name=name, y=-5.5 - index * 3.0)
			for index, name in enumerate(self.danger_names)
		]
		return data

	async def refresh(self, live):
		"""Pull the current picture from the LiveController and (re)display."""
		if live.phase in ('idle', 'ended') or live.count <= 0:
			await self.hide()
			return

		self.count = live.count
		self.showdown = live.phase == 'showdown'

		danger = set(live.danger_logins())
		self.danger_names = [await self._name(login) for login in danger]
		# In a showdown, name both finalists; otherwise we only call out the bubble.
		if self.showdown:
			self.racing_names = [await self._name(login) for login in live.racing]
		else:
			self.racing_names = []

		await self.display()

	async def _name(self, login):
		try:
			player = await self.app.instance.player_manager.get_player(login=login)
			return player.nickname
		except Exception:
			return login

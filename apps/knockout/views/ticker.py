from pyplanet.views.template import TemplateView


class CupTicker(TemplateView):
	"""
	Stream ticker: players remaining, elimination bubble (red), and final-two
	showdown names. Shown to pure spectators and /ko stream opt-ins by default,
	or to everyone when show_overlays is on. Driven by LiveController.
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
		self._practice = False

	async def get_context_data(self):
		data = await super().get_context_data()
		data['count'] = self.count
		data['showdown'] = self.showdown
		data['racing_names'] = self.racing_names
		data['practice'] = bool(getattr(self, '_practice', False))
		# Precompute each bubble row's y here so the template carries no float
		# arithmetic (PyPlanet's Jinja rejects trailing-dot literals like ``-5.5.``).
		data['danger_rows'] = [
			dict(name=name, y=-5.5 - index * 3.0)
			for index, name in enumerate(self.danger_names)
		]
		return data

	async def refresh(self, live):
		"""Pull the current picture from the LiveController and (re)display.

		Live KO rounds show the racing count + danger bubble. During cup/BOTN
		warm-up (phase idle while a Knockout event is active) we still push a
		practice ticker so the dedicated spectator is not blank for friday's
		multi-lap warm-ups.
		"""
		self.showdown = live.phase == 'showdown'
		danger = set(live.danger_logins()) if live.phase not in ('idle', 'ended') else set()
		self.danger_names = [await self._name(login) for login in danger]

		if live.phase not in ('idle', 'ended') and live.count > 0:
			self._practice = False
			self.count = live.count
			# In a showdown, name both finalists; otherwise we only call out the bubble.
			if self.showdown:
				self.racing_names = [await self._name(login) for login in live.racing]
			else:
				self.racing_names = []
			await self.app.push_stream_view(self, visible=True)
			return

		# Warm-up / practice stream presence during an active cup or BOTN.
		event_active = bool(getattr(live, 'cup_active', False))
		botn = getattr(self.app, 'botn', None)
		if botn is not None and getattr(botn, 'active', False):
			event_active = True
		is_knockout = bool(getattr(live, 'is_knockout', False))
		if event_active and is_knockout and live.phase in ('idle', 'ended'):
			try:
				logins = await live.roster_logins()
			except Exception:
				logins = []
			self.count = len(logins)
			self.showdown = False
			self.danger_names = []
			# Sentinel consumed by the template: empty danger + showdown false +
			# practice_label in context (see get_context_data).
			self.racing_names = []
			self._practice = True
			await self.app.push_stream_view(self, visible=True)
			return

		self._practice = False
		await self.app.push_stream_view(self, visible=False)

	async def _name(self, login):
		try:
			player = await self.app.instance.player_manager.get_player(login=login)
			return player.nickname
		except Exception:
			return login

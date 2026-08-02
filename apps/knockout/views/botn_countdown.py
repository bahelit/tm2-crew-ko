from pyplanet.views.template import TemplateView


class BotnCountdown(TemplateView):
	"""
	Right-side countdown shown to everyone during a Bowl of the Night. It is armed
	for the whole event: "PRACTICE ENDS IN" while practice runs down to the cutoff,
	then "STARTING IN" through the short handoff window before the knockout loads.
	The seconds tick client-side (embedded ManiaScript), so it stays smooth without
	a server refresh every frame -- the BotnController only (re)shows it when the
	target or header changes and hides it when the knockout starts (or the BOTN is
	stopped). The readout grows from bare seconds to M:SS to H:MM:SS as needed,
	since the practice wait can run for hours.
	"""

	template_name = 'knockout/botn_countdown.xml'

	def __init__(self, app):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.id = 'knockout__botn_countdown'
		self.seconds = 900
		self.header = 'STARTING IN'

	async def get_context_data(self):
		data = await super().get_context_data()
		secs = max(1, int(self.seconds))
		data['seconds'] = secs
		# The client script counts down from this many milliseconds.
		data['ms'] = secs * 1000
		data['header'] = self.header
		return data

	async def start(self, seconds, header='STARTING IN', player=None):
		"""(Re)arm and display the countdown for ``seconds`` seconds under ``header``.

		With ``player`` set, send only to that player (used to catch a late joiner up
		with their remaining time without resetting everyone else's running clock);
		otherwise display to everyone currently connected."""
		self.seconds = max(1, int(seconds or 0))
		self.header = header or 'STARTING IN'
		# player_logins, not player: a `player` kwarg is swallowed by TemplateView and
		# the countdown goes to everyone -- which would restart the running clock on
		# every client each time one late joiner is caught up.
		login = getattr(player, 'login', None)
		if login:
			await self.display(player_logins=[login])
		else:
			await self.display()

from pyplanet.views.template import TemplateView


class BotdCountdown(TemplateView):
	"""
	Right-side "KNOCKOUT IN" countdown shown to everyone during the BOTD handoff:
	the window between practice closing at the cutoff and the knockout script
	loading. The BotdController arms it for the configured countdown length and the
	seconds tick client-side (embedded ManiaScript), so it stays smooth without a
	server refresh every frame -- the controller only shows it once and hides it
	when the knockout starts (or the BOTD is stopped). Mirrors the lower-right
	``FinishCountdown`` but with an M:SS readout since the wait can run to minutes.
	"""

	template_name = 'knockout/botd_countdown.xml'

	def __init__(self, app):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.id = 'knockout__botd_countdown'
		self.seconds = 900

	async def get_context_data(self):
		data = await super().get_context_data()
		secs = max(1, int(self.seconds))
		data['seconds'] = secs
		# The client script counts down from this many milliseconds.
		data['ms'] = secs * 1000
		return data

	async def start(self, seconds):
		"""(Re)arm and display the countdown for ``seconds`` seconds."""
		self.seconds = max(1, int(seconds or 0))
		await self.display()

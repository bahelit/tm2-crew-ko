from pyplanet.views.template import TemplateView


class FinishCountdown(TemplateView):
	"""
	Lower-right "FINISH NOW" countdown shown to everyone once the first player
	crosses the line in a live Knockout round. The mode arms the same cut-off
	(``S_FinishCountdown``) server-side; this overlay mirrors it for the broadcast
	with a big, colour-shifting readout and a depleting bar. The seconds tick
	client-side (embedded ManiaScript), so it stays smooth without a server
	refresh every frame -- the controller only shows it once and hides it when the
	round resolves.
	"""

	template_name = 'knockout/finish_countdown.xml'

	def __init__(self, app):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.id = 'knockout__finish_countdown'
		self.seconds = 30

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

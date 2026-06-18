import asyncio

from pyplanet.views.template import TemplateView


class CupLowerThird(TemplateView):
	"""
	Transient broadcast banner for big moments: an elimination, the round winner,
	or a shield being earned/spent. Shown via flash(), it auto-hides after a few
	seconds. A newer flash supersedes an older one's pending hide.
	"""

	template_name = 'knockout/lower_third.xml'

	def __init__(self, app, duration=5.0):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.id = 'knockout__lower_third'
		self.text = ''
		self.duration = duration
		self._token = 0

	async def get_context_data(self):
		data = await super().get_context_data()
		data['text'] = self.text
		return data

	async def flash(self, text):
		self.text = text
		self._token += 1
		token = self._token
		await self.display()
		asyncio.ensure_future(self._auto_hide(token))

	async def _auto_hide(self, token):
		await asyncio.sleep(self.duration)
		# Only hide if no newer flash replaced us in the meantime.
		if token == self._token:
			await self.hide()

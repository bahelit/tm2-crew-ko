import asyncio

from pyplanet.views.template import TemplateView


class CupLowerThird(TemplateView):
	"""
	Transient stream banner for big moments: elimination, round winner, or shield
	earned/spent. Same audience as the ticker (spectators + /ko stream, or everyone
	when show_overlays is on). flash() auto-hides after a few seconds; a newer
	flash supersedes an older pending hide.
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
		await self.app.push_stream_view(self, visible=True)
		asyncio.ensure_future(self._auto_hide(token))

	async def _auto_hide(self, token):
		await asyncio.sleep(self.duration)
		# Only hide if no newer flash replaced us in the meantime.
		if token == self._token:
			await self.app.push_stream_view(self, visible=False)

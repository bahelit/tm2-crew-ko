from pyplanet.views.template import TemplateView

from ..hud_format import ticker_render_signature


class CupTicker(TemplateView):
	"""
	Stream ticker: players remaining, elimination bubble (red), and final-two
	showdown names during live KO rounds. Shown to pure spectators and /ko stream
	opt-ins by default, or to everyone when show_overlays is on. Warm-up no longer
	shows a center "PRACTICE / N ON SERVER" card (left match HUD has the roster).
	Driven by LiveController.
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
		# Set by KnockoutConfig.push_stream_view: the (audience, signature) pair the
		# clients are currently showing, so a push that would repaint the same thing for
		# the same people is dropped. invalidate() clears it -- see the note there.
		self.stream_sent = None
		# ManiaLink pages actually pushed. Reported by //ko hud.
		self.sends = 0

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

	def invalidate(self):
		"""Forget what is on screen, so the next refresh() pushes unconditionally.

		ManiaLink pages live on the client, so a player who just connected holds
		nothing until something is pushed to them. push_stream_view already folds the
		audience into what it remembers, which covers a connect on the per-login path
		-- but not on the global one (``show_overlays``), where a send carries no login
		list at all and a new arrival would sit behind the dedupe forever.
		LiveController calls this on every roster change, alongside the HUD and splits.
		"""
		self.stream_sent = None

	async def refresh(self, live):
		"""Pull the current picture from the LiveController and (re)display.

		Live KO rounds show the racing count + danger bubble for the stream box.
		Warm-up / between-maps no longer push a center "PRACTICE / N ON SERVER"
		card — that duplicated the left match HUD and sat under the Round banner.

		The push is deduped on (audience, what would be drawn): this runs on every
		overlay refresh -- every KORoundOrder, every best-lap improvement -- and the
		ticker is a count plus a couple of names, so nearly all of those repaint an
		identical card. The signature is computed after the state above is settled and
		handed to push_stream_view, which folds the target set in on top.
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
			await self.app.push_stream_view(
				self, visible=True, signature=ticker_render_signature(self))
			return

		self._practice = False
		await self.app.push_stream_view(
			self, visible=False, signature=ticker_render_signature(self))

	async def _name(self, login):
		try:
			player = await self.app.instance.player_manager.get_player(login=login)
			return player.nickname
		except Exception:
			return login

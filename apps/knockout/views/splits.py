from pyplanet.views.template import TemplateView

from ..hud_format import ml_num, split_row_signature

# Where the first standings row sits below the header tab, and the height of each row.
# Both stay whole numbers: the template writes "{{ y }}." in ManiaLink's trailing-dot
# syntax, and a fractional value there renders as "-7.5." and silently fails to draw.
FIRST_Y = -7
ROW_H = 4

# "We do not know what the clients are showing." refresh()/hide() skip the send when
# it would repaint what is already on screen, and this is the state that forces one
# through. invalidate() puts us back here -- see the note on that method.
_UNKNOWN = object()


class SplitsHud(TemplateView):
	"""
	Bottom middle-right checkpoint standings board, shown only during a live Knockout
	round (near the in-game timer). One row per player, ordered by race progress:
	furthest checkpoint first, then fastest time at it. Each row lists the player, the
	checkpoint they last crossed, and their split versus the best time seen at that
	checkpoint so far -- the leader shows an absolute time, the rest a ``+gap``.

	This replaced a rolling newest-first feed of the last six crossings, where every
	checkpoint anybody hit shoved every name down a row and no player could be tracked.
	A row now moves only when its player is genuinely overtaken. The LiveController owns
	the rows (resolving names as crossings arrive, ordering them with
	hud_format.order_split_rows) and calls refresh()/hide().
	"""

	template_name = 'knockout/splits.xml'

	def __init__(self, app):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.id = 'knockout__splits_hud'
		self.rows = []
		# Signature of the board the clients are currently showing: None while it is
		# hidden, a split_row_signature() tuple while it is up, _UNKNOWN when we cannot
		# be sure (startup, or after invalidate()).
		self._sent = _UNKNOWN
		# ManiaLink pages actually pushed to clients. Paired with LiveController's
		# splits_requests in //ko splits, so the coalescing/dedupe can be checked on a
		# live server instead of taken on trust.
		self.sends = 0

	async def get_context_data(self):
		data = await super().get_context_data()
		data['rows'] = self.rows
		data['body_height'] = ml_num(max(4, len(self.rows) * ROW_H + 2))
		return data

	async def refresh(self, rows):
		"""(Re)display the board. ``rows`` is the already-ordered, already-truncated list
		of row dicts (name, cp_label, split, color) the LiveController produces; y is
		assigned here so the template stays arithmetic-free.

		A repaint that would draw exactly what is already on screen is dropped. The
		board is capped at SPLITS_ROWS, so most checkpoint crossings on a full server
		are by players who are not on it -- without this, each of those still cost every
		client a full ManiaLink page replacement (and its re-layout hitch) to redraw an
		identical panel. Anything that can leave a client without the page it should
		have -- a connect, a spectator flip -- must call invalidate() first.
		"""
		ordered = rows
		rows = []
		for index, entry in enumerate(ordered):
			row = dict(entry)
			row['y'] = ml_num(FIRST_Y - index * ROW_H)
			rows.append(row)
		if not rows:
			self.rows = rows
			await self.hide()
			return
		signature = split_row_signature(rows)
		if signature == self._sent:
			return
		self.rows = rows
		# Recorded only after display() returns -- see MatchHud.refresh for why.
		await self.display()
		self._sent = signature
		self.sends += 1

	async def hide(self, player_logins=None):
		"""Hide the board, skipping the send when it is already hidden for everyone.

		Between rounds the controller re-runs its overlay refresh on every roster
		change and finish, and each of those used to broadcast a hide for a panel that
		had not been visible for minutes. A targeted hide (``player_logins``) is always
		sent and leaves the global state alone -- it says nothing about what the rest of
		the server can see.
		"""
		if player_logins is not None:
			await super().hide(player_logins=player_logins)
			return
		if self._sent is None:
			return
		await super().hide()
		self._sent = None
		self.sends += 1

	def invalidate(self):
		"""Forget what is on screen, so the next refresh()/hide() sends unconditionally.

		ManiaLink pages live on the client: a player who just connected holds nothing
		until something is pushed to them, and the dedupe above would happily decide the
		board is "already showing" and skip that push. LiveController calls this on
		every roster change for exactly that reason -- it is what keeps the self-heal in
		on_roster_change working now that repeats are dropped.
		"""
		self._sent = _UNKNOWN

	async def show_test(self, player=None):
		"""Force-render the board with placeholder rows, ignoring match state. Used by
		the //ko splits diagnostic to prove the panel renders where it is expected.
		Six rows, so it also proves the tallest layout the real board can reach still
		clears the finish countdown in the same corner.
		Shown only to ``player`` when given, otherwise to everyone."""
		feed = [
			dict(name='Test A', cp_label='FIN', split='12.470', color='66FF66'),
			dict(name='Test B', cp_label='CP 3', split='+0.031', color='66FF66'),
			dict(name='Test C', cp_label='CP 3', split='+0.250', color='66FF66'),
			dict(name='Test D', cp_label='CP 2', split='+1.900', color='66FF66'),
			dict(name='Test E', cp_label='CP 2', split='+2.480', color='66FF66'),
			dict(name='Test F', cp_label='CP 1', split='+4.010', color='66FF66'),
		]
		self.rows = [
			dict(entry, y=ml_num(FIRST_Y - index * ROW_H))
			for index, entry in enumerate(feed)
		]
		# Placeholder rows are not what the live board would compute, so leave the
		# dedupe with no opinion: the next real refresh must repaint over them.
		self._sent = _UNKNOWN
		# player_logins, not player -- see MatchHud.show_test.
		login = getattr(player, 'login', None)
		if login:
			await self.display(player_logins=[login])
		else:
			await self.display()

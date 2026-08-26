from pyplanet.views.template import TemplateView

from ..hud_format import (
	format_race_time, format_gap, format_hud_name, match_label, round_value,
	hud_applies, is_practice_phase, ml_num, cup_map_value, title_textsize,
	hud_render_signature,
)

# Layout mirrors the BOTN countdown: a title tab (TITLE_H) then a body panel.
# Stats sit just under the tab; player rows follow. All geometry is precomputed
# here so the template never does float arithmetic. The stats block is variable
# length (a MAP line joins it during a cup), so the rows below it are positioned
# off the last stat line rather than a fixed constant.
TITLE_H = 7
STATS_TOP = -9   # y of the first stat line
STATS_STEP = 4   # spacing between stat lines
ROW_H = 4

# Gap between the last stat line and the first player row. The points column gets
# its own "CUP" heading in that gap, so it needs a wider one when it is shown.
ROWS_GAP = 5
ROWS_GAP_SEASON = 9

# When more players are listed than MAX_ROWS, the middle is collapsed to a single
# "…" marker: the top HEAD_ROWS and the trailing rows (which include the danger
# zone) are kept so the leaders and the elimination bubble are always visible.
HEAD_ROWS = 4
MAX_ROWS = 16

# Panel geometry. 46 wide is the footprint of the cup standings widget this panel
# replaced; it keeps the board compact and leaves x -113..-95 back to PyPlanet's
# own left-hand widgets during the cup's TimeAttack phases. The column bands are
# derived from these in get_context_data() and passed to the template ready-made
# -- the template must never do arithmetic (see hud_format.ml_num).
BG_WIDTH = 46
PAD = 2            # left/right margin inside the panel
RANK_X = 2
RANK_W = 4         # "16" at textsize 1 is about 2.3 units
NAME_X = 6
TIME_W = 12        # fits the leader's absolute "1:01.000" (about 9 units)
PTS_W = 8          # three-digit cup totals
COL_GAP = 1        # clear space between the time and points columns
STAT_SPLIT = 24    # x where the stat label box ends and its right-aligned value starts
TITLE_TEXT_W = BG_WIDTH - 4   # usable width of the title tab

# Per-cell colours.
WHITE = 'FFFFFF'      # rank + name (clan-tag $codes colour the names themselves)
RED = 'FF3333'        # times in the danger zone (about to be eliminated)
GREEN = '66FF66'      # safe times: the leader's absolute time and the gaps behind it
BUBBLE = 'FFCC00'     # the last safe time, one spot above the cut line
DIM = 'AAAAAA'        # no time yet / gap marker

# Title shown in place of "MATCH n" when the live event is a Bowl of the Night.
BOTN_TITLE = 'BOWL OF THE NIGHT'

# "We do not know what the clients are showing." refresh()/hide() skip the send when it
# would repaint what is already on screen, and this is the state that forces one
# through. invalidate() puts us back here -- see the note on that method.
_UNKNOWN = object()


class MatchHud(TemplateView):
	"""
	Always-on left-side match HUD shown to everyone (players and spectators)
	during a live Knockout match. A structured header (match number, round,
	players left, KOs per round) sits above the running order; each row shows the
	player's gap to the leader (the leader shows an absolute time). Elimination-
	bubble players are tinted red below a divider. Driven by LiveController.refresh().
	"""

	template_name = 'knockout/hud.xml'

	def __init__(self, app):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.id = 'knockout__match_hud'
		self.match_text = 'KNOCKOUT'
		self.round_text = '—'
		self.map_text = ''
		self.show_map = False
		self.players_count = 0
		self.rows = []
		self.has_divider = False
		self.divider_y = 0.0
		self.show_season = False
		self.title_textsize = '2'
		# Signature of the board the clients are currently showing: None while it is
		# hidden, a hud_render_signature() tuple while it is up, _UNKNOWN when we cannot
		# be sure (startup, or after invalidate()).
		self._sent = _UNKNOWN
		# ManiaLink pages actually pushed. Reported by //ko hud next to the controller's
		# request count, so the dedupe can be checked on a live server.
		self.sends = 0

	async def get_context_data(self):
		data = await super().get_context_data()
		data['match_text'] = self.match_text
		data['players_count'] = self.players_count
		data['rows'] = self.rows
		data['has_divider'] = self.has_divider
		data['divider_y'] = ml_num(self.divider_y)
		data['title_h'] = ml_num(TITLE_H)
		data['stats'] = [
			dict(label=label, value=value, y=ml_num(STATS_TOP - index * STATS_STEP))
			for index, (label, value) in enumerate(self._stats())
		]
		# The panel is a fixed 46 wide in both cases: a cup's points column is paid for
		# by pulling the time column left and shortening the name column, not by
		# widening the board. All geometry is precomputed here so the template stays
		# arithmetic-free -- Jinja renders a float as "46.0", which turns
		# size="{{ w }}. {{ h }}." into "46.0. 38.0." and the quad silently never draws.
		data['show_season'] = self.show_season
		bg_width = BG_WIDTH
		right = bg_width - PAD
		time_x = right - (PTS_W + COL_GAP) if self.show_season else right
		# Bands abut exactly, so a long nickname is clipped at the box edge rather than
		# running under the time. Do NOT truncate names in Python instead: they carry
		# clan-tag $codes and cutting one mid-code corrupts the rest of the row.
		name_w = time_x - TIME_W - NAME_X
		rows_start = self._rows_start()
		# Body runs from under the title tab to just past the last player row.
		body_height = -rows_start - TITLE_H + len(self.rows) * ROW_H
		# "CUP" heading for the points column, in the gap above the first row. It
		# cannot share a stat line: the stat values are right-aligned at the same
		# panel edge and would be drawn over.
		data['col_head_y'] = ml_num(rows_start + ROW_H)
		data['bg_width'] = ml_num(bg_width)
		data['body_height'] = ml_num(body_height)
		data['title_w'] = ml_num(bg_width - 4)
		data['center_x'] = ml_num(bg_width / 2)
		data['header_val_x'] = ml_num(right)
		data['divider_w'] = ml_num(bg_width - 4)
		# Stat lines: an explicit split so the left label and the right-aligned value
		# cannot overlap. At 46 wide there is no slack left to absorb it.
		data['stat_label_w'] = ml_num(STAT_SPLIT - PAD)
		data['stat_val_w'] = ml_num(right - STAT_SPLIT)
		data['rank_x'] = ml_num(RANK_X)
		data['rank_w'] = ml_num(RANK_W)
		data['name_x'] = ml_num(NAME_X)
		data['name_w'] = ml_num(name_w)
		data['time_x'] = ml_num(time_x)
		data['time_w'] = ml_num(TIME_W)
		# Emitted even without a cup (where they go unused), so the template never
		# sees a Jinja Undefined.
		data['pts_x'] = ml_num(right)
		data['pts_w'] = ml_num(PTS_W)
		data['title_textsize'] = self.title_textsize
		return data

	async def refresh(self, live):
		"""Pull the current picture from the LiveController and (re)display. The HUD
		stays up for the whole Knockout: during warm-up it lists the players on the
		server with their best lap so far; once rounds start it switches to the live
		running order with elimination highlighting. It only hides when the loaded
		mode is not Knockout, or when nobody is on the server to show.

		A repaint that would draw exactly what is already on screen is dropped. This
		runs on every KORoundOrder and every best-lap improvement -- dozens of times in
		a round, most of them leaving the board identical (a checkpoint that does not
		change the order, a finish that beats nobody) -- and each one used to cost every
		client a full ManiaLink page replacement and its re-layout hitch. Anything that
		can leave a client without the page it should have -- a connect, a spectator
		flip -- must call invalidate() first.
		"""
		cup_active = getattr(live, 'cup_active', False)
		is_knockout = getattr(live, 'is_knockout', True)
		if not hud_applies(is_knockout, cup_active):
			await self.hide()
			return

		botn = getattr(self.app, 'botn', None)
		botn_active = bool(botn and botn.active)
		botn_phase = getattr(botn, 'phase', 'idle') if botn else 'idle'
		practice = is_practice_phase(
			is_knockout, cup_active, botn_active=botn_active, botn_phase=botn_phase)

		if getattr(live, 'is_botn', False):
			self.match_text = BOTN_TITLE
		elif cup_active:
			# Cup-of-the-day style: show the cup name while a cup is running.
			self.match_text = (getattr(live, 'cup_name', None) or 'CUP').upper()
		else:
			self.match_text = match_label(getattr(live, 'match_number', 0))
		# A long title needs a smaller font so it fits the tab without wrapping down
		# into the stats block below. One rule for all three paths: the tab is only 42
		# units wide, so "BOWL OF THE NIGHT" and the 19-character preset cup names both
		# step down a tier.
		self.title_textsize = title_textsize(self.match_text, TITLE_TEXT_W)
		if practice:
			self.round_text = 'PRACTICE'
		else:
			self.round_text = round_value(getattr(live, 'round', 0), getattr(live, 'total_rounds', 0))
		# MAP line: which map of the cup is being played. Only while a cup runs -- a
		# standalone knockout is a single map and the line would say "1" -- and never
		# during a BOTN, which plays one map a night: "MAP 1 of 3" there counts nights,
		# not anything happening on screen tonight.
		self.show_map = bool(cup_active) and not getattr(live, 'is_botn', False)
		self.map_text = cup_map_value(
			getattr(live, 'cup_maps_played', 0), getattr(live, 'cup_map_count', 0)
		) if self.show_map else ''
		danger = set() if practice else set(live.danger_logins())
		# login -> shields banked. Stacks up to S_MaxShields and carries across the maps
		# of a cup, so the HUD draws one + per shield rather than a single marker.
		shield_counts = dict(getattr(live, 'shield_counts', None) or {})

		# Points column (running cup total) is part of the CotD-style match HUD during
		# an active cup/BOTN: always on from map 1 (zeros until a map is recorded), so
		# admins do not need a separate //settings toggle for it to appear. The global
		# show_season_points setting can only hide the column when no cup is active
		# (which is a no-op — there are no points to show then).
		season = getattr(live, 'season_points', None) or {}
		show_season = bool(cup_active)
		self.show_season = show_season

		# Collect (login, time_ms, finished) in display order: live round order when
		# a round is on, otherwise the warm-up roster sorted by best lap.
		entries = []
		if live.order:
			for entry in live.order:
				login = entry.get('login')
				if not login or login not in live.racing:
					continue
				entries.append((login, entry.get('time', -1), entry.get('finished', False)))
		else:
			logins = await live.roster_logins()
			logins.sort(key=lambda lg: (live.best_time(lg) < 0, live.best_time(lg)))
			for login in logins:
				entries.append((login, live.best_time(login), False))

		self.players_count = len(entries)

		# Baseline for gap times: the fastest valid time on the board.
		leader_ms = None
		for _login, time_ms, _finished in entries:
			ms = self._as_int(time_ms)
			if ms >= 0 and (leader_ms is None or ms < leader_ms):
				leader_ms = ms

		rows = []
		for index, (login, time_ms, _finished) in enumerate(entries):
			ms = self._as_int(time_ms)
			is_danger = login in danger
			if ms < 0:
				time_text, time_color = '—', DIM
			elif leader_ms is not None and ms == leader_ms:
				time_text, time_color = format_race_time(ms), GREEN
			else:
				time_text, time_color = format_gap(ms - (leader_ms or 0)), GREEN
			if is_danger:
				time_color = RED
			rows.append(dict(
				gap=False,
				danger=is_danger,
				rank=index + 1,
				name=format_hud_name(await self._name(login), shields=shield_counts.get(login, 0)),
				time=time_text,
				# Names stay white so the clan-tag colours show; the danger zone reads
				# as red times below the divider, matching the cup-of-the-day style.
				name_color=WHITE,
				time_color=time_color,
				season_points=(season.get(login, 0) if show_season else None),
			))

		rows = self._collapse_middle(rows)
		self._layout(rows)
		self.rows = rows

		if not rows:
			await self.hide()
			return
		# After _layout: it is what assigns row y, the divider, and the bubble colour,
		# so the panel state is only final here.
		signature = hud_render_signature(self, rows)
		if signature == self._sent:
			return
		# Recorded only after display() returns: doing it first would mean a transient
		# send failure left us believing a page is on screen that never arrived, and
		# every identical refresh afterwards would skip -- the panel would stay stale
		# until its content happened to change.
		await self.display()
		self._sent = signature
		self.sends += 1

	async def hide(self, player_logins=None):
		"""Hide the panel, skipping the send when it is already hidden for everyone.

		A targeted hide (``player_logins``) is always sent and leaves the global state
		alone -- it says nothing about what the rest of the server can see.
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
		panel is "already showing" and skip that push. LiveController calls this on every
		roster change for exactly that reason.
		"""
		self._sent = _UNKNOWN

	# ------------------------------------------------------------- helpers

	def _stats(self):
		"""The header stat lines, top to bottom, as (label, value) pairs. MAP joins
		them while a (non-BOTN) cup is running so the field can see how far along it
		is. The mode announces the double-knockout threshold in chat, so the board
		stays short: three lines at most, which keeps it out of the way of PyPlanet's
		own left-hand widgets during the TimeAttack phases. Note the panel's right edge
		is x=-113 and live_rankings sits around x=-124.75, so they still meet there --
		less than the old 64-wide board did, but do not treat -113 as clear."""
		stats = []
		if self.show_map:
			stats.append(('MAP', self.map_text))
		stats.append(('ROUND', self.round_text))
		stats.append(('PLAYERS', self.players_count))
		return stats

	def _rows_start(self):
		"""y of the first player row: below the (variable-length) stats block, with
		room for the points column's heading when that column is shown."""
		gap = ROWS_GAP_SEASON if self.show_season else ROWS_GAP
		return STATS_TOP - (len(self._stats()) - 1) * STATS_STEP - gap

	@staticmethod
	def _as_int(value):
		try:
			return int(value)
		except (TypeError, ValueError):
			return -1

	@staticmethod
	def _collapse_middle(rows):
		"""Window a long field down to the leaders plus the trailing (danger) rows,
		with a single gap marker standing in for the elided middle."""
		if len(rows) <= MAX_ROWS:
			return rows
		tail = MAX_ROWS - HEAD_ROWS - 1
		return rows[:HEAD_ROWS] + [dict(gap=True)] + rows[-tail:]

	def _layout(self, rows):
		"""Assign each row its y position, drop the divider above the first danger
		row, and gild the last safe time (the bubble) just above the cut line."""
		self.has_divider = False
		self.divider_y = 0
		start_y = self._rows_start()
		for index, row in enumerate(rows):
			row['y'] = ml_num(start_y - index * ROW_H)
			if not self.has_divider and not row.get('gap') and row.get('danger'):
				self.has_divider = True
				self.divider_y = ml_num(row['y'] + 1)
				prev = rows[index - 1] if index > 0 else None
				if prev and not prev.get('gap') and not prev.get('danger'):
					prev['time_color'] = BUBBLE

	async def _name(self, login):
		try:
			player = await self.app.instance.player_manager.get_player(login=login)
			return player.nickname
		except Exception:
			return login

	async def show_test(self, player=None):
		"""Force-render the HUD with placeholder rows, ignoring match state. Used
		by the //ko hud diagnostic to confirm the manialink renders at all. Shown
		only to ``player`` when given, otherwise to everyone (the real path).

		Deliberately renders the *tightest* layout the panel has -- a cup, so all four
		columns are on, with the MAP line, a long cup title and an over-long nickname --
		so one //ko hud shows whether anything clips at 46 wide."""
		self.match_text = 'FRIDAY KNOCKOUT CUP'
		self.round_text = '12/21'
		self.map_text = '2 of 3'
		self.show_map = True
		self.players_count = 4
		self.show_season = True
		self.title_textsize = title_textsize(self.match_text, TITLE_TEXT_W)
		self.rows = [
			# Row 1 carries the worst-case absolute time; row 2 the worst-case nickname.
			dict(gap=False, danger=False, rank=1, name='Test A', time='1:01.470',
				name_color=WHITE, time_color=GREEN, season_points=12),
			dict(gap=False, danger=False, rank=2, name='TestPlayerWithALongName', time='+0.031',
				name_color=WHITE, time_color=GREEN, season_points=9),
			dict(gap=False, danger=False, rank=3, name='Test C', time='+0.250',
				name_color=WHITE, time_color=GREEN, season_points=7),
			dict(gap=False, danger=True, rank=4, name='Test D', time='+0.500',
				name_color=WHITE, time_color=RED, season_points=5),
		]
		self._layout(self.rows)
		# Placeholder rows are not what the live board would compute, so leave the
		# dedupe with no opinion: the next real refresh must repaint over them.
		self._sent = _UNKNOWN
		# player_logins, not player: TemplateView.display swallows an unknown `player`
		# kwarg and shows the manialink to everyone -- which made this "you only"
		# diagnostic render on every client on the server.
		login = getattr(player, 'login', None)
		if login:
			await self.display(player_logins=[login])
		else:
			await self.display()

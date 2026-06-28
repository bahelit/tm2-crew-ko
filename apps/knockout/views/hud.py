from pyplanet.views.template import TemplateView

from ..hud_format import (
	format_race_time, format_gap, match_label, round_value, ko_per_round_label,
	ml_num,
)

# Layout mirrors the BOTN countdown: a title tab (TITLE_H) then a body panel.
# Stats sit just under the tab; player rows follow. All geometry is precomputed
# here so the template never does float arithmetic.
TITLE_H = 7
STATS_Y = (-9, -13, -17)   # ROUND, PLAYERS, KOS PER ROUND
START_Y = -22
ROW_H = 4

# When more players are listed than MAX_ROWS, the middle is collapsed to a single
# "…" marker: the top HEAD_ROWS and the trailing rows (which include the danger
# zone) are kept so the leaders and the elimination bubble are always visible.
HEAD_ROWS = 4
MAX_ROWS = 16

# Per-cell colours.
WHITE = 'FFFFFF'      # rank + name (clan-tag $codes colour the names themselves)
RED = 'FF3333'        # times in the danger zone (about to be eliminated)
GREEN = '66FF66'      # safe times: the leader's absolute time and the gaps behind it
BUBBLE = 'FFCC00'     # the last safe time, one spot above the cut line
DIM = 'AAAAAA'        # no time yet / gap marker

# Title shown in place of "MATCH n" when the live event is a Bowl of the Night.
BOTN_TITLE = 'BOWL OF THE NIGHT'


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
		self.players_count = 0
		self.ko_text = '1'
		self.rows = []
		self.has_divider = False
		self.divider_y = 0.0
		self.show_season = False
		self.title_textsize = '2'

	async def get_context_data(self):
		data = await super().get_context_data()
		data['match_text'] = self.match_text
		data['round_text'] = self.round_text
		data['players_count'] = self.players_count
		data['ko_text'] = self.ko_text
		data['rows'] = self.rows
		data['has_divider'] = self.has_divider
		data['divider_y'] = ml_num(self.divider_y)
		data['title_h'] = ml_num(TITLE_H)
		data['stats_y'] = [ml_num(y) for y in STATS_Y]
		# Season column: widen the panel and shift the time column left to make room
		# for a right-hand points column. All geometry is precomputed here so the
		# template stays arithmetic-free.
		data['show_season'] = self.show_season
		bg_width = 64 if self.show_season else 54
		body_height = 15 + len(self.rows) * ROW_H
		data['bg_width'] = ml_num(bg_width)
		data['body_height'] = ml_num(body_height)
		data['title_w'] = ml_num(bg_width - 4)
		data['center_x'] = ml_num(bg_width / 2)
		data['header_val_x'] = ml_num(bg_width - 2)
		data['divider_w'] = ml_num(bg_width - 4)
		data['time_x'] = ml_num(50 if self.show_season else 52)
		data['pts_x'] = ml_num(62)
		data['title_textsize'] = self.title_textsize
		return data

	async def refresh(self, live):
		"""Pull the current picture from the LiveController and (re)display. The HUD
		stays up for the whole Knockout: during warm-up it lists the players on the
		server with their best lap so far; once rounds start it switches to the live
		running order with elimination highlighting. It only hides when the loaded
		mode is not Knockout, or when nobody is on the server to show."""
		if not getattr(live, 'is_knockout', True):
			await self.hide()
			return

		if getattr(live, 'is_botn', False):
			self.match_text = BOTN_TITLE
			# Long title needs a smaller font so it fits the tab without bleeding
			# into the stats block below.
			self.title_textsize = '1.5'
		else:
			self.match_text = match_label(getattr(live, 'match_number', 0))
			self.title_textsize = '2'
		self.round_text = round_value(getattr(live, 'round', 0), getattr(live, 'total_rounds', 0))
		danger = set(live.danger_logins())

		# Points column (running cup total) shows whenever a cup is active and the
		# setting is on -- from map 1, with zeros, before any map is recorded.
		season = getattr(live, 'season_points', None) or {}
		cup_active = getattr(live, 'cup_active', False)
		try:
			show_season = cup_active and await self.app.setting_show_season_points.get_value()
		except Exception:
			show_season = False
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
		self.ko_text = ko_per_round_label(getattr(live, '_double_until', 0), len(entries))

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
				name=await self._name(login),
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
		await self.display()

	# ------------------------------------------------------------- helpers

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
		for index, row in enumerate(rows):
			row['y'] = ml_num(START_Y - index * ROW_H)
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
		only to ``player`` when given, otherwise to everyone (the real path)."""
		self.match_text = 'MATCH 30'
		self.round_text = '12/21'
		self.players_count = 4
		self.ko_text = '2 UNTIL 8 PLAYERS'
		self.show_season = False
		self.title_textsize = '2'
		self.rows = [
			dict(gap=False, danger=False, rank=1, name='Test A', time='12.470', name_color=WHITE, time_color=GREEN),
			dict(gap=False, danger=False, rank=2, name='Test B', time='+0.031', name_color=WHITE, time_color=GREEN),
			dict(gap=False, danger=False, rank=3, name='Test C', time='+0.250', name_color=WHITE, time_color=GREEN),
			dict(gap=False, danger=True, rank=4, name='Test D', time='+0.500', name_color=WHITE, time_color=RED),
		]
		self._layout(self.rows)
		if player is not None:
			await self.display(player=player)
		else:
			await self.display()

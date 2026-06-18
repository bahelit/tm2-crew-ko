from pyplanet.views.template import TemplateView

from ..hud_format import (
	format_race_time, format_gap, match_label, round_value, ko_per_round_label,
)

# Where the first player row sits below the frame top, and the height of each
# row. The header block (title + ROUND/PLAYERS/KOS + divider) fills the space
# above START_Y. Kept in the view so the template never does float arithmetic.
START_Y = -21.0
ROW_H = 4.0

# When more players are listed than MAX_ROWS, the middle is collapsed to a single
# "…" marker: the top HEAD_ROWS and the trailing rows (which include the danger
# zone) are kept so the leaders and the elimination bubble are always visible.
HEAD_ROWS = 4
MAX_ROWS = 16

# Per-cell colours.
WHITE = 'FFFFFF'
RED = 'FF3333'        # on the elimination bubble
GREEN = '66FF66'      # safe gap behind the leader
LEADER = '33DDFF'     # the leader's absolute time
DIM = 'AAAAAA'        # no time yet / gap marker


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

	async def get_context_data(self):
		data = await super().get_context_data()
		data['match_text'] = self.match_text
		data['round_text'] = self.round_text
		data['players_count'] = self.players_count
		data['ko_text'] = self.ko_text
		data['rows'] = self.rows
		data['has_divider'] = self.has_divider
		data['divider_y'] = self.divider_y
		# Background height is precomputed so the template never does float math.
		data['bg_height'] = 22.0 + len(self.rows) * ROW_H
		# Season column: widen the panel and shift the time column left to make room
		# for a right-hand points column. All geometry is precomputed here so the
		# template stays arithmetic-free.
		data['show_season'] = self.show_season
		bg_width = 64.0 if self.show_season else 54.0
		data['bg_width'] = bg_width
		data['center_x'] = bg_width / 2.0
		data['header_val_x'] = bg_width - 2.0
		data['divider_w'] = bg_width - 4.0
		data['time_x'] = 50.0 if self.show_season else 52.0
		data['pts_x'] = 62.0
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

		self.match_text = match_label(getattr(live, 'match_number', 0))
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
				time_text, time_color = format_race_time(ms), LEADER
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
				name_color=RED if is_danger else WHITE,
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
		"""Assign each row its y position and find the divider above the first
		danger row (red name)."""
		self.has_divider = False
		self.divider_y = 0.0
		for index, row in enumerate(rows):
			row['y'] = START_Y - index * ROW_H
			if not self.has_divider and not row.get('gap') and row.get('name_color') == RED:
				self.has_divider = True
				self.divider_y = row['y'] + 0.6

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
		self.rows = [
			dict(gap=False, danger=False, rank=1, name='Test A', time='12.470', name_color=WHITE, time_color=LEADER),
			dict(gap=False, danger=False, rank=2, name='Test B', time='+0.031', name_color=WHITE, time_color=GREEN),
			dict(gap=False, danger=False, rank=3, name='Test C', time='+0.250', name_color=WHITE, time_color=GREEN),
			dict(gap=False, danger=True, rank=4, name='Test D', time='+0.500', name_color=RED, time_color=RED),
		]
		self._layout(self.rows)
		if player is not None:
			await self.display(player=player)
		else:
			await self.display()

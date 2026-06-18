"""
Pure (pyplanet-free) helpers for the live Knockout match HUD, kept in their own
module so they can be unit-tested without pyplanet installed. The view that uses
them lives in views/hud.py.
"""


def format_race_time(ms):
	"""Format a race time in milliseconds as ``M:SS.mmm`` (or ``S.mmm`` under a
	minute). Returns an em dash for an unset/negative time (player still racing)."""
	try:
		ms = int(ms)
	except (TypeError, ValueError):
		return '—'
	if ms < 0:
		return '—'
	minutes, rem = divmod(ms, 60000)
	seconds, millis = divmod(rem, 1000)
	if minutes:
		return '{}:{:02d}.{:03d}'.format(minutes, seconds, millis)
	return '{}.{:03d}'.format(seconds, millis)


def format_gap(ms):
	"""Format a positive gap to the leader (in milliseconds) as ``+S.mmm`` (or
	``+M:SS.mmm`` past a minute). Returns an em dash for an unset/negative gap."""
	try:
		ms = int(ms)
	except (TypeError, ValueError):
		return '—'
	if ms < 0:
		return '—'
	minutes, rem = divmod(ms, 60000)
	seconds, millis = divmod(rem, 1000)
	if minutes:
		return '+{}:{:02d}.{:03d}'.format(minutes, seconds, millis)
	return '+{}.{:03d}'.format(seconds, millis)


def row_color(danger, finished):
	"""Text colour for a HUD row: red on the elimination bubble, green once the
	player has safely finished, white otherwise."""
	if danger:
		return 'FF3333'
	if finished:
		return '66FF66'
	return 'FFFFFF'


def round_label(round_no, total):
	"""Build the HUD header: ``ROUND x / y`` (the total is dropped when the map is
	unbounded, i.e. total <= 0). Falls back to ``KNOCKOUT`` before round 1."""
	try:
		round_no = int(round_no)
	except (TypeError, ValueError):
		round_no = 0
	if round_no <= 0:
		return 'KNOCKOUT'
	try:
		total = int(total)
	except (TypeError, ValueError):
		total = 0
	if total > 0:
		return 'ROUND {} / {}'.format(round_no, total)
	return 'ROUND {}'.format(round_no)


def match_label(match_number):
	"""Title line for the HUD: ``MATCH n`` (1-based), or ``KNOCKOUT`` when the
	match number is unknown (e.g. before the database has been consulted)."""
	try:
		n = int(match_number)
	except (TypeError, ValueError):
		n = 0
	if n > 0:
		return 'MATCH {}'.format(n)
	return 'KNOCKOUT'


def round_value(round_no, total):
	"""Right-hand value for the HUD's ``ROUND`` line: ``x/y`` (or just ``x`` when
	the map is unbounded). An em dash before the first round starts."""
	try:
		round_no = int(round_no)
	except (TypeError, ValueError):
		round_no = 0
	if round_no <= 0:
		return '—'
	try:
		total = int(total)
	except (TypeError, ValueError):
		total = 0
	if total > 0:
		return '{}/{}'.format(round_no, total)
	return str(round_no)


def ko_per_round_label(double_until, players):
	"""Right-hand value for the HUD's ``KOS PER ROUND`` line. With double-knockout
	configured (``double_until`` > 0) and more than that many players still in, the
	mode knocks out two each round until the field shrinks to ``double_until``; at
	or below that threshold it is one."""
	try:
		double_until = int(double_until)
	except (TypeError, ValueError):
		double_until = 0
	try:
		players = int(players)
	except (TypeError, ValueError):
		players = 0
	if double_until and players > double_until:
		return '2 UNTIL {} PLAYERS'.format(double_until)
	return '1'

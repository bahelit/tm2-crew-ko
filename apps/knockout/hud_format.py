"""
Pure (pyplanet-free) helpers for the live Knockout match HUD, kept in their own
module so they can be unit-tested without pyplanet installed. The view that uses
them lives in views/hud.py.
"""


def ml_num(value):
	"""Format a number for ManiaLink ``pos``/``size`` attributes.

	Jinja renders Python floats with a trailing ``.0`` (e.g. ``64.0``). In the
	``W. H.`` size syntax that produces ``64.0. 38.0.`` -- three dots -- which
	the client treats as invalid and the quad never draws. Whole values are
	emitted as integers so templates can safely write ``{{ w }}. {{ h }}.``."""
	try:
		f = float(value)
	except (TypeError, ValueError):
		return 0
	if f == int(f):
		return int(f)
	return f


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


def split_cp_label(cp_count, is_end_race):
	"""Label for a checkpoint crossing in the splits feed: ``FIN`` at the finish
	line, otherwise ``CP n`` (1-based, the number of checkpoints crossed so far)."""
	if is_end_race:
		return 'FIN'
	try:
		n = int(cp_count)
	except (TypeError, ValueError):
		n = 0
	if n <= 0:
		return 'CP'
	return 'CP {}'.format(n)


def waypoint_cp_count(race_cps=None, raw=None, **_kwargs):
	"""Checkpoint ordinal for the splits feed from a PyPlanet waypoint event.

	Intermediate ``trackmania:waypoint`` callbacks only expose ``player``,
	``race_time``, ``flow``, and ``raw`` — not ``race_cps``. Finish events carry
	``race_cps`` / ``cps`` on the custom ``finish`` signal instead. Prefer an
	explicit list length, then ManiaPlanet raw fields (``checkpointinrace`` or
	the length of ``curracecheckpoints``). Returns 0 when unknown.
	"""
	for candidate in (race_cps, _kwargs.get('cps'), _kwargs.get('lap_cps')):
		try:
			if candidate is not None:
				n = len(candidate)
				if n > 0:
					return n
		except TypeError:
			pass

	if isinstance(raw, dict):
		for key in ('checkpointinrace', 'checkpointinlap', 'CheckpointInRace', 'CheckpointInLap'):
			if key in raw and raw[key] is not None:
				try:
					n = int(raw[key])
				except (TypeError, ValueError):
					n = 0
				if n > 0:
					return n
		for key in ('curracecheckpoints', 'curlapcheckpoints', 'CurRaceCheckpoints', 'CurLapCheckpoints'):
			try:
				seq = raw.get(key)
				if seq is not None:
					n = len(seq)
					if n > 0:
						return n
			except TypeError:
				pass
	return 0


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


def hud_applies(is_knockout, cup_active):
	"""Whether the match HUD should be shown: always during Knockout, and also
	during an active cup's TimeAttack phases (BOTN practice, between maps)."""
	return bool(is_knockout) or bool(cup_active)


def is_practice_phase(is_knockout, cup_active, botn_active=False, botn_phase='idle'):
	"""True during cup/BOTN practice (TimeAttack) before the knockout is live."""
	if is_knockout:
		return False
	if botn_active and botn_phase in ('practice', 'countdown'):
		return True
	return bool(cup_active)


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


# Font-safe shield marker (U+271A). The shield emoji does not render in ManiaPlanet.
SHIELD_MARK = '✚'


def format_hud_name(name, has_shield=False):
	"""Player name as shown on a match-HUD row. When ``has_shield`` is true, append
	a compact ✚ so everyone can see who still holds a one-time save."""
	text = name if name is not None else ''
	if has_shield:
		if text:
			return '{} {}'.format(text, SHIELD_MARK)
		return SHIELD_MARK
	return text

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


# Rows the bottom splits standings board shows. The panel is 6 rows tall (see
# templates/splits.xml for the geometry that fixes that number).
SPLITS_ROWS = 6


def split_rank_key(row):
	"""Sort key for the splits standings board: furthest checkpoint first, then the
	fastest time at that checkpoint, then arrival order.

	``seq`` is a monotonic crossing counter, used as the tie-break instead of the login
	so that two players who reach the same checkpoint on the same millisecond are ranked
	by who got there first. More importantly it makes the ordering TOTAL and stable: a
	row can only change position when another player's ``(cp, ms)`` genuinely crosses
	it -- i.e. on a real overtake -- never because someone else merely crossed a
	checkpoint. That is the whole point of the board (it replaced a rolling feed where
	every crossing shoved every name down a row).

	Finishers need no special case: a finish's ordinal is one past the last checkpoint,
	so ``-cp`` already pins them above everyone still on track, and a finisher can only
	be displaced by a faster finisher.
	"""
	def _int(key):
		try:
			return int(row.get(key, 0) or 0)
		except (TypeError, ValueError):
			return 0
	return (-_int('cp'), _int('ms'), _int('seq'))


def order_split_rows(rows, racing=None, limit=SPLITS_ROWS):
	"""Ordered, filtered and truncated standings for the splits panel.

	``racing`` (when non-empty) drops players who are no longer in the knockout, so an
	eliminated or departed driver's last checkpoint does not sit on the board into the
	next round. An empty/None ``racing`` shows everyone, which keeps the panel working
	before any KO roster callback has arrived (e.g. the controller reloaded mid-map).
	"""
	live = set(racing or ())
	ordered = [row for row in rows if not live or row.get('login') in live]
	ordered.sort(key=split_rank_key)
	if limit:
		return ordered[:limit]
	return ordered


# The row fields the splits template actually draws. Everything else a row carries
# (login, cp, ms, finished, seq) is ordering bookkeeping -- and ``seq`` in particular
# is a counter that changes on EVERY crossing by design, so signing over it would make
# every signature unique and defeat the point.
SPLIT_RENDERED_FIELDS = ('y', 'name', 'cp_label', 'split', 'color')


def split_row_signature(rows):
	"""A hashable summary of exactly what the splits panel would draw for ``rows``.

	Two row lists with the same signature render byte-identical ManiaLink, so the
	board can skip re-displaying. That matters because the panel is truncated to
	``SPLITS_ROWS``: on a full server most checkpoint crossings are by players who are
	not on the board at all, and each one used to cost every client a full ManiaLink
	page replacement -- and the layout hitch that comes with it -- to redraw the same
	six rows.
	"""
	return tuple(
		tuple(row.get(field) for field in SPLIT_RENDERED_FIELDS)
		for row in rows
	)


# What the match-HUD template actually draws, split the way the view stores it: panel
# state read off the view, and per-row cells read out of each row dict.
#
# Read the template before touching either tuple -- a field it draws but this does not
# cover is a repaint the HUD will wrongly skip, which shows up in game as a board that
# stops updating rather than as an error. Two known-deliberate omissions:
#   * ``danger`` is not here. It is not drawn: it only decides ``time_color`` and where
#     the divider goes, and both of those ARE covered.
#   * every geometry value (column x/width, body height, stat line y) is derived from
#     module constants plus show_map / show_season / players_count / len(rows), so the
#     fields below already pin them.
HUD_RENDERED_PANEL_FIELDS = (
	'match_text', 'title_textsize', 'round_text', 'map_text', 'show_map',
	'players_count', 'show_season', 'has_divider', 'divider_y',
)
HUD_RENDERED_ROW_FIELDS = (
	'gap', 'y', 'rank', 'name', 'time', 'name_color', 'time_color', 'season_points',
)


def hud_render_signature(view, rows):
	"""A hashable summary of exactly what the match HUD would draw.

	``view`` is anything carrying the panel attributes (the MatchHud itself in
	production, a stand-in in the tests). Same job as split_row_signature: the HUD is
	repainted from KORoundOrder and from every best-lap improvement, and most of those
	leave the board looking identical -- a checkpoint that does not change the running
	order, a finish that does not beat anyone. Each one still cost every client a full
	ManiaLink page replacement.
	"""
	panel = tuple(getattr(view, field, None) for field in HUD_RENDERED_PANEL_FIELDS)
	body = tuple(
		tuple(row.get(field) for field in HUD_RENDERED_ROW_FIELDS)
		for row in rows
	)
	return (panel, body)


# What the stream ticker's template branches on and draws. ``_practice`` is private on
# the view but get_context_data reads it the same way, so it is signed the same way.
# ``danger_rows`` is not here: the template derives each row's y from its index, so the
# names alone pin it.
TICKER_RENDERED_FIELDS = (
	'showdown', '_practice', 'count', 'racing_names', 'danger_names',
)


def ticker_render_signature(view):
	"""A hashable summary of exactly what the stream ticker would draw.

	Sequences are frozen to tuples so the signature survives the view mutating its own
	lists in place, and so it stays hashable. Note this covers the CONTENT only --
	push_stream_view folds the audience in on top, because the ticker goes to a target
	set (spectators plus /ko stream opt-ins) that changes without the content changing.
	"""
	values = []
	for field in TICKER_RENDERED_FIELDS:
		value = getattr(view, field, None)
		if isinstance(value, (list, tuple, set)):
			value = tuple(value)
		values.append(value)
	return tuple(values)


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


def describe_payload(value, max_keys=6):
	"""Compact description of a callback payload field for the ``//ko splits``
	diagnostic: a list becomes ``list[3]``, a dict its first few keys, anything else
	its type name. Keeps a chat line readable while still showing what arrived."""
	if isinstance(value, dict):
		keys = sorted(value)[:max_keys]
		return 'dict{{{}}}'.format(','.join(keys)) if keys else 'dict{}'
	if isinstance(value, (list, tuple)):
		return '{}[{}]'.format(type(value).__name__, len(value))
	if value is None:
		return 'None'
	return type(value).__name__


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


# Worst-case glyph width per character for the HUD's title tab, per textsize tier
# (uppercase GameFontBlack, with a small margin over the width measured from the
# BOTN countdown header: "PRACTICE ENDS IN" -- 16 chars -- fits a 44-unit label at
# textsize 2, i.e. about 2.75 units a character).
TITLE_TIERS = (('2', 2.9), ('1.5', 2.2), ('1', 1.5))


def title_textsize(text, width):
	"""Font tier for the HUD's title tab: the largest size whose worst-case width
	still fits ``width`` units. Labels clip at their box rather than shrinking, and
	an over-long title wraps down into the stats block, so this has to be picked up
	front. At the panel's 42-unit tab: ``'2'`` up to 14 characters, ``'1.5'`` to 19,
	``'1'`` beyond -- which keeps "BOWL OF THE NIGHT" and the 19-character preset cup
	names ("FRIDAY KNOCKOUT CUP") on the middle tier."""
	n = len(text or '')
	if n <= 0:
		return '2'
	for size, char_w in TITLE_TIERS:
		if n * char_w <= width:
			return size
	return '1'


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


def cup_map_value(maps_played, map_count):
	"""Right-hand value for the HUD's ``MAP`` line while a cup runs: ``2 of 3``.

	``maps_played`` counts the maps already *recorded*, so the one being played now
	is the next one up. Open-ended cups (map_count 0) show a bare map number. The
	current map is clamped to the target so the last map cannot briefly read
	``4 of 3`` in the window between its standings landing and the cup completing."""
	try:
		played = max(0, int(maps_played))
	except (TypeError, ValueError):
		played = 0
	try:
		total = int(map_count)
	except (TypeError, ValueError):
		total = 0
	current = played + 1
	if total > 0:
		return '{} of {}'.format(min(current, total), total)
	return str(current)


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


# Font-safe shield marker. Keep this ASCII: the ManiaPlanet game fonts carry Latin-1
# and little else, so the shield emoji (U+1F6E1) and the Dingbats cross (U+271A) both
# drew as an empty box on the HUD.
SHIELD_MARK = '+'

# Most shields we will ever draw on a name, and the default bank cap. Matches the mode's
# S_MaxShields default; the live cap is read from the mode at map start.
MAX_SHIELD_MARKS = 3


def format_hud_name(name, has_shield=False, shields=None):
	"""Player name as shown on a match-HUD row, with one ``+`` per banked shield (capped
	at MAX_SHIELD_MARKS): ``[TM2C]ogiewan +++``. Shields stack and carry across the
	maps of a cup, so the count matters, not just the fact of holding one.

	``shields`` is the count. ``has_shield`` is the pre-stacking boolean and is kept as
	a legacy alias meaning "one shield"; it is only consulted when ``shields`` is None.
	"""
	text = name if name is not None else ''
	if shields is None:
		shields = 1 if has_shield else 0
	try:
		count = int(shields)
	except (TypeError, ValueError):
		count = 0
	count = max(0, min(count, MAX_SHIELD_MARKS))
	if not count:
		return text
	marks = SHIELD_MARK * count
	if text:
		return '{} {}'.format(text, marks)
	return marks


def apply_shield_delta(counts, login, delta, cap=MAX_SHIELD_MARKS):
	"""Optimistically apply a single-login KOShieldAwarded/KOShieldUsed to the bank.

	KOShieldState carries the authoritative counts, but it arrives just *after* the
	single-login callback that caused it (and could in principle be dropped), so the
	controller folds the delta in as it lands and lets the state callback overwrite.
	Returns a NEW dict clamped to ``[0, cap]``, with logins at zero removed -- the same
	"only holders are stored" invariant the mode keeps.
	"""
	updated = dict(counts or {})
	if not login:
		return updated
	try:
		cap = int(cap)
	except (TypeError, ValueError):
		cap = MAX_SHIELD_MARKS
	if cap < 0:
		cap = 0
	current = updated.get(login, 0)
	try:
		current = int(current)
	except (TypeError, ValueError):
		current = 0
	new = max(0, min(current + int(delta), cap))
	if new <= 0:
		updated.pop(login, None)
	else:
		updated[login] = new
	return updated

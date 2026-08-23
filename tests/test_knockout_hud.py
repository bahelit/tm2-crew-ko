"""
Unit tests for the pure (pyplanet-free) Knockout match-HUD helpers in
apps/knockout/hud_format.py. Loaded by path so they run without pyplanet.

Run with:  python -m pytest tests/test_knockout_hud.py
       or:  python tests/test_knockout_hud.py
"""
import importlib.util
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_KO = os.path.join(_HERE, '..', 'apps', 'knockout')


def _load(name, filename):
	spec = importlib.util.spec_from_file_location(name, os.path.join(_KO, filename))
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


hud = _load('ko_hud_format', 'hud_format.py')


# --------------------------------------------------------------- race times

def test_format_race_time_under_a_minute():
	assert hud.format_race_time(42123) == '42.123'
	assert hud.format_race_time(0) == '0.000'
	assert hud.format_race_time(5) == '0.005'


def test_format_race_time_over_a_minute():
	assert hud.format_race_time(61000) == '1:01.000'
	assert hud.format_race_time(125678) == '2:05.678'


def test_format_race_time_unset_is_dash():
	assert hud.format_race_time(-1) == '—'
	assert hud.format_race_time(None) == '—'
	assert hud.format_race_time('nope') == '—'


# --------------------------------------------------------------- gap times

def test_format_gap_under_a_minute():
	assert hud.format_gap(31) == '+0.031'
	assert hud.format_gap(448) == '+0.448'
	assert hud.format_gap(0) == '+0.000'


def test_format_gap_over_a_minute():
	assert hud.format_gap(61000) == '+1:01.000'


def test_format_gap_unset_is_dash():
	assert hud.format_gap(-1) == '—'
	assert hud.format_gap(None) == '—'
	assert hud.format_gap('nope') == '—'


# --------------------------------------------------------------- row colours

def test_row_color_priority():
	# Danger wins even if the player has finished (they are still on the bubble).
	assert hud.row_color(True, True) == 'FF3333'
	assert hud.row_color(True, False) == 'FF3333'
	assert hud.row_color(False, True) == '66FF66'
	assert hud.row_color(False, False) == 'FFFFFF'


# --------------------------------------------------------------- round label

def test_round_label_bounded_and_unbounded():
	assert hud.round_label(3, 5) == 'ROUND 3 / 5'
	assert hud.round_label(3, 0) == 'ROUND 3'
	assert hud.round_label(1, 1) == 'ROUND 1 / 1'


def test_round_label_before_first_round():
	assert hud.round_label(0, 5) == 'KNOCKOUT'
	assert hud.round_label('x', 5) == 'KNOCKOUT'


# --------------------------------------------------------- header values

def test_match_label():
	assert hud.match_label(30) == 'MATCH 30'
	assert hud.match_label(1) == 'MATCH 1'
	assert hud.match_label(0) == 'KNOCKOUT'
	assert hud.match_label(None) == 'KNOCKOUT'


def test_round_value():
	assert hud.round_value(12, 21) == '12/21'
	assert hud.round_value(3, 0) == '3'
	assert hud.round_value(0, 21) == '—'
	assert hud.round_value('x', 5) == '—'


def test_cup_map_value():
	# maps_played counts RECORDED maps, so the one being raced is the next one.
	assert hud.cup_map_value(0, 3) == '1 of 3'
	assert hud.cup_map_value(1, 3) == '2 of 3'
	# Open-ended cup: no target to count towards.
	assert hud.cup_map_value(2, 0) == '3'
	# Between the last map's standings landing and the cup completing, played
	# already equals the target -- never show "4 of 3".
	assert hud.cup_map_value(3, 3) == '3 of 3'
	assert hud.cup_map_value(None, None) == '1'
	assert hud.cup_map_value('x', 3) == '1 of 3'


def test_title_textsize_tiers():
	# The panel's title tab is 42 units wide (bg_width 46 less a 2-unit inset each
	# side). Short titles keep the big font; the long ones step down rather than
	# wrapping into the stats block below.
	assert hud.title_textsize('MATCH 30', 42) == '2'
	assert hud.title_textsize('QUICK KNOCKOUT', 42) == '2'          # 14 chars, the boundary
	assert hud.title_textsize('BOWL OF THE NIGHT', 42) == '1.5'     # 17 -- unchanged from before
	assert hud.title_textsize('FRIDAY KNOCKOUT CUP', 42) == '1.5'   # 19, a shipped preset name
	assert hud.title_textsize('A' * 20, 42) == '1'
	# No title yet / empty: the big font, not a crash.
	assert hud.title_textsize('', 42) == '2'
	assert hud.title_textsize(None, 42) == '2'


def test_ml_num_avoids_broken_size_syntax():
	# Jinja would render 64.0 as "64.0", producing size="64.0. 38.0." (invalid).
	assert hud.ml_num(64.0) == 64
	assert hud.ml_num(38.0) == 38
	assert hud.ml_num(-21.0) == -21
	assert hud.ml_num(27.5) == 27.5


def test_hud_applies():
	assert hud.hud_applies(True, False) is True
	assert hud.hud_applies(False, True) is True
	assert hud.hud_applies(False, False) is False


def test_is_practice_phase():
	assert hud.is_practice_phase(False, True) is True
	assert hud.is_practice_phase(True, True) is False
	assert hud.is_practice_phase(False, False, botn_active=True, botn_phase='practice') is True
	assert hud.is_practice_phase(False, False, botn_active=True, botn_phase='knockout') is False
	assert hud.is_practice_phase(False, True, botn_active=True, botn_phase='countdown') is True


def test_format_hud_name_shield_marker():
	# The pre-stacking boolean is kept as a legacy alias meaning "one shield".
	assert hud.format_hud_name('Alice', has_shield=False) == 'Alice'
	assert hud.format_hud_name('Alice', has_shield=True) == 'Alice ✚'
	assert hud.format_hud_name('', has_shield=True) == '✚'
	assert hud.format_hud_name(None, has_shield=False) == ''


def test_format_hud_name_repeats_the_mark_per_banked_shield():
	assert hud.format_hud_name('Alice', shields=0) == 'Alice'
	assert hud.format_hud_name('Alice', shields=1) == 'Alice ✚'
	assert hud.format_hud_name('Alice', shields=2) == 'Alice ✚✚'
	assert hud.format_hud_name('Alice', shields=3) == 'Alice ✚✚✚'


def test_format_hud_name_clamps_the_shield_count():
	# The mode caps at S_MaxShields, but the HUD must not draw a name off the row
	# if that setting is ever raised past what the column can hold.
	assert hud.format_hud_name('Alice', shields=5) == 'Alice ✚✚✚'
	assert hud.format_hud_name('Alice', shields=-1) == 'Alice'
	assert hud.format_hud_name('Alice', shields='abc') == 'Alice'


def test_format_hud_name_count_wins_over_the_legacy_flag():
	assert hud.format_hud_name('Alice', has_shield=True, shields=0) == 'Alice'
	assert hud.format_hud_name('Alice', has_shield=False, shields=2) == 'Alice ✚✚'


# --------------------------------------------------------- shield bank deltas

def test_apply_shield_delta_increments_and_clamps_at_the_cap():
	assert hud.apply_shield_delta({}, 'alice', 1) == {'alice': 1}
	assert hud.apply_shield_delta({'alice': 2}, 'alice', 1) == {'alice': 3}
	assert hud.apply_shield_delta({'alice': 3}, 'alice', 1, cap=3) == {'alice': 3}
	assert hud.apply_shield_delta({'alice': 1}, 'alice', 1, cap=1) == {'alice': 1}


def test_apply_shield_delta_drops_a_login_at_zero():
	# Mirrors the mode's invariant: only holders are stored, so the HUD never has to
	# distinguish "zero shields" from "not in the bank".
	assert hud.apply_shield_delta({'alice': 1}, 'alice', -1) == {}
	assert hud.apply_shield_delta({'alice': 2}, 'alice', -1) == {'alice': 1}
	assert hud.apply_shield_delta({'alice': 1}, 'bob', -1) == {'alice': 1}
	assert hud.apply_shield_delta({}, 'alice', -1) == {}


def test_apply_shield_delta_does_not_mutate_its_input():
	before = {'alice': 1}
	after = hud.apply_shield_delta(before, 'alice', 1)
	assert before == {'alice': 1}
	assert after == {'alice': 2}


def test_apply_shield_delta_ignores_an_empty_login():
	assert hud.apply_shield_delta({'alice': 1}, '', 1) == {'alice': 1}


# --------------------------------------------------------- waypoint CP count

def test_waypoint_cp_count_from_race_cps_list():
	assert hud.waypoint_cp_count(race_cps=[100, 200, 300]) == 3
	assert hud.waypoint_cp_count(race_cps=[]) == 0
	assert hud.waypoint_cp_count(race_cps=None) == 0


def test_waypoint_cp_count_from_raw_checkpointinrace():
	# PyPlanet intermediate waypoints only pass raw — no race_cps.
	assert hud.waypoint_cp_count(raw={'checkpointinrace': 2, 'racetime': 12000}) == 2
	assert hud.waypoint_cp_count(raw={'CheckpointInRace': 4}) == 4


def test_waypoint_cp_count_from_raw_checkpoint_list():
	assert hud.waypoint_cp_count(raw={'curracecheckpoints': [1, 2, 3, 4]}) == 4
	assert hud.waypoint_cp_count(raw={'curlapcheckpoints': [10, 20]}) == 2


def test_waypoint_cp_count_prefers_explicit_list_over_raw():
	assert hud.waypoint_cp_count(
		race_cps=[1, 2],
		raw={'checkpointinrace': 9},
	) == 2


def test_waypoint_cp_count_empty_when_unknown():
	assert hud.waypoint_cp_count() == 0
	assert hud.waypoint_cp_count(raw={}) == 0
	assert hud.waypoint_cp_count(raw={'checkpointinrace': 0}) == 0


if __name__ == '__main__':
	import sys
	import traceback

	failures = 0
	for name, fn in sorted(globals().items()):
		if name.startswith('test_') and callable(fn):
			try:
				fn()
				print('ok   ', name)
			except Exception:
				failures += 1
				print('FAIL ', name)
				traceback.print_exc()
	sys.exit(1 if failures else 0)


# ------------------------------------------------------------- repaint dedupe
# MatchHud is repainted from every KORoundOrder and every best-lap improvement --
# dozens of times a round, most leaving the board identical -- and each repaint used
# to broadcast a full ManiaLink page to every client. hud_render_signature is what
# lets the view drop the no-op ones. If it stops covering something the template
# draws, the HUD quietly freezes instead of erroring, so these guard the coverage
# rather than just the happy path.


def _template_row_fields(name):
	"""Every ``row.<field>`` the given template dereferences."""
	path = os.path.join(_KO, 'templates', name)
	with open(path, 'r', encoding='utf-8') as handle:
		return set(re.findall(r'\brow\.([a-z_]+)', handle.read()))


class _Panel:
	"""Stand-in for the MatchHud attributes the signature reads."""

	def __init__(self, **kwargs):
		defaults = dict(
			match_text='MATCH 3', title_textsize='2', round_text='4/12', map_text='',
			show_map=False, players_count=8, show_season=False,
			has_divider=False, divider_y=0)
		defaults.update(kwargs)
		for key, value in defaults.items():
			setattr(self, key, value)


def _hud_row(**kwargs):
	row = dict(
		gap=False, y='-18', rank=1, name='Alice', time='42.123',
		name_color='FFFFFF', time_color='66FF66', season_points=None)
	row.update(kwargs)
	return row


def test_hud_signature_covers_every_row_field_the_template_draws():
	drawn = _template_row_fields('hud.xml')
	assert drawn, 'no row.<field> found -- did hud.xml move or change syntax?'
	missing = drawn - set(hud.HUD_RENDERED_ROW_FIELDS)
	assert not missing, 'hud.xml draws row fields the dedupe ignores: {}'.format(
		sorted(missing))


def test_hud_signature_reacts_to_every_row_field():
	panel = _Panel()
	base = _hud_row()
	for field, other in (
		('gap', True), ('y', '-22'), ('rank', 2), ('name', 'Bob'), ('time', '+0.031'),
		('name_color', 'FF3333'), ('time_color', 'FFCC00'), ('season_points', 7),
	):
		changed = dict(base, **{field: other})
		assert (hud.hud_render_signature(panel, [base])
			!= hud.hud_render_signature(panel, [changed])), field


def test_hud_signature_reacts_to_every_panel_field():
	base = _Panel()
	rows = [_hud_row()]
	for field, other in (
		('match_text', 'FRIDAY CUP'), ('title_textsize', '1'), ('round_text', '5/12'),
		('map_text', '2 of 3'), ('show_map', True), ('players_count', 7),
		('show_season', True), ('has_divider', True), ('divider_y', '-20'),
	):
		changed = _Panel(**{field: other})
		assert (hud.hud_render_signature(base, rows)
			!= hud.hud_render_signature(changed, rows)), field


def test_hud_signature_ignores_danger_which_is_not_drawn():
	# `danger` is not drawn: it only decides time_color and where the divider goes,
	# and both of those are covered. Signing it too would only cost repaints that
	# change nothing on screen.
	panel = _Panel()
	base = _hud_row()
	assert (hud.hud_render_signature(panel, [base])
		== hud.hud_render_signature(panel, [dict(base, danger=True)]))


def test_hud_signature_distinguishes_row_order_and_count():
	panel = _Panel()
	one = _hud_row(rank=1, name='Alice')
	two = _hud_row(rank=2, name='Bob', y='-22')
	assert (hud.hud_render_signature(panel, [one, two])
		!= hud.hud_render_signature(panel, [two, one]))
	assert (hud.hud_render_signature(panel, [one, two])
		!= hud.hud_render_signature(panel, [one]))


def test_hud_signature_is_hashable():
	# MatchHud stores it and compares it against the next one.
	sig = hud.hud_render_signature(_Panel(), [_hud_row()])
	assert hash(sig) == hash(hud.hud_render_signature(_Panel(), [_hud_row()]))


def test_an_unchanged_running_order_produces_an_unchanged_signature():
	# The case the dedupe exists for: a checkpoint that moves nobody, or a finish
	# that beats nobody, repaints the HUD with an identical board.
	panel = _Panel()
	rows = [_hud_row(rank=i + 1, name='P{}'.format(i), y='-{}'.format(18 + i * 4))
		for i in range(8)]
	assert (hud.hud_render_signature(panel, rows)
		== hud.hud_render_signature(_Panel(), list(rows)))


# ------------------------------------------------------------- ticker dedupe
# CupTicker is pushed from every overlay refresh too, and it is only a count plus a
# couple of names -- so nearly every one of those repaints an identical card. Its
# signature covers the CONTENT; push_stream_view folds the audience in on top,
# because the ticker goes to a target set that changes without the content changing.

# Jinja syntax, filters and loop-local names -- not context variables.
_JINJA_NOISE = {
	'for', 'in', 'if', 'elif', 'else', 'endif', 'endfor', 'not', 'and', 'or', 'is',
	'none', 'true', 'false', 'join', 'length', 'row',
}


def _template_context_names(name):
	"""Context variables a template reads, as best a regex can tell.

	String literals are stripped first so their contents cannot be mistaken for
	identifiers, and ``row.<field>`` accesses are dropped -- those are loop locals,
	covered separately by the row-field guards above.
	"""
	path = os.path.join(_KO, 'templates', name)
	with open(path, 'r', encoding='utf-8') as handle:
		body = handle.read()
	expressions = re.findall(r'\{\{(.*?)\}\}|\{%(.*?)%\}', body, re.S)
	names = set()
	for parts in expressions:
		text = ' '.join(part for part in parts if part)
		text = re.sub(r"'[^']*'|\"[^\"]*\"", ' ', text)   # drop string literals
		text = re.sub(r'\brow\.[a-z_]+', ' ', text)       # drop loop-local accesses
		names.update(re.findall(r'\b([a-z_][a-z0-9_]*)\b', text))
	return names - _JINJA_NOISE


# Template variable -> the view attribute the signature reads for it. Two do not
# match by name: `practice` comes from the private `_practice`, and `danger_rows` is
# built in get_context_data from `danger_names` (each row's y is derived from its
# index, so the names alone pin it).
TICKER_TEMPLATE_TO_FIELD = {
	'count': 'count',
	'showdown': 'showdown',
	'practice': '_practice',
	'racing_names': 'racing_names',
	'danger_rows': 'danger_names',
}


class _Ticker:
	"""Stand-in for the CupTicker attributes the signature reads."""

	def __init__(self, **kwargs):
		defaults = dict(
			showdown=False, _practice=False, count=8,
			racing_names=[], danger_names=['Dave'])
		defaults.update(kwargs)
		for key, value in defaults.items():
			setattr(self, key, value)


def test_ticker_signature_covers_every_variable_the_template_uses():
	used = _template_context_names('ticker.xml')
	assert used, 'no context variables found -- did ticker.xml move?'
	unknown = used - set(TICKER_TEMPLATE_TO_FIELD)
	assert not unknown, (
		'ticker.xml reads context variables the dedupe does not account for: {}'.format(
			sorted(unknown)))
	# And every mapped field is actually signed, so the table cannot drift either.
	assert set(TICKER_TEMPLATE_TO_FIELD.values()) == set(hud.TICKER_RENDERED_FIELDS)


def test_ticker_signature_reacts_to_every_signed_field():
	base = _Ticker()
	for field, other in (
		('showdown', True), ('_practice', True), ('count', 7),
		('racing_names', ['Alice', 'Bob']), ('danger_names', ['Erin']),
	):
		changed = _Ticker(**{field: other})
		assert (hud.ticker_render_signature(base)
			!= hud.ticker_render_signature(changed)), field


def test_ticker_signature_is_hashable_and_survives_in_place_mutation():
	# The view rebuilds danger_names/racing_names as lists each refresh; the signature
	# has to be a frozen snapshot or a stored one would mutate along with the view and
	# always compare equal -- which would wedge the ticker permanently.
	view = _Ticker(danger_names=['Dave'])
	snapshot = hud.ticker_render_signature(view)
	assert hash(snapshot)
	view.danger_names.append('Erin')
	assert hud.ticker_render_signature(view) != snapshot


def test_ticker_signature_is_stable_for_an_unchanged_card():
	# The case the dedupe exists for.
	assert hud.ticker_render_signature(_Ticker()) == hud.ticker_render_signature(_Ticker())


# The audience-folding half of the ticker dedupe. Extracted by AST from
# apps/knockout/__init__.py, which cannot be imported without pyplanet.


def _load_stream_helpers():
	import ast
	path = os.path.join(_KO, '__init__.py')
	with open(path, 'r', encoding='utf-8') as handle:
		tree = ast.parse(handle.read(), path)
	wanted = {'_stream_send_needed', '_stream_mark_sent'}
	body = [node for node in ast.walk(tree)
		if isinstance(node, ast.FunctionDef) and node.name in wanted]
	found = {node.name for node in body}
	assert found == wanted, 'missing in __init__.py: {}'.format(wanted - found)
	for node in body:
		node.decorator_list = []      # they are @staticmethod on KnockoutConfig
	ns = {}
	exec(compile(ast.Module(body=body, type_ignores=[]), path, 'exec'), ns)
	return ns['_stream_send_needed'], ns['_stream_mark_sent']


stream_send_needed, stream_mark_sent = _load_stream_helpers()


class _View:
	def __init__(self):
		self.stream_sent = None
		self.sends = 0


_TARGETED = ('targeted', ('alice',), ('bob',))


def _push(view, signature, audience, ok=True):
	"""One push_stream_view call: check, send, and record only if the send worked.

	Returns whether a send was attempted.
	"""
	if not stream_send_needed(view, signature, audience):
		return False
	if ok:
		stream_mark_sent(view, signature, audience)
	return True


def test_stream_push_without_a_signature_always_sends():
	# The lower third passes none: a flash is an event, not a state, so two identical
	# flashes in a row must both fire.
	view = _View()
	for _ in range(3):
		assert _push(view, None, _TARGETED) is True
	assert view.sends == 3
	# ...and it never starts remembering one, which would dedupe the next flash.
	assert view.stream_sent is None


def test_stream_push_skips_an_identical_repaint():
	view = _View()
	sig = ('showdown', 2)
	assert _push(view, sig, _TARGETED) is True
	assert _push(view, sig, _TARGETED) is False
	assert _push(view, sig, _TARGETED) is False
	assert view.sends == 1


def test_stream_push_sends_when_the_content_changes():
	view = _View()
	assert _push(view, ('racing', 8), _TARGETED) is True
	assert _push(view, ('racing', 7), _TARGETED) is True
	assert view.sends == 2


def test_stream_push_sends_when_only_the_audience_changes():
	# The whole reason the audience is folded in: a spectator flip changes who should
	# be holding the card while the card itself is identical.
	view = _View()
	sig = ('racing', 8)
	assert _push(view, sig, ('targeted', ('alice',), ('bob',))) is True
	assert _push(view, sig, ('targeted', ('alice', 'bob'), ())) is True
	assert view.sends == 2


def test_stream_push_sends_when_the_send_shape_changes():
	# Global (show_overlays on) carries no login list, so a switch to or from it has to
	# repaint even though the content never moved.
	view = _View()
	sig = ('racing', 8)
	assert _push(view, sig, ('global',)) is True
	assert _push(view, sig, _TARGETED) is True
	assert _push(view, sig, ('hidden',)) is True
	assert _push(view, sig, ('global',)) is True
	assert view.sends == 4


def test_stream_push_sends_again_after_invalidate():
	# invalidate() is what stops a player who just connected from sitting behind the
	# dedupe with a blank overlay.
	view = _View()
	sig = ('racing', 8)
	assert _push(view, sig, _TARGETED) is True
	assert _push(view, sig, _TARGETED) is False
	view.stream_sent = None                      # CupTicker.invalidate()
	assert _push(view, sig, _TARGETED) is True
	assert view.sends == 2


def test_a_failed_stream_push_is_retried_not_remembered():
	# push_stream_view records only after the await returns. If it recorded first, one
	# transient send error would leave us believing a page is on screen that never
	# arrived, and the ticker would stay stale until its content happened to change.
	view = _View()
	sig = ('racing', 8)
	assert _push(view, sig, _TARGETED, ok=False) is True   # send raised
	assert view.stream_sent is None
	assert view.sends == 0
	assert _push(view, sig, _TARGETED) is True             # so the retry still sends
	assert view.sends == 1

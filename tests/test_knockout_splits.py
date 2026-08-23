"""
Unit tests for the checkpoint-splits standings-board helpers.

The board shows one row per player, ordered by race progress, so a name moves only
when its player is genuinely overtaken. (It replaced a rolling newest-first feed of
the last six crossings, where every checkpoint anybody hit shoved every name down a
row.) ``order_split_rows`` / ``split_rank_key`` in hud_format.py own that ordering
and are tested directly here.

``LiveController._queue_splits`` / ``_splits_paint_loop`` are the coalescing that
stops a burst of checkpoint crossings from broadcasting one ManiaLink page per
crossing to every client, and ``_cp_ordinal`` is the fallback that keeps the board
working when a waypoint payload carries no checkpoint ordinal of its own (payload shapes differ
between PyPlanet versions; an unknown ordinal used to drop the crossing and leave the
panel empty for the whole round). It is pure, so it is extracted from
controllers/live.py by AST — importing that module would pull in pyplanet.

Run with:  python -m pytest tests/test_knockout_splits.py
"""
import ast
import asyncio
import importlib.util
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_KO = os.path.join(_HERE, '..', 'apps', 'knockout')
_LIVE = os.path.join(_KO, 'controllers', 'live.py')


def _load_live_functions(names, globals_=None):
	"""Exec just these LiveController methods, with no pyplanet import.

	``names`` are taken in the order they appear in live.py; the returned namespace
	holds them as plain functions, ready to be bound onto a stand-in class below.
	"""
	with open(_LIVE, 'r', encoding='utf-8') as handle:
		tree = ast.parse(handle.read(), _LIVE)
	body = [
		node for node in ast.walk(tree)
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
	]
	found = {node.name for node in body}
	assert found == set(names), 'missing in live.py: {}'.format(set(names) - found)
	ns = dict(globals_ or {})
	exec(compile(ast.Module(body=body, type_ignores=[]), _LIVE, 'exec'), ns)
	return ns


def _load_cp_ordinal():
	return _load_live_functions(['_cp_ordinal'])['_cp_ordinal']


def _load(name, filename):
	spec = importlib.util.spec_from_file_location(name, os.path.join(_KO, filename))
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


cp_ordinal = _load_cp_ordinal()
hud = _load('ko_hud_format', 'hud_format.py')


class _Live:
	"""Minimal stand-in for the bit of LiveController state _cp_ordinal touches."""

	def __init__(self):
		self.cp_counts = {}


def test_cp_ordinal_counts_crossings_per_player():
	live = _Live()
	assert cp_ordinal(live, 'alice', 8000) == 1
	assert cp_ordinal(live, 'alice', 17000) == 2
	assert cp_ordinal(live, 'alice', 25000) == 3


def test_cp_ordinal_is_independent_per_player():
	live = _Live()
	assert cp_ordinal(live, 'alice', 8000) == 1
	assert cp_ordinal(live, 'bob', 8500) == 1
	assert cp_ordinal(live, 'alice', 17000) == 2
	assert cp_ordinal(live, 'bob', 17500) == 2


def test_cp_ordinal_restarts_when_race_time_goes_backwards():
	"""A give-up/restart rewinds the race clock -- the count must start over so the
	feed does not report CP 7 on the player's first checkpoint of the new run."""
	live = _Live()
	cp_ordinal(live, 'alice', 8000)
	cp_ordinal(live, 'alice', 17000)
	assert cp_ordinal(live, 'alice', 7900) == 1
	assert cp_ordinal(live, 'alice', 16000) == 2


# ----------------------------------------------------- payload diagnostics


def test_describe_payload_shapes():
	assert hud.describe_payload([1, 2, 3]) == 'list[3]'
	assert hud.describe_payload(None) == 'None'
	assert hud.describe_payload({'racetime': 1, 'login': 'a'}) == 'dict{login,racetime}'
	assert hud.describe_payload(7) == 'int'


def test_describe_payload_truncates_dict_keys():
	raw = {'k{}'.format(i): i for i in range(10)}
	described = hud.describe_payload(raw, max_keys=3)
	assert described.startswith('dict{')
	assert described.count(',') == 2


# ------------------------------------------------- standings-board ordering


def _row(login, cp, ms, seq, finished=False):
	return dict(login=login, cp=cp, ms=ms, seq=seq, finished=finished)


def test_split_rows_sort_by_progress_then_time():
	rows = [
		_row('back', 2, 20000, 1),
		_row('lead', 4, 41000, 2),
		_row('mid', 4, 40000, 3),
	]
	assert [r['login'] for r in hud.order_split_rows(rows)] == ['mid', 'lead', 'back']


def test_split_rows_tie_at_the_same_cp_and_time_uses_arrival_order():
	rows = [_row('second', 3, 30000, 9), _row('first', 3, 30000, 4)]
	assert [r['login'] for r in hud.order_split_rows(rows)] == ['first', 'second']


def test_split_row_positions_only_change_on_an_overtake():
	"""The headline requirement: a checkpoint crossing that does not pass anybody must
	leave every row exactly where it was."""
	rows = [
		_row('a', 4, 40000, 1),
		_row('b', 4, 41000, 2),
		_row('c', 3, 30000, 3),
		_row('d', 2, 20000, 4),
	]
	before = [r['login'] for r in hud.order_split_rows(rows)]
	assert before == ['a', 'b', 'c', 'd']

	# 'd' advances a checkpoint but is still behind 'c' -- nothing moves.
	rows[3] = _row('d', 3, 31000, 5)
	assert [r['login'] for r in hud.order_split_rows(rows)] == before

	# 'c' advances past 'b' at the same checkpoint -- exactly those two swap.
	rows[2] = _row('c', 4, 40500, 6)
	assert [r['login'] for r in hud.order_split_rows(rows)] == ['a', 'c', 'b', 'd']


def test_finishers_rank_above_players_still_on_track():
	# A finish's ordinal is one past the last checkpoint, so -cp pins it on top with no
	# special case, and only a faster finisher can displace it.
	rows = [
		_row('driving', 4, 40000, 1),
		_row('slow_fin', 5, 61000, 2, finished=True),
		_row('fast_fin', 5, 60000, 3, finished=True),
	]
	assert [r['login'] for r in hud.order_split_rows(rows)] == [
		'fast_fin', 'slow_fin', 'driving']


def test_split_rows_drop_players_no_longer_racing():
	rows = [_row('alive', 3, 30000, 1), _row('knocked', 4, 40000, 2)]
	ordered = hud.order_split_rows(rows, racing=['alive'])
	assert [r['login'] for r in ordered] == ['alive']


def test_split_rows_show_everyone_when_the_roster_is_unknown():
	# Empty/None racing means the KO roster callbacks have not arrived yet (e.g. the
	# controller reloaded mid-map); blanking the panel there would be worse than
	# showing a row for someone who has since been knocked out.
	rows = [_row('a', 3, 30000, 1), _row('b', 2, 20000, 2)]
	assert len(hud.order_split_rows(rows, racing=[])) == 2
	assert len(hud.order_split_rows(rows, racing=None)) == 2


def test_split_rows_truncate_to_the_panel_height():
	rows = [_row('p{}'.format(i), 3, 30000 + i, i) for i in range(10)]
	ordered = hud.order_split_rows(rows)
	assert len(ordered) == hud.SPLITS_ROWS == 6
	assert [r['login'] for r in ordered] == ['p0', 'p1', 'p2', 'p3', 'p4', 'p5']


def test_split_rank_key_tolerates_missing_and_junk_fields():
	assert hud.split_rank_key({}) == (0, 0, 0)
	assert hud.split_rank_key(dict(cp=None, ms='x', seq=2)) == (0, 0, 2)


# ---------------------------------------------------------------- repaint dedupe
# The board is redrawn from a race callback that fires once per checkpoint per
# player, and every redraw used to broadcast a full ManiaLink page to every client.
# split_row_signature is what lets SplitsHud drop the ones that would repaint an
# identical panel; if it ever starts covering a field the template does not draw,
# the dedupe silently stops working and the flood comes back.


def _drawn(login, name, cp_label, split, y='-7', color='66FF66'):
	"""A row as it reaches the template: rendering fields plus the ordering
	bookkeeping the view carries alongside them."""
	return dict(
		login=login, cp=3, ms=30000, seq=1, finished=False,
		y=y, name=name, cp_label=cp_label, split=split, color=color)


def test_signature_covers_every_field_the_template_draws():
	assert set(hud.SPLIT_RENDERED_FIELDS) == {'y', 'name', 'cp_label', 'split', 'color'}
	base = _drawn('a', 'Alice', 'CP 3', '+0.310')
	for field, other in (
		('y', '-11'), ('name', 'Bob'), ('cp_label', 'CP 4'),
		('split', '+0.320'), ('color', 'FF3333'),
	):
		changed = dict(base, **{field: other})
		assert hud.split_row_signature([base]) != hud.split_row_signature([changed]), field


def test_signature_ignores_bookkeeping_the_panel_never_draws():
	# seq advances on EVERY crossing by design, and ms/cp move for players who are
	# nowhere near the board. Signing over any of them would make every signature
	# unique and drop the hit rate to zero.
	base = _drawn('a', 'Alice', 'CP 3', '+0.310')
	same = dict(base, seq=99, ms=31000, cp=4, finished=True, login='b')
	assert hud.split_row_signature([base]) == hud.split_row_signature([same])


def test_signature_distinguishes_row_order_and_row_count():
	one = _drawn('a', 'Alice', 'CP 3', '12.470')
	two = _drawn('b', 'Bob', 'CP 3', '+0.310', y='-11')
	assert hud.split_row_signature([one, two]) != hud.split_row_signature([two, one])
	assert hud.split_row_signature([one, two]) != hud.split_row_signature([one])
	assert hud.split_row_signature([]) == ()


def test_signature_is_hashable_and_comparable():
	# SplitsHud stores it and compares it against the next one; a dict or list would
	# work for == but not for the identity checks around the _UNKNOWN sentinel.
	sig = hud.split_row_signature([_drawn('a', 'Alice', 'CP 3', '12.470')])
	assert hash(sig) == hash(hud.split_row_signature(
		[_drawn('a', 'Alice', 'CP 3', '12.470')]))


def test_a_crossing_off_the_bottom_of_the_board_does_not_change_the_signature():
	# The whole point: on a full server most crossings are by players outside the
	# top SPLITS_ROWS, and must not cost every client a page replacement.
	board = [_row('p{}'.format(i), 5, 30000 + i, i) for i in range(6)]
	tail = _row('tail', 1, 90000, 6)
	before = hud.order_split_rows(board + [tail])
	after = hud.order_split_rows(board + [dict(tail, cp=2, ms=95000, seq=7)])
	assert hud.split_row_signature(before) == hud.split_row_signature(after)


# ------------------------------------------------------------ repaint coalescing
# Checkpoint crossings arrive in bursts -- a pack hits the same checkpoint inside a
# couple of seconds -- and every one of them used to render the board and broadcast a
# full ManiaLink page to every client. _queue_splits only flags the board dirty;
# _splits_paint_loop does the painting, at most once per SPLITS_REFRESH_INTERVAL.
# These pin the two properties that matter: bursts collapse, and nothing is lost.

# Short enough to keep the tests quick, long enough that scheduling jitter on a busy
# machine cannot make a "fast" drip look slow.
_TICK = 0.05


class _Painter:
	"""Stand-in for the bit of LiveController the coalescing touches."""

	_ns = _load_live_functions(
		['_queue_splits', '_splits_paint_loop'],
		# _splits_paint_loop logs (and swallows) a failure of the coalescing itself.
		{'asyncio': asyncio, 'SPLITS_REFRESH_INTERVAL': _TICK,
			'logger': type('_L', (), {'exception': staticmethod(lambda *a, **k: None)})()},
	)
	_queue_splits = _ns['_queue_splits']
	_splits_paint_loop = _ns['_splits_paint_loop']

	def __init__(self):
		self._splits_dirty = False
		self._splits_task = None
		self.splits_requests = 0
		self.paints = 0

	async def _refresh_splits(self):
		self.paints += 1


def test_a_burst_of_crossings_in_one_tick_paints_once():
	async def run():
		live = _Painter()
		for _ in range(16):          # a 16-player pack crossing the same checkpoint
			live._queue_splits()
		await asyncio.sleep(_TICK * 3)
		return live

	live = asyncio.run(run())
	assert live.splits_requests == 16
	assert live.paints == 1
	assert live._splits_dirty is False


def test_crossings_faster_than_the_interval_are_collapsed():
	async def run():
		live = _Painter()
		for _ in range(20):
			live._queue_splits()
			await asyncio.sleep(_TICK / 10)
		await asyncio.sleep(_TICK * 3)
		return live

	live = asyncio.run(run())
	assert live.splits_requests == 20
	# Two intervals' worth of drip, so at most a paint per interval plus the leading
	# and trailing ones. The point is that it is nowhere near 20.
	assert live.paints <= 5, live.paints
	# Whatever else it drops, it must never drop the LAST one -- that is the repaint
	# carrying the final state of the board.
	assert live._splits_dirty is False


def test_crossings_slower_than_the_interval_are_not_throttled():
	# The delay must only ever apply to a repaint chasing a recent one. A quiet round
	# where crossings trickle in should paint every single time.
	async def run():
		live = _Painter()
		for _ in range(4):
			live._queue_splits()
			await asyncio.sleep(_TICK * 2)
		await asyncio.sleep(_TICK * 2)
		return live

	live = asyncio.run(run())
	assert live.paints == 4


def test_the_paint_task_retires_so_the_next_burst_is_immediate():
	# If the task looped forever, the first crossing after a quiet spell would wait a
	# whole interval before showing -- the board would feel laggy between rounds.
	async def run():
		live = _Painter()
		live._queue_splits()
		await asyncio.sleep(_TICK * 3)
		retired = live._splits_task.done()
		before = live.paints
		live._queue_splits()
		await asyncio.sleep(0)       # one event-loop turn, well under the interval
		return retired, before, live.paints

	retired, before, after = asyncio.run(run())
	assert retired, 'paint task never retired'
	assert after == before + 1


def test_a_failing_repaint_does_not_wedge_the_loop():
	# _refresh_splits swallows its own render errors, but if anything ever did escape,
	# a dead task that still looks alive would freeze the board for the whole map.
	class _Broken(_Painter):
		async def _refresh_splits(self):
			self.paints += 1
			raise RuntimeError('render exploded')

	async def run():
		live = _Broken()
		live._queue_splits()
		await asyncio.sleep(_TICK * 2)
		live._queue_splits()
		await asyncio.sleep(_TICK * 2)
		return live

	live = asyncio.run(run())
	assert live.paints == 2, live.paints


def test_split_signature_covers_every_row_field_the_template_draws():
	# Drift guard: a field splits.xml draws but the signature ignores is a repaint the
	# board will wrongly skip, which shows in game as a panel that stops updating
	# rather than as an error.
	path = os.path.join(_KO, 'templates', 'splits.xml')
	with open(path, 'r', encoding='utf-8') as handle:
		drawn = set(re.findall(r'\brow\.([a-z_]+)', handle.read()))
	assert drawn, 'no row.<field> found -- did splits.xml move or change syntax?'
	missing = drawn - set(hud.SPLIT_RENDERED_FIELDS)
	assert not missing, 'splits.xml draws row fields the dedupe ignores: {}'.format(
		sorted(missing))

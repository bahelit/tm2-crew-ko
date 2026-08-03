"""
Unit tests for match-id allocation and pure cup-capture helpers.
Loaded by path so they run without pyplanet.

Run with:  python -m pytest tests/test_knockout_capture.py
       or:  python tests/test_knockout_capture.py
"""
import ast
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_MATCH_IDS = os.path.join(_HERE, '..', 'apps', 'knockout', 'match_ids.py')
_CAPTURE = os.path.join(_HERE, '..', 'apps', 'knockout', 'controllers', 'capture.py')


def _load_match_ids():
	spec = importlib.util.spec_from_file_location('ko_match_ids', _MATCH_IDS)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _load_pure_capture_helpers():
	"""Exec only the pure helpers from capture.py (no pyplanet import)."""
	with open(_CAPTURE, 'r', encoding='utf-8') as handle:
		source = handle.read()
	tree = ast.parse(source)
	wanted = {'should_arm_cup_handoff', 'carry_over_match_id'}
	body = [
		node for node in tree.body
		if isinstance(node, ast.FunctionDef) and node.name in wanted
	]
	module = ast.Module(body=body, type_ignores=[])
	code = compile(module, _CAPTURE, 'exec')
	ns = {}
	exec(code, ns)
	return ns


match_ids = _load_match_ids()
helpers = _load_pure_capture_helpers()


def test_allocate_match_start_time_monotonic():
	last = 1_000_000
	stamp = match_ids.allocate_match_start_time(last)
	assert stamp > last


def test_allocate_match_start_time_fits_a_32bit_column():
	"""map_start_time is an IntegerField -> signed 32-bit INT on MySQL/Postgres.

	Epoch milliseconds (~1.8e12) overflow it, so every INSERT raised and no map's
	scores were ever stored: the cup showed no points and never auto-completed.
	"""
	stamp = match_ids.allocate_match_start_time(0)
	assert stamp <= match_ids.C_MaxMatchId
	# ...and it is a real timestamp, not a truncated one: seconds since the epoch.
	assert stamp > 1_700_000_000


def test_allocate_match_start_time_bumps_within_the_same_second():
	"""Two maps starting in the same second still get distinct, ordered ids."""
	first = match_ids.allocate_match_start_time(0)
	second = match_ids.allocate_match_start_time(first)
	assert second == first + 1
	assert second <= match_ids.C_MaxMatchId


# ------------------------------------------------------------- id selection

def test_pick_match_id_uses_the_current_map():
	assert match_ids.pick_match_id(202, None, set()) == 202


def test_pick_match_id_prefers_an_unrecorded_previous_map():
	"""Standings for map 1 must keep map 1's id even if map 2 already started."""
	assert match_ids.pick_match_id(202, 101, set()) == 101
	# ...but only while map 1 is still missing: once stored, map 2 owns them.
	assert match_ids.pick_match_id(202, 101, {101}) == 202


def test_pick_match_id_drops_a_repeat_report():
	"""A second KOMatchStandings for an already-recorded map must not be stored.

	It used to mint a fresh id (the FIFO queue was empty), which linked an extra map
	to the active cup: a 3-map Friday cup completed after two maps were raced.
	"""
	assert match_ids.pick_match_id(202, 101, {101, 202}) is None
	assert match_ids.pick_match_id(202, None, {202}) is None
	assert match_ids.pick_match_id(None, None, set()) is None


# ----------------------------------------------------- cup handoff / orphans

def test_should_arm_cup_handoff_on_last_map():
	# maps_played is already-linked count; standings about to land is the next.
	assert helpers['should_arm_cup_handoff'](0, 1) is True   # first of 1
	assert helpers['should_arm_cup_handoff'](6, 7) is True   # 7th of 7
	assert helpers['should_arm_cup_handoff'](5, 7) is False  # 6th of 7
	assert helpers['should_arm_cup_handoff'](0, 7) is False


def test_should_arm_cup_handoff_open_ended():
	assert helpers['should_arm_cup_handoff'](99, 0) is False
	assert helpers['should_arm_cup_handoff'](3, None) is False


def test_carry_over_match_id_keeps_an_unrecorded_knockout_map():
	assert helpers['carry_over_match_id'](101, True, set()) == 101
	assert helpers['carry_over_match_id'](101, True, {101}) is None


def test_carry_over_match_id_drops_non_knockout_maps():
	"""TimeAttack maps and RestartMap-only rotations never report standings.

	Carrying their ids forward is what let the next rotation re-record the previous
	knockout map and count it as an extra cup map.
	"""
	assert helpers['carry_over_match_id'](101, False, set()) is None
	assert helpers['carry_over_match_id'](None, True, set()) is None


# ------------------------------------------------- full id lifecycle (no I/O)

class _Ids:
	"""CaptureController's id bookkeeping with the database and pyplanet stripped out.

	Ids are a plain counter here; ``allocate_match_start_time`` is covered above.
	"""

	def __init__(self):
		self.captured = set()
		self.current = None
		self.prev = None
		self._next = 100

	def report(self):
		"""A KOMatchStandings (or a salvage/force-record). Returns the id it stored
		under, or None when the map it describes is already recorded."""
		chosen = match_ids.pick_match_id(self.current, self.prev, self.captured)
		if chosen is None:
			return None
		if chosen == self.prev:
			self.prev = None
		self.captured.add(chosen)
		return chosen

	def map_start(self, was_knockout, cup_active=True):
		"""A map rotation: salvage the map that just ended if it never reported, retire
		its id, then allocate one for the map now starting."""
		if cup_active and was_knockout and self.current is not None \
				and self.current not in self.captured:
			self.report()
		self.prev = helpers['carry_over_match_id'](self.current, was_knockout, self.captured)
		self._next += 1
		self.current = self._next


def test_a_three_map_cup_records_exactly_three_maps():
	"""``//cup on friday`` on a 3-map playlist, restarts and all.

	The reported off-by-one: the cup announced 3 maps but completed after two were
	raced. Every map_start allocated an id, only knockout maps ever consumed one, and
	the leftovers queued up -- so the rotation after map 1 "salvaged" a stale id and
	stored map 1 a second time, which counted as an extra cup map.
	"""
	ids = _Ids()
	ids.map_start(was_knockout=False, cup_active=False)  # //cup off / BOTN RestartMap
	ids.map_start(was_knockout=False, cup_active=False)  # //cup on's RestartMap
	assert ids.prev is None, 'a TimeAttack map must not leave an id behind'

	for _map in range(3):
		assert ids.report() is not None
		ids.map_start(was_knockout=True)

	assert len(ids.captured) == 3


def test_a_repeat_standings_report_is_not_a_second_map():
	ids = _Ids()
	ids.map_start(was_knockout=False, cup_active=False)
	first = ids.report()
	assert first is not None
	assert ids.report() is None
	assert ids.captured == {first}


def test_standings_landing_after_the_rotation_keep_their_own_map():
	"""No cup active, so nothing salvages: a late report still belongs to map 1."""
	ids = _Ids()
	ids.map_start(was_knockout=False, cup_active=False)
	map_one = ids.current
	ids.map_start(was_knockout=True, cup_active=False)
	assert ids.report() == map_one
	# ...and the map now being played is still free to report its own result.
	assert ids.report() == ids.current


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
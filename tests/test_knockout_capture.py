"""
Unit tests for match-id allocation and pure cup-capture helpers.
Loaded by path so they run without pyplanet.

Run with:  python -m pytest tests/test_knockout_capture.py
       or:  python tests/test_knockout_capture.py
"""
import ast
import importlib.util
import os
from collections import deque

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
	wanted = {'should_arm_cup_handoff', 'orphan_match_id'}
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


def test_dequeue_prefers_queued_id():
	queue = deque([42, 99])
	stamp = match_ids.dequeue_match_start_time(queue, 100)
	assert stamp == 42
	assert list(queue) == [99]


def test_dequeue_allocates_when_queue_empty():
	queue = deque()
	stamp = match_ids.dequeue_match_start_time(queue, 5_000_000)
	assert stamp > 5_000_000
	assert not queue


def test_map_rotation_race_queue_order():
	"""Standings for map 1 must keep map 1's id even if map 2 already started."""
	queue = deque([101, 202])
	assert match_ids.dequeue_match_start_time(queue, 500) == 101
	assert match_ids.dequeue_match_start_time(queue, 500) == 202


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


def test_orphan_match_id_prefers_queue_head():
	queue = deque([101, 202])
	assert helpers['orphan_match_id'](queue, 202, set()) == 101
	assert helpers['orphan_match_id'](queue, 202, {101}) is None


def test_orphan_match_id_falls_back_to_last():
	assert helpers['orphan_match_id'](deque(), 55, set()) == 55
	assert helpers['orphan_match_id'](deque(), 55, {55}) is None
	assert helpers['orphan_match_id'](deque(), None, set()) is None


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
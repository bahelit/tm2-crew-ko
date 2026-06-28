"""
Unit tests for match-id allocation in apps/knockout/controllers/capture.py.
Loaded by path so they run without pyplanet.

Run with:  python -m pytest tests/test_knockout_capture.py
       or:  python tests/test_knockout_capture.py
"""
import importlib.util
import os
from collections import deque

_HERE = os.path.dirname(os.path.abspath(__file__))
_MATCH_IDS = os.path.join(_HERE, '..', 'apps', 'knockout', 'match_ids.py')


def _load():
	spec = importlib.util.spec_from_file_location('ko_match_ids', _MATCH_IDS)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


capture = _load()


def test_allocate_match_start_time_monotonic():
	last = 1_000_000
	stamp = capture.allocate_match_start_time(last)
	assert stamp > last


def test_dequeue_prefers_queued_id():
	queue = deque([42, 99])
	stamp = capture.dequeue_match_start_time(queue, 100)
	assert stamp == 42
	assert list(queue) == [99]


def test_dequeue_allocates_when_queue_empty():
	queue = deque()
	stamp = capture.dequeue_match_start_time(queue, 5_000_000)
	assert stamp > 5_000_000
	assert not queue


def test_map_rotation_race_queue_order():
	"""Standings for map 1 must keep map 1's id even if map 2 already started."""
	queue = deque([101, 202])
	assert capture.dequeue_match_start_time(queue, 500) == 101
	assert capture.dequeue_match_start_time(queue, 500) == 202


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
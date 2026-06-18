"""
Unit tests for the pure (pyplanet-free) Bowl of the Evening helpers in
apps/knockout/botd.py. Loaded by path so they run without pyplanet.

Run with:  python -m pytest tests/test_knockout_botd.py
       or:  python tests/test_knockout_botd.py
"""
import importlib.util
import os
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_KO = os.path.join(_HERE, '..', 'apps', 'knockout')


def _load(name, filename):
	spec = importlib.util.spec_from_file_location(name, os.path.join(_KO, filename))
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


botd = _load('ko_botd', 'botd.py')


# ------------------------------------------------------------------ parse_hhmm

def test_parse_hhmm_valid():
	assert botd.parse_hhmm('17:00') == (17, 0)
	assert botd.parse_hhmm('18:30') == (18, 30)
	assert botd.parse_hhmm('0:5') == (0, 5)
	assert botd.parse_hhmm('9') == (9, 0)


def test_parse_hhmm_invalid_falls_back():
	assert botd.parse_hhmm('') == (17, 0)
	assert botd.parse_hhmm('nope') == (17, 0)
	assert botd.parse_hhmm('25:00') == (17, 0)
	assert botd.parse_hhmm('12:99') == (17, 0)
	assert botd.parse_hhmm(None) == (17, 0)
	assert botd.parse_hhmm('20:00', default=(9, 0)) == (20, 0)
	assert botd.parse_hhmm('bad', default=(9, 0)) == (9, 0)


# ------------------------------------------------------------- next_occurrence

def test_next_occurrence_later_today():
	now = datetime(2026, 6, 15, 14, 0, 0)
	target = botd.next_occurrence(now, 17, 0)
	assert target == datetime(2026, 6, 15, 17, 0, 0)


def test_next_occurrence_rolls_to_tomorrow():
	now = datetime(2026, 6, 15, 18, 0, 0)
	target = botd.next_occurrence(now, 17, 0)
	assert target == datetime(2026, 6, 16, 17, 0, 0)


def test_next_occurrence_exact_now_rolls_forward():
	now = datetime(2026, 6, 15, 17, 0, 0)
	target = botd.next_occurrence(now, 17, 0)
	assert target == datetime(2026, 6, 16, 17, 0, 0)


# ------------------------------------------------------------------ pick_fastest

def test_pick_fastest_lowest_time():
	assert botd.pick_fastest({'a': 42000, 'b': 41000, 'c': 43000}) == 'b'


def test_pick_fastest_empty_is_none():
	assert botd.pick_fastest({}) is None


def test_pick_fastest_single():
	assert botd.pick_fastest({'solo': 99999}) == 'solo'


# ----------------------------------------------------------------- human_duration

def test_human_duration():
	assert botd.human_duration(900) == '15 minutes'
	assert botd.human_duration(60) == '1 minute'
	assert botd.human_duration(150) == '2m 30s'
	assert botd.human_duration(30) == '30s'
	assert botd.human_duration(0) == '0s'


# ----------------------------------------------------------------- countdown marks

def test_countdown_marks_below_total():
	# Only marks strictly below the total are used (see _run_countdown).
	used = [m for m in botd.COUNTDOWN_MARKS if m < 900]
	assert used == [600, 300, 120, 60, 30, 10]
	used_30 = [m for m in botd.COUNTDOWN_MARKS if m < 30]
	assert used_30 == [10]


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

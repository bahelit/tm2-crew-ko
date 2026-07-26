"""
Unit tests for the pure (pyplanet-free) Bowl of the Night helpers in
apps/knockout/botn.py. Loaded by path so they run without pyplanet.

Run with:  python -m pytest tests/test_knockout_botn.py
       or:  python tests/test_knockout_botn.py
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


botn = _load('ko_botn', 'botn.py')
hud_format = _load('ko_hud_format', 'hud_format.py')


# --------------------------------------------------------------- split_cp_label

def test_split_cp_label_checkpoints():
	assert hud_format.split_cp_label(1, False) == 'CP 1'
	assert hud_format.split_cp_label(3, False) == 'CP 3'


def test_split_cp_label_finish_wins():
	# is_end_race takes priority over the checkpoint count.
	assert hud_format.split_cp_label(9, True) == 'FIN'


def test_split_cp_label_bad_input():
	assert hud_format.split_cp_label(0, False) == 'CP'
	assert hud_format.split_cp_label(None, False) == 'CP'


# ------------------------------------------------------------------ parse_hhmm

def test_parse_hhmm_valid():
	assert botn.parse_hhmm('17:00') == (17, 0)
	assert botn.parse_hhmm('18:30') == (18, 30)
	assert botn.parse_hhmm('0:5') == (0, 5)
	assert botn.parse_hhmm('9') == (9, 0)


def test_parse_hhmm_invalid_falls_back():
	assert botn.parse_hhmm('') == (17, 0)
	assert botn.parse_hhmm('nope') == (17, 0)
	assert botn.parse_hhmm('25:00') == (17, 0)
	assert botn.parse_hhmm('12:99') == (17, 0)
	assert botn.parse_hhmm(None) == (17, 0)
	assert botn.parse_hhmm('20:00', default=(9, 0)) == (20, 0)
	assert botn.parse_hhmm('bad', default=(9, 0)) == (9, 0)


# ------------------------------------------------------------- next_occurrence

def test_next_occurrence_later_today():
	now = datetime(2026, 6, 15, 14, 0, 0)
	target = botn.next_occurrence(now, 17, 0)
	assert target == datetime(2026, 6, 15, 17, 0, 0)


def test_next_occurrence_rolls_to_tomorrow():
	now = datetime(2026, 6, 15, 18, 0, 0)
	target = botn.next_occurrence(now, 17, 0)
	assert target == datetime(2026, 6, 16, 17, 0, 0)


def test_next_occurrence_exact_now_rolls_forward():
	now = datetime(2026, 6, 15, 17, 0, 0)
	target = botn.next_occurrence(now, 17, 0)
	assert target == datetime(2026, 6, 16, 17, 0, 0)


# ------------------------------------------------------------------ pick_fastest

def test_pick_fastest_lowest_time():
	assert botn.pick_fastest({'a': 42000, 'b': 41000, 'c': 43000}) == 'b'


def test_pick_fastest_empty_is_none():
	assert botn.pick_fastest({}) is None


def test_pick_fastest_single():
	assert botn.pick_fastest({'solo': 99999}) == 'solo'


# ----------------------------------------------------------------- human_duration

def test_human_duration():
	assert botn.human_duration(900) == '15 minutes'
	assert botn.human_duration(60) == '1 minute'
	assert botn.human_duration(150) == '2m 30s'
	assert botn.human_duration(30) == '30s'
	assert botn.human_duration(0) == '0s'


# --------------------------------------------------------------- resolve_map_count

def test_resolve_map_count_all_sentinel():
	# 'all' (any case / padding) spans the whole playlist.
	assert botn.resolve_map_count('all', 7) == 7
	assert botn.resolve_map_count('ALL', 5) == 5
	assert botn.resolve_map_count('  all  ', 3) == 3


def test_resolve_map_count_negative_spans_playlist():
	assert botn.resolve_map_count(-1, 7) == 7
	assert botn.resolve_map_count('-1', 4) == 4


def test_resolve_map_count_plain_counts():
	assert botn.resolve_map_count(0, 7) == 0       # open-ended
	assert botn.resolve_map_count(3, 7) == 3
	assert botn.resolve_map_count('5', 7) == 5


def test_resolve_map_count_bad_input_is_open_ended():
	assert botn.resolve_map_count('nope', 7) == 0
	assert botn.resolve_map_count(None, 7) == 0


# ----------------------------------------------------------------- countdown marks

def test_countdown_marks_below_total():
	# Only marks strictly below the total are used (see _run_countdown).
	used = [m for m in botn.COUNTDOWN_MARKS if m < 900]
	assert used == [600, 300, 120, 60, 30, 10]
	used_30 = [m for m in botn.COUNTDOWN_MARKS if m < 30]
	assert used_30 == [10]


# ----------------------------------------------------------- practice_map_action

def test_practice_map_action_force_ta_wins():
	# Post-knockout handoff always reloads TA, even mid-practice phase.
	assert botn.practice_map_action('practice', True, 'map-a', 'map-b') == 'force_ta'
	assert botn.practice_map_action('knockout', True, 'map-a', 'map-a') == 'force_ta'


def test_practice_map_action_snap_back_on_drift():
	assert botn.practice_map_action('practice', False, 'map-a', 'map-b') == 'snap_back'
	assert botn.practice_map_action('countdown', False, 'map-a', 'map-b') == 'snap_back'


def test_practice_map_action_hold_on_pinned_map():
	assert botn.practice_map_action('practice', False, 'map-a', 'map-a') == 'hold'
	assert botn.practice_map_action('countdown', False, 'map-a', 'map-a') == 'hold'
	# No pin yet: hold and let the controller pin current.
	assert botn.practice_map_action('practice', False, None, 'map-a') == 'hold'
	assert botn.practice_map_action('practice', False, 'map-a', None) == 'hold'


def test_practice_map_action_idle_outside_practice():
	assert botn.practice_map_action('knockout', False, 'map-a', 'map-b') == 'idle'
	assert botn.practice_map_action('idle', False, 'map-a', 'map-b') == 'idle'


def test_practice_timelimit_is_open_ended():
	# Stock TimeAttack defaults to 300s; practice must disable the cutoff.
	assert botn.PRACTICE_TIMELIMIT == 0


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

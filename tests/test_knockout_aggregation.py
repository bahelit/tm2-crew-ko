"""
Unit tests for the pure (DB/pyplanet-free) helpers in the Knockout plugin:
season leaderboard aggregation and VOD marker formatting.

These load the source files directly by path so the tests run without pyplanet
installed (the package __init__ imports pyplanet, which we want to avoid here).

Run with:  python -m pytest tests/test_knockout_aggregation.py
       or:  python tests/test_knockout_aggregation.py
"""
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_KO = os.path.join(_HERE, '..', 'apps', 'knockout')


def _load(name, filename):
	spec = importlib.util.spec_from_file_location(name, os.path.join(_KO, filename))
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


season = _load('ko_season', 'season.py')
markers = _load('ko_markers', 'markers.py')


def _standing(login, cup_points, ko_points=0, maps=1, nickname=None):
	return dict(login=login, nickname=nickname or login,
		cup_points=cup_points, ko_points=ko_points, maps=maps)


# --------------------------------------------------------------- season totals

def test_accumulate_season_sums_points_and_counts_wins_podiums():
	# Cup 1 order: alice, bob, cara, dan. Cup 2 order: bob, alice, cara.
	cup1 = [_standing('alice', 10), _standing('bob', 8), _standing('cara', 6), _standing('dan', 5)]
	cup2 = [_standing('bob', 10), _standing('alice', 8), _standing('cara', 6)]

	table = season.accumulate_season([cup1, cup2])
	by_login = {row['login']: row for row in table}

	assert by_login['alice']['total_cup_points'] == 18
	assert by_login['bob']['total_cup_points'] == 18
	assert by_login['alice']['wins'] == 1
	assert by_login['bob']['wins'] == 1
	# alice and bob each have 2 podiums; cara 2; dan 1.
	assert by_login['cara']['podiums'] == 2
	assert by_login['dan']['podiums'] == 0
	assert by_login['dan']['cups'] == 1
	assert by_login['alice']['cups'] == 2


def test_accumulate_season_sorts_by_points_then_wins_then_podiums():
	# Two players tied on points; the one with more wins ranks first.
	cup1 = [_standing('alice', 10), _standing('bob', 10)]  # both "win" their cup-of-one? no, placement matters
	# Give them equal points but alice wins one cup, bob wins another -> tie broken by podiums next.
	cup2 = [_standing('bob', 10), _standing('alice', 0, maps=0)]
	table = season.accumulate_season([cup1, cup2])
	# alice: 10 (win cup1) ; bob: 20 (2nd cup1 + win cup2) -> bob first.
	assert table[0]['login'] == 'bob'
	assert table[0]['total_cup_points'] == 20


def test_accumulate_season_empty():
	assert season.accumulate_season([]) == []


def test_season_points_map_for_hud():
	cup1 = [_standing('alice', 10), _standing('bob', 8)]
	cup2 = [_standing('bob', 10), _standing('alice', 8)]
	table = season.accumulate_season([cup1, cup2])
	points = season.season_points_map(table)
	assert points == {'alice': 18, 'bob': 18}


def test_season_points_map_empty():
	assert season.season_points_map([]) == {}


# --------------------------------------------------------------- player stats

def test_accumulate_player_history_and_summary():
	cups = [
		('Weekly', 1, [_standing('alice', 10), _standing('bob', 8)]),
		('Weekly', 2, [_standing('bob', 10), _standing('alice', 8)]),
		('Monthly', 1, [_standing('cara', 10), _standing('alice', 6)]),
	]
	rows, summary = season.accumulate_player('alice', cups)

	# Rows are most-recent first.
	assert [r['edition'] for r in rows] == [1, 2, 1]
	assert [r['cup'] for r in rows] == ['Monthly', 'Weekly', 'Weekly']
	assert summary['cups'] == 3
	assert summary['wins'] == 1          # won Weekly e1
	assert summary['podiums'] == 3       # always top 3
	assert summary['total_cup_points'] == 24
	# places were 1, 2, 2 -> avg 1.7 (rounded)
	assert summary['avg_place'] == 1.7


def test_accumulate_player_absent():
	cups = [('Weekly', 1, [_standing('bob', 10)])]
	rows, summary = season.accumulate_player('nobody', cups)
	assert rows == []
	assert summary['cups'] == 0
	assert summary['avg_place'] == 0


# --------------------------------------------------------------- VOD markers

def test_format_offset():
	assert markers._format_offset(0) == '0:00:00'
	assert markers._format_offset(65) == '0:01:05'
	assert markers._format_offset(3661) == '1:01:01'
	assert markers._format_offset(-5) == '0:00:00'


def test_format_line_with_and_without_stream_start():
	# Fixed epoch for determinism: 2026-01-01T00:00:00 local is hard to pin,
	# so just assert structure and the offset column.
	line = markers.format_line('eliminated', 'Bob', stream_start=1000.0, now=1075.0)
	cols = line.split('\t')
	assert len(cols) == 4
	assert cols[1] == '0:01:15'
	assert cols[2] == 'eliminated'
	assert cols[3] == 'Bob'

	line2 = markers.format_line('map_start', 'A01', stream_start=None, now=1075.0)
	assert line2.split('\t')[1] == '-'


def test_format_line_strips_tabs_and_newlines():
	line = markers.format_line('manual', 'multi\tline\nnote', stream_start=None, now=1.0)
	detail = line.split('\t')[3]
	assert '\t' not in detail and '\n' not in detail


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

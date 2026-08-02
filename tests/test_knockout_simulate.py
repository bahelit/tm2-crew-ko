"""
Unit tests for the solo-testing helpers behind //ko fake and //ko simulate.
Loaded by path so they run without pyplanet.

Run with:  python -m pytest tests/test_knockout_simulate.py
       or:  python tests/test_knockout_simulate.py
"""
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SIMULATE = os.path.join(_HERE, '..', 'apps', 'knockout', 'simulate.py')


def _load_simulate():
	spec = importlib.util.spec_from_file_location('ko_simulate', _SIMULATE)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


simulate = _load_simulate()


# --------------------------------------------------------------------- roster

def test_sim_roster_puts_real_players_first():
	roster = simulate.sim_roster(['treesloth', 'someone'], 4)
	assert roster[:2] == ['treesloth', 'someone']
	assert len(roster) == 4
	# The padding is clearly synthetic so simulated rows stand out in /cup results.
	assert all(login.startswith('*simbot') for login in roster[2:])


def test_sim_roster_pads_from_nobody():
	roster = simulate.sim_roster([], 3)
	assert roster == ['*simbot1*', '*simbot2*', '*simbot3*']


def test_sim_roster_truncates_to_requested_size():
	roster = simulate.sim_roster(['a', 'b', 'c', 'd'], 2)
	assert roster == ['a', 'b']


def test_sim_roster_drops_duplicates():
	"""A login taking two placements on one map would double-count its cup points."""
	roster = simulate.sim_roster(['a', 'a', 'b'], 3)
	assert roster[:2] == ['a', 'b']
	assert len(set(roster)) == 3


# ------------------------------------------------------------------ standings

def test_build_sim_standings_shape_matches_parse_standings():
	"""Same shape callbacks.parse_standings emits: {login, points}, best first."""
	standings = simulate.build_sim_standings(['a', 'b', 'c'])
	assert standings == [
		dict(login='a', points=3),
		dict(login='b', points=2),
		dict(login='c', points=1),
	]
	points = [entry['points'] for entry in standings]
	assert points == sorted(points, reverse=True)


def test_build_sim_standings_rotates_the_winner():
	"""Multi-map simulations must spread cup points, not hand every map to one login."""
	first = simulate.build_sim_standings(['a', 'b', 'c'], rotation=0)
	second = simulate.build_sim_standings(['a', 'b', 'c'], rotation=1)
	third = simulate.build_sim_standings(['a', 'b', 'c'], rotation=2)
	assert [entry['login'] for entry in (first[0], second[0], third[0])] == ['a', 'b', 'c']
	# Rotation wraps, so a long simulation keeps cycling instead of running out.
	assert simulate.build_sim_standings(['a', 'b', 'c'], rotation=3) == first


def test_build_sim_standings_every_login_scores_once_per_map():
	roster = simulate.sim_roster([], 5)
	standings = simulate.build_sim_standings(roster, rotation=2)
	assert len(standings) == 5
	assert len({entry['login'] for entry in standings}) == 5


def test_build_sim_standings_empty_roster():
	assert simulate.build_sim_standings([]) == []


# ---------------------------------------------------------------- arg parsing

def test_parse_count_accepts_a_plain_number():
	assert simulate.parse_count('6', 32) == (6, None)


def test_parse_count_uses_the_default_when_blank():
	assert simulate.parse_count(None, 32, default=6) == (6, None)
	assert simulate.parse_count('  ', 32, default=6) == (6, None)


def test_parse_count_requires_a_value_without_a_default():
	value, error = simulate.parse_count('', 32)
	assert value is None
	assert error


def test_parse_count_rejects_junk_and_out_of_range():
	for raw in ('abc', '0', '-3'):
		value, error = simulate.parse_count(raw, 32)
		assert value is None, raw
		assert error, raw


def test_parse_count_is_bounded():
	"""//ko simulate 5000 would write thousands of rows into a live cup."""
	value, error = simulate.parse_count('5000', simulate.C_MaxSimMaps)
	assert value is None
	assert str(simulate.C_MaxSimMaps) in error


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

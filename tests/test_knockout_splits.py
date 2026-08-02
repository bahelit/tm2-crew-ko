"""
Unit tests for the checkpoint-splits feed helpers.

``LiveController._cp_ordinal`` is the fallback that keeps the bottom splits feed
working when a waypoint payload carries no checkpoint ordinal of its own (payload
shapes differ between PyPlanet versions; an unknown ordinal used to drop the
crossing and leave the feed empty for the whole round). It is pure, so it is
extracted from controllers/live.py by AST — importing that module would pull in
pyplanet.

Run with:  python -m pytest tests/test_knockout_splits.py
"""
import ast
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_KO = os.path.join(_HERE, '..', 'apps', 'knockout')
_LIVE = os.path.join(_KO, 'controllers', 'live.py')


def _load_cp_ordinal():
	"""Exec only LiveController._cp_ordinal (no pyplanet import)."""
	with open(_LIVE, 'r', encoding='utf-8') as handle:
		tree = ast.parse(handle.read(), _LIVE)
	body = [
		node for node in ast.walk(tree)
		if isinstance(node, ast.FunctionDef) and node.name == '_cp_ordinal'
	]
	assert body, '_cp_ordinal not found in live.py'
	module = ast.Module(body=body, type_ignores=[])
	ns = {}
	exec(compile(module, _LIVE, 'exec'), ns)
	return ns['_cp_ordinal']


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

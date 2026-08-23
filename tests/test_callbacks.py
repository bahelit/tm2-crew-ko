"""
Unit tests for the pure callback parsers in apps/knockout/callbacks.py — the
mode -> app integration boundary (KNOCKOUT_REBUILD_SPEC.md section 3.1).

Loaded by path so they run without pyplanet installed (the registration helpers
import pyplanet lazily, so the module top stays import-clean).

Run with:  python -m pytest tests/test_callbacks.py
       or:  python tests/test_callbacks.py
"""
import asyncio
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_KO = os.path.join(_HERE, '..', 'apps', 'knockout')


def _load(name, filename):
	spec = importlib.util.spec_from_file_location(name, os.path.join(_KO, filename))
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


cb = _load('ko_callbacks', 'callbacks.py')


def _run(coro):
	return asyncio.new_event_loop().run_until_complete(coro)


# ------------------------------------------------------------------- _flatten

def test_flatten_bare_list():
	assert cb._flatten(['a:1', 'b:2']) == ['a:1', 'b:2']


def test_flatten_name_pair():
	# ModeScript often wraps the array as ``[callbackName, [entries]]``.
	assert cb._flatten(['KORoundOrder', ['a:1', 'b:2']]) == ['a:1', 'b:2']


def test_flatten_dict_wrapped():
	assert cb._flatten({'data': ['a:1']}) == ['a:1']
	assert cb._flatten({'params': ['b:2']}) == ['b:2']


def test_flatten_scalar():
	assert cb._flatten('solo') == ['solo']


# -------------------------------------------------------------- parse_round_order

def test_parse_round_order_full_entries():
	src = ['alice:1:3:42100:1', 'bob:2:3:43500:1', 'cara:3:2:0:0']
	result = _run(cb.parse_round_order(src))
	order = result['order']
	assert [e['login'] for e in order] == ['alice', 'bob', 'cara']
	assert order[0]['rank'] == 1
	assert order[0]['time'] == 42100
	assert order[0]['finished'] is True
	assert order[2]['finished'] is False


def test_parse_round_order_sorts_by_rank():
	src = ['bob:2', 'alice:1', 'cara:3']
	order = _run(cb.parse_round_order(src))['order']
	assert [e['login'] for e in order] == ['alice', 'bob', 'cara']


def test_parse_round_order_skips_blank_logins():
	src = [':5', 'alice:1']
	order = _run(cb.parse_round_order(src))['order']
	assert [e['login'] for e in order] == ['alice']


def test_parse_round_order_name_pair_shape():
	src = ['KORoundOrder', ['alice:1', 'bob:2']]
	order = _run(cb.parse_round_order(src))['order']
	assert [e['login'] for e in order] == ['alice', 'bob']


# -------------------------------------------------------------- parse_round_start

def test_parse_round_start_bounded():
	assert _run(cb.parse_round_start(['3:5'])) == {'round': 3, 'total': 5}


def test_parse_round_start_unbounded():
	assert _run(cb.parse_round_start(['7:0'])) == {'round': 7, 'total': 0}


def test_parse_round_start_missing_total():
	assert _run(cb.parse_round_start(['2'])) == {'round': 2, 'total': 0}


def test_parse_round_start_empty():
	assert _run(cb.parse_round_start([])) == {'round': 0, 'total': 0}


# --------------------------------------------------------------- parse_standings

def test_parse_standings_sorted_desc():
	src = ['bob:8', 'alice:10', 'cara:6']
	standings = _run(cb.parse_standings(src))['standings']
	assert [(e['login'], e['points']) for e in standings] == [
		('alice', 10), ('bob', 8), ('cara', 6)]


def test_parse_standings_skips_malformed():
	src = ['alice:10', 'noscore', ':5', 'bob:3']
	standings = _run(cb.parse_standings(src))['standings']
	assert [e['login'] for e in standings] == ['alice', 'bob']


def test_parse_standings_name_pair_shape():
	src = ['KOMatchStandings', ['alice:10', 'bob:8']]
	standings = _run(cb.parse_standings(src))['standings']
	assert standings[0]['login'] == 'alice'


# ------------------------------------------------------------ parse_shield_state

def test_parse_shield_state_counts():
	counts = _run(cb.parse_shield_state(['alice:3', 'bob:1']))['counts']
	assert counts == {'alice': 3, 'bob': 1}


def test_parse_shield_state_skips_entries_without_a_colon():
	# An empty bank arrives as the bare callback name. Without the separator guard
	# "KOShieldState" itself would be read as a player holding shields.
	assert _run(cb.parse_shield_state(['KOShieldState']))['counts'] == {}


def test_parse_shield_state_ignores_non_integer_and_non_positive_counts():
	src = ['alice:3', 'bob:zero', 'cara:0', 'dan:-1', ':4']
	assert _run(cb.parse_shield_state(src))['counts'] == {'alice': 3}


def test_parse_shield_state_name_pair_shape():
	counts = _run(cb.parse_shield_state(['KOShieldState', ['alice:2']]))['counts']
	assert counts == {'alice': 2}


def test_parse_shield_state_empty_payload_is_an_empty_bank():
	assert _run(cb.parse_shield_state([]))['counts'] == {}


# ----------------------------------------------------------------- first_login

def test_first_login_list():
	assert cb.first_login(['alice']) == 'alice'
	assert cb.first_login(['bob', 'cara']) == 'bob'


def test_first_login_scalar():
	assert cb.first_login('solo') == 'solo'


def test_first_login_empty():
	assert cb.first_login([]) == ''
	assert cb.first_login(None) == ''


# --------------------------------------------------------------- callback_login

def test_callback_login_reads_source():
	# The real shape: a Callback with no target gets signal= and source= only.
	assert cb.callback_login(dict(signal=object(), source=['alice'])) == 'alice'


def test_callback_login_reads_bare_source_string():
	assert cb.callback_login(dict(signal=object(), source='alice')) == 'alice'


def test_callback_login_missing_payload_is_empty_not_none():
	# Reading a kwarg that is not there used to yield the string 'None', which
	# matched no player and quietly poisoned shield/winner tracking.
	assert cb.callback_login(dict(signal=object())) == ''


def test_callback_login_still_accepts_parsed_kwargs():
	assert cb.callback_login(dict(player_login='bob')) == 'bob'
	assert cb.callback_login(dict(login='cara')) == 'cara'


# --------------------------------------------------------------- contract shape

def test_all_callbacks_is_the_full_contract():
	assert set(cb.ALL_CALLBACKS) == {
		'KOPlayerAdded', 'KOPlayerRemoved', 'KOSendWinner', 'KOMatchStandings',
		'KORoundOrder', 'KORoundStart', 'KOShieldAwarded', 'KOShieldUsed',
		'KOShieldState',
	}


# ------------------------------------------------------------------ dispatch key

def _fake_callback_class(recorder):
	"""Stand-in for pyplanet.core.events.Callback that records its arguments."""
	class FakeCallback:
		def __init__(self, call, namespace, code, target=None):
			recorder.append(dict(call=call, namespace=namespace, code=code, target=target))
	return FakeCallback


def _make_callback(code, target=None):
	"""Call cb.make_callback with a stubbed pyplanet.core.events module."""
	import sys
	import types

	recorder = []
	core = types.ModuleType('pyplanet.core')
	events = types.ModuleType('pyplanet.core.events')
	events.Callback = _fake_callback_class(recorder)
	root = types.ModuleType('pyplanet')
	saved = {name: sys.modules.get(name) for name in
		('pyplanet', 'pyplanet.core', 'pyplanet.core.events')}
	sys.modules.update({
		'pyplanet': root, 'pyplanet.core': core, 'pyplanet.core.events': events})
	try:
		cb.make_callback(code, target=target)
	finally:
		for name, module in saved.items():
			if module is None:
				sys.modules.pop(name, None)
			else:
				sys.modules[name] = module
	return recorder[0]


def test_make_callback_uses_the_script_dispatch_key():
	# PyPlanet dispatches mode script callbacks with
	# SignalManager.get_callback('Script.' + name), so `call` must carry that exact
	# prefixed name. Using the transport name ('ModeScriptCallback') registers under
	# a key nothing is dispatched to and every payload is silently dropped.
	assert _make_callback('KOMatchStandings')['call'] == 'Script.KOMatchStandings'


def test_make_callback_keeps_signal_identity_unprefixed():
	# The prefix belongs to the raw dispatch key only; the PyPlanet-side signal is
	# still script:KOMatchStandings, which register() listens on by name.
	built = _make_callback('KOMatchStandings')
	assert built['namespace'] == 'script'
	assert built['code'] == 'KOMatchStandings'


def test_every_contract_callback_gets_its_own_dispatch_key():
	# One shared key would let the nine callbacks overwrite each other in
	# SignalManager.callbacks -- the second failure mode of the transport-name bug.
	keys = {code: _make_callback(code)['call'] for code in cb.ALL_CALLBACKS}
	assert len(set(keys.values())) == len(cb.ALL_CALLBACKS)
	assert all(key.startswith(cb.SCRIPT_CALL_PREFIX) for key in keys.values())


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

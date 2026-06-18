"""
Knockout mode -> app callback contract (the integration boundary).

This module owns parsing of every ``KO*`` ModeScript callback the Knockout mode
emits, plus helpers to build and register the PyPlanet Callback signals. The
parsers are **pure** (no PyPlanet import at module load) so they can be
unit-tested in isolation; the registration helpers import PyPlanet lazily.

Contract (mode -> app); see KNOCKOUT_REBUILD_SPEC.md section 3.1:

    KOPlayerAdded     login
    KOPlayerRemoved   login
    KOSendWinner      login
    KOMatchStandings  [login:survivalScore, ...]
    KORoundOrder      [login:rank:cps:time:finished, ...]
    KORoundStart      round:total
    KOShieldAwarded   login
    KOShieldUsed      login

Every callback's payload is parsed here so the controllers only subscribe and
react -- they never re-implement the wire format.
"""

# Single-login callbacks: simple payload, no parser target. The listener gets the
# raw ``player_login`` / ``login`` kwarg and pulls the login out with first_login.
SINGLE_LOGIN_CALLBACKS = (
	'KOPlayerAdded',
	'KOPlayerRemoved',
	'KOSendWinner',
	'KOShieldAwarded',
	'KOShieldUsed',
)

# Array / structured callbacks, each parsed by a target function below.
ARRAY_CALLBACKS = {
	'KORoundOrder': 'parse_round_order',
	'KORoundStart': 'parse_round_start',
	'KOMatchStandings': 'parse_standings',
}

# The full §3.1 contract -- eight callbacks.
ALL_CALLBACKS = SINGLE_LOGIN_CALLBACKS + tuple(ARRAY_CALLBACKS)


def _flatten(source):
	"""
	Normalise the shapes a ModeScript array callback can arrive in into a flat
	list of strings. Handles the raw array, a ``[name, [entries]]`` pair, and
	dict-wrapped (``data`` / ``params``) payloads.
	"""
	data = source
	if isinstance(data, dict):
		data = data.get('data') or data.get('params') or list(data.values())
	if (isinstance(data, (list, tuple)) and len(data) == 2
			and isinstance(data[1], (list, tuple))):
		data = data[1]
	if not isinstance(data, (list, tuple)):
		data = [data]
	return [str(item) for item in data]


async def parse_round_order(source, signal=None, **kwargs):
	"""
	Parse a KORoundOrder payload into an ordered list (best first). Each entry is
	``login:rank:cps:time:finished``; only ``login`` is required, the rest are
	best-effort. Returns ``{'order': [ {login, rank, cps, time, finished} ... ]}``.
	"""
	order = []
	for item in _flatten(source):
		parts = str(item).split(':')
		login = parts[0] if parts else ''
		if not login:
			continue

		def _int(index, default=0):
			try:
				return int(parts[index])
			except (IndexError, ValueError):
				return default

		order.append(dict(
			login=login,
			rank=_int(1, len(order) + 1),
			cps=_int(2, 0),
			time=_int(3, 0),
			finished=_int(4, 0) == 1,
		))
	order.sort(key=lambda entry: entry['rank'])
	return dict(order=order)


async def parse_round_start(source, signal=None, **kwargs):
	"""
	Parse a KORoundStart payload (``["round:total"]``) into
	``{'round': int, 'total': int}``. ``total`` is 0 when the map is unbounded.
	"""
	items = _flatten(source)
	parts = str(items[0]).split(':') if items else []

	def _int(index):
		try:
			return int(parts[index])
		except (IndexError, ValueError):
			return 0

	return dict(round=_int(0), total=_int(1))


async def parse_standings(source, signal=None, **kwargs):
	"""
	Parse a KOMatchStandings payload (``["login:points", ...]``) into a list of
	``{'login': str, 'points': int}`` dicts, ordered by points descending so the
	index doubles as placement (0 = winner).
	"""
	standings = []
	for item in _flatten(source):
		login, sep, raw_points = str(item).partition(':')
		if not login or not sep:
			continue
		try:
			points = int(raw_points)
		except (TypeError, ValueError):
			points = 0
		standings.append(dict(login=login, points=points))
	standings.sort(key=lambda entry: entry['points'], reverse=True)
	return dict(standings=standings)


def first_login(payload):
	"""Pull a single login out of the various payload shapes the mode sends."""
	if isinstance(payload, (list, tuple)):
		return str(payload[0]) if payload else ''
	return str(payload) if payload is not None else ''


# --------------------------------------------------------------------------- wiring
# The helpers below import PyPlanet lazily so this module stays import-clean for
# the pure unit tests (tests/test_callbacks.py loads it by file path).

def make_callback(code, target=None):
	"""Build a PyPlanet ModeScript Callback for a ``KO*`` code."""
	from pyplanet.core.events import Callback
	return Callback(call='ModeScriptCallback', namespace='script', code=code, target=target)


def register(app, code, handler, target=None):
	"""
	Register and listen for one ``KO*`` callback on ``app``. When a ``target``
	parser is supplied, the handler receives parsed kwargs and is bound to the
	Callback object; otherwise it is bound to the raw ``script:<code>`` signal.
	Returns the Callback signal.
	"""
	cb = make_callback(code, target=target)
	app.context.signals.register_signal(cb)
	if target is not None:
		app.context.signals.listen(cb, handler)
	else:
		app.context.signals.listen('script:{}'.format(code), handler)
	return cb

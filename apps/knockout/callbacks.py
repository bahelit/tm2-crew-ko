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
    KOShieldState     [login:count, ...]

Every callback's payload is parsed here so the controllers only subscribe and
react -- they never re-implement the wire format.
"""

# Single-login callbacks: simple payload, no parser target. With no target the
# listener is called with just ``signal`` and ``source``; use callback_login() to
# read it -- there is no ``login`` kwarg on this path.
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
	'KOShieldState': 'parse_shield_state',
}

# The full §3.1 contract -- nine callbacks.
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


async def parse_shield_state(source, signal=None, **kwargs):
	"""
	Parse a KOShieldState payload (``["login:count", ...]``) into
	``{'counts': {login: int}}`` -- the mode's authoritative shield bank.

	Entries with no ``:`` are skipped, same as parse_standings: an empty bank arrives
	as the bare callback name, and without that guard "KOShieldState" itself would be
	read as a player holding shields. Counts that are not positive integers are
	dropped, mirroring the mode's "only holders are stored" invariant.
	"""
	counts = {}
	for item in _flatten(source):
		login, sep, raw_count = str(item).partition(':')
		if not login or not sep:
			continue
		try:
			count = int(raw_count)
		except (TypeError, ValueError):
			continue
		if count > 0:
			counts[login] = count
	return dict(counts=counts)


def first_login(payload):
	"""Pull a single login out of the various payload shapes the mode sends."""
	if isinstance(payload, (list, tuple)):
		return str(payload[0]) if payload else ''
	return str(payload) if payload is not None else ''


#: Receiver kwargs that can carry an unparsed payload, best first. ``source`` is the
#: real one; the other two are what PyPlanet's own *parsed* callbacks expose, kept
#: here so a handler cannot break if a callback later grows a target parser.
LOGIN_KWARGS = ('source', 'player_login', 'login')


def callback_login(kwargs):
	"""Pull the login out of an **unparsed** ``KO*`` callback's receiver kwargs.

	A Callback built without a ``target`` keeps PyPlanet's default processor, and
	``Signal.send`` calls it as ``process_target(signal=self, source=source)`` while
	``Signal.process(**data)`` returns its input untouched. So receivers on this path
	are called with exactly two kwargs -- ``signal`` and ``source`` -- and never a
	``login``: that one belongs to stock callbacks that ship their own parser.

	Reading ``login``/``player_login`` here produced the literal string ``'None'``
	for every player added, knocked out and winner, which then failed to match any
	real login. Returns '' when nothing usable is present.
	"""
	for key in LOGIN_KWARGS:
		value = kwargs.get(key)
		if value is not None:
			return first_login(value)
	return ''


# --------------------------------------------------------------------------- wiring
# The helpers below import PyPlanet lazily so this module stays import-clean for
# the pure unit tests (tests/test_callbacks.py loads it by file path).

#: PyPlanet's dispatcher prefix for mode script callbacks. ``GbxRemote.handle_scripted``
#: receives the ManiaPlanet.ModeScriptCallback[Array] transport callback, pulls the
#: script's own callback name out of the payload, and dispatches with
#: ``SignalManager.get_callback('Script.' + name)`` -- so that prefixed string, not the
#: transport name, is the key a Callback must register itself under.
SCRIPT_CALL_PREFIX = 'Script.'


def make_callback(code, target=None):
	"""Build a PyPlanet ModeScript Callback for a ``KO*`` code.

	``call`` is the RAW dispatch key, not a description of the transport:
	``Callback.__init__`` does ``SignalManager.register_signal(Signal(code=call,
	namespace='raw'), callback=True)``, which files the callback under exactly that
	string, and ``handle_scripted`` looks it up as ``Script.<name>``. Stock PyPlanet
	callbacks follow the same rule (``call='Script.Trackmania.Event.WayPoint'``).

	Passing the literal ``'ModeScriptCallback'`` -- the name of the *transport*
	callback that carries every script callback -- registers under a key nothing is
	ever dispatched to. The mode sends, the dedicated server delivers, PyPlanet's
	``if signal:`` finds nothing and drops the payload on the floor. No exception, no
	log line, no partial behaviour: every ``KO*`` count in ``//ko hud`` reads 0 while a
	knockout plays perfectly. It also collided all eight KO callbacks onto one
	registry key, so they overwrote each other on the way in.
	"""
	from pyplanet.core.events import Callback
	return Callback(
		call='{}{}'.format(SCRIPT_CALL_PREFIX, code),
		namespace='script', code=code, target=target)


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

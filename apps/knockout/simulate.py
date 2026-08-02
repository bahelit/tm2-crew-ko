"""Pure helpers for the ``//ko fake`` and ``//ko simulate`` test tools (no PyPlanet imports).

Solo testing is the normal case on a crew server: one admin connects and there is
no field to knock out. Two tools cover that gap from opposite ends.

``//ko fake`` calls the dedicated server's own debug method (``ConnectFakePlayer``,
which returns the new login; ``DisconnectFakePlayer '*'`` drops them all) to put
real bodies in the player list. Fake players fill slots and fire ``KOPlayerAdded``,
but in TrackMania they never drive -- so every one of them DNFs and the mode knocks
them all in a single round (``Knockout.Script.txt``: "Knock all DNF"). That still
drives the whole mode -> callback -> scoring chain with a full-sized field.

``//ko simulate`` skips racing entirely and pushes fabricated standings through the
real ``CaptureController.record_match`` path. That is where cup scoring actually
broke -- epoch-millisecond ids overflowed ``map_start_time`` (see
``match_ids.C_MaxMatchId``) and every insert failed silently -- so being able to
exercise the database writes, the cup point table, CupMatch linking and
auto-complete in seconds is worth more than any HUD test.

The helpers here are pure so they can be unit-tested without a server; the commands
that use them live in ``controllers/commands.py``.
"""

# The dedicated server tops out well below this, but a typo (``//ko fake 500``)
# should not spend a minute hammering ConnectFakePlayer.
C_MaxFakePlayers = 32

# Each simulated map is a full round of database writes; keep a fat-fingered count
# from writing thousands of rows into a live cup.
C_MaxSimMaps = 50

# A simulated field big enough to spread cup points across placements without
# needing an argument. Roughly a normal Friday turnout.
C_DefaultSimPlayers = 6

# Synthetic logins mirror the server's own ``*fakeplayer1*`` convention so rows
# written by a simulation are obvious in /cup results and easy to delete later.
C_SimLoginFormat = '*simbot{}*'


def sim_roster(real_logins, count):
	"""Return ``count`` logins for a simulated match, real players first.

	Keeping connected players at the front means the admin running the test sees
	their own name in ``/cup results``, which is the quickest way to tell a
	simulated cup apart from an empty one. Duplicates are dropped so a login can
	never take two placements on the same map.
	"""
	roster = []
	for login in (real_logins or ()):
		if login and login not in roster:
			roster.append(login)
		if len(roster) >= count:
			break
	while len(roster) < count:
		roster.append(C_SimLoginFormat.format(len(roster) + 1))
	return roster


def build_sim_standings(logins, rotation=0):
	"""Fabricate one map's standings as ``[{login, points}]``, best first.

	``points`` mirrors the mode's survival score (one per round survived), so the
	winner holds the largest value -- the same shape ``callbacks.parse_standings``
	produces, which is what ``results.compute_standings`` sorts on to derive
	placement.

	``rotation`` shifts who wins, so a multi-map simulation produces a real spread
	of cup points instead of the same player topping every map.
	"""
	if not logins:
		return []
	size = len(logins)
	offset = rotation % size
	ordered = list(logins[offset:]) + list(logins[:offset])
	return [
		dict(login=login, points=size - index)
		for index, login in enumerate(ordered)
	]


def parse_count(raw, maximum, default=None):
	"""Parse a positive integer command argument, bounded by ``maximum``.

	Returns ``(value, error)`` where ``error`` is a ready-to-print reason string
	when the argument is unusable, so the caller only has to format one message.
	"""
	text = '' if raw is None else str(raw).strip()
	if not text:
		if default is None:
			return None, 'a count is required'
		return default, None
	try:
		value = int(text)
	except (TypeError, ValueError):
		return None, '"{}" is not a number'.format(text)
	if value < 1:
		return None, 'the count must be at least 1'
	if value > maximum:
		return None, 'the count must be at most {}'.format(maximum)
	return value, None

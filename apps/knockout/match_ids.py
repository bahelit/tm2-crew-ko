"""Pure helpers for stable per-map match identifiers (no PyPlanet imports)."""

import time

# ``MatchInfo.map_start_time`` -- and the ``PlayerScore`` / ``CupMatch`` columns
# that join on it -- are peewee ``IntegerField``s, i.e. a signed 32-bit INT on
# MySQL and Postgres (the documented engines; see pyplanet_settings_example.py).
# Ids must stay under this ceiling: MySQL in strict mode rejects a larger value
# outright, so the whole INSERT raises and the map's scores are lost, while a
# non-strict server silently clamps every map to the same id. Epoch SECONDS fit
# until 2038; epoch MILLISECONDS (~1.8e12) do not, and that overflow is what
# stopped cup scoring from being recorded at all.
C_MaxMatchId = 2 ** 31 - 1


def allocate_match_start_time(last_id):
	"""Return a strictly-increasing match id (epoch seconds; see C_MaxMatchId).

	Second resolution is coarser than a map rotation only in pathological cases;
	the ``last_id + 1`` bump keeps ids unique and ordered when two maps start
	within the same second.
	"""
	stamp = int(time.time())
	return max(stamp, (last_id or 0) + 1)


def pick_match_id(current_id, prev_id, captured):
	"""Which match id a set of standings belongs to, or None to drop them.

	``current_id`` is the map being played; ``prev_id`` is the map that ended most
	recently and still has no standings stored, so a KOMatchStandings arriving just
	after the rotation belongs to it and wins.

	Returns None when both are already in ``captured``: that is a repeat report for a
	map that is already recorded. Storing it again used to be possible (a fresh id was
	minted whenever nothing was queued), which linked an extra map to the active cup
	and completed a fixed-length cup one map early.
	"""
	captured = set(captured or ())
	if prev_id is not None and prev_id not in captured:
		return prev_id
	if current_id is not None and current_id not in captured:
		return current_id
	return None

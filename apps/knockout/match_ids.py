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


def dequeue_match_start_time(queue, last_id):
	"""Pop the oldest queued map-start id, or allocate a fresh one if the queue is empty."""
	if queue:
		return queue.popleft()
	return allocate_match_start_time(last_id)

"""Pure helpers for stable per-map match identifiers (no PyPlanet imports)."""

import time
from collections import deque


def allocate_match_start_time(last_id):
	"""Return a strictly-increasing match id (epoch ms)."""
	stamp = int(time.time() * 1000)
	return max(stamp, last_id + 1)


def dequeue_match_start_time(queue, last_id):
	"""Pop the oldest queued map-start id, or allocate a fresh one if the queue is empty."""
	if queue:
		return queue.popleft()
	return allocate_match_start_time(last_id)
from peewee import *
from pyplanet.core.db import TimedModel


class CupInfo(TimedModel):
	"""
	A cup: a series of Knockout maps whose per-map scores are summed into an
	overall standing. At most one cup is active at a time.
	"""

	cup_key = CharField(null=False, max_length=100, index=True)
	"""Short identifier for the cup (e.g. 'weekly'), links to a preset."""

	name = CharField(null=False, max_length=150)
	"""Display name shown in chat and the results window."""

	edition = IntegerField(null=False, default=1)
	"""Edition/week number, incremented each time the cup is run."""

	map_count = IntegerField(null=False, default=0)
	"""Target number of maps; the cup auto-completes when reached. 0 = open-ended."""

	score_mode = CharField(null=False, max_length=100, default='default')
	"""Id of the points-by-placement table used to award cup points."""

	mode_script = CharField(null=True, max_length=150)
	"""Mode script this cup runs, if applied via a preset."""

	is_active = BooleanField(null=False, default=False, index=True)
	"""Whether this cup is currently collecting results."""

	count_in_season = BooleanField(null=False, default=True)
	"""Whether this cup feeds the season leaderboard. Stamped at creation from the
	global ``save_to_season`` setting so season computation stays deterministic."""

	class Meta:
		db_table = 'knockout_cup'

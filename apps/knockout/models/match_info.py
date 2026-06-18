from peewee import *
from pyplanet.core.db import TimedModel


class MatchInfo(TimedModel):
	"""
	One finished Knockout map (a single knockout match). Identified by the
	server-side match start time so a cup can reference a set of matches.
	"""

	map_start_time = IntegerField(null=False, unique=True, index=True)
	"""
	Identifier for the match. Captured when the map starts; ties PlayerScore
	rows to the map they were recorded on.
	"""

	mode_script = CharField(null=True, max_length=150)
	"""Name of the mode script this match was played in."""

	map_name = CharField(null=True, max_length=250)
	"""Name of the map this match was played on."""

	map_uid = CharField(null=False, max_length=50)
	"""The unique UID of the map file."""

	class Meta:
		db_table = 'knockout_match'

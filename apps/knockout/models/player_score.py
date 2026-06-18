from peewee import *
from pyplanet.core.db import TimedModel


class PlayerScore(TimedModel):
	"""
	A single player's result on a single Knockout map. Joined to MatchInfo via
	map_start_time. `score` holds the Knockout survival score (higher = better
	placement); placement is derived by sorting a match's rows by score.
	"""

	map_start_time = IntegerField(null=False, index=True)
	"""The match this score belongs to (MatchInfo.map_start_time)."""

	login = CharField(null=False, max_length=150, index=True)
	"""Login of the player this score belongs to."""

	nickname = CharField(null=False, max_length=250)
	"""Formatted nickname of the player at the time of the match."""

	country = CharField(null=True, max_length=150)
	"""The player's country, if known."""

	score = IntegerField(null=False, default=0)
	"""Knockout survival points for the player on this map."""

	score2 = IntegerField(null=False, default=0)
	"""Secondary score (reserved, e.g. best race time). Unused for now."""

	class Meta:
		db_table = 'knockout_playerscore'

from peewee import *
from pyplanet.core.db import TimedModel

from .cup_info import CupInfo


class CupMatch(TimedModel):
	"""
	Links a CupInfo to one of its matches (a MatchInfo, by map_start_time).
	`counts` lets an admin include/exclude a map from the cup totals.
	"""

	cup = ForeignKeyField(CupInfo, null=False, index=True, related_name='matches', on_delete='CASCADE')
	"""The cup this match belongs to."""

	map_start_time = IntegerField(null=False, index=True)
	"""Identifier of the match (MatchInfo.map_start_time)."""

	map_index = IntegerField(null=False, default=0)
	"""Zero-based order of this map within the cup."""

	counts = BooleanField(null=False, default=True)
	"""Whether this map is included in the cup standings."""

	class Meta:
		db_table = 'knockout_cupmatch'

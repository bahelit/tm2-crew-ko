import logging

from ..models import CupInfo, CupMatch

logger = logging.getLogger(__name__)


class CupController:
	"""
	Owns the active-cup lifecycle and links finished matches to the active cup.
	State is persisted, so an active cup survives a PyPlanet restart.
	"""

	def __init__(self, app):
		self.app = app
		self.instance = app.instance
		self.active_cup = None

	async def on_start(self):
		await self._ensure_schema()
		rows = list(await CupInfo.execute(
			CupInfo.select().where(CupInfo.is_active == True).order_by(CupInfo.id.desc())
		))
		self.active_cup = rows[0] if rows else None
		if self.active_cup:
			logger.info('Knockout: resumed active cup "%s" (edition %s)',
				self.active_cup.name, self.active_cup.edition)

	async def _ensure_schema(self):
		"""Self-healing schema guard for the knockout_cup table.

		PyPlanet auto-creates missing *tables* on start but never adds new
		*columns* to a table that already exists. Databases created before the
		season-save toggle therefore lack ``count_in_season`` and crash the very
		first SELECT in ``on_start``. Add any missing column here so a restart
		repairs the schema without manual SQL or a migration framework.

		Idempotent: each column is only added when introspection shows it absent.
		"""
		# (column_name, column DDL) pairs to reconcile against the live table.
		expected = [
			('count_in_season', 'TINYINT(1) NOT NULL DEFAULT 1'),
		]
		manager = CupInfo.objects
		database = manager.database
		try:
			with manager.allow_sync():
				existing = {col.name for col in database.get_columns('knockout_cup')}
				for name, ddl in expected:
					if name in existing:
						continue
					database.execute_sql(
						'ALTER TABLE `knockout_cup` ADD COLUMN `{}` {}'.format(name, ddl)
					)
					logger.info('Knockout: added missing column knockout_cup.%s', name)
		except Exception:
			# Don't take the whole app down over the guard itself; the original
			# query will still surface a clear error if a column is truly missing.
			logger.exception('Knockout: schema guard for knockout_cup failed')

	# ---------------------------------------------------------------- lifecycle

	async def start_cup(self, cup_key, name=None, map_count=0, score_mode='default', mode_script=None):
		# Only one active cup at a time; close any existing one first.
		if self.active_cup:
			await self.stop_cup()

		# Continue the edition counter from the most recent cup with this key.
		previous = list(await CupInfo.execute(
			CupInfo.select().where(CupInfo.cup_key == cup_key).order_by(CupInfo.edition.desc())
		))
		edition = (previous[0].edition + 1) if previous else 1

		# Stamp whether this cup feeds the season leaderboard from the global toggle,
		# so historical season computation stays deterministic regardless of later
		# changes to the setting.
		try:
			count_in_season = await self.app.setting_save_to_season.get_value()
		except Exception:
			count_in_season = True

		cup = CupInfo(
			cup_key=cup_key,
			name=name or cup_key,
			edition=edition,
			map_count=map_count,
			score_mode=score_mode,
			mode_script=mode_script,
			is_active=True,
			count_in_season=count_in_season,
		)
		await cup.save()
		self.active_cup = cup
		logger.info('Knockout: started cup "%s" edition %s (map_count=%s)', cup.name, edition, map_count)
		return cup

	async def stop_cup(self):
		if not self.active_cup:
			return None
		cup = self.active_cup
		cup.is_active = False
		await cup.save()
		self.active_cup = None
		logger.info('Knockout: stopped cup "%s"', cup.name)
		return cup

	async def set_map_count(self, count):
		if not self.active_cup:
			return False
		self.active_cup.map_count = max(0, int(count))
		await self.active_cup.save()
		return True

	async def set_edition(self, edition):
		if not self.active_cup:
			return False
		self.active_cup.edition = int(edition)
		await self.active_cup.save()
		return True

	async def set_score_mode(self, score_mode):
		if not self.active_cup:
			return False
		self.active_cup.score_mode = score_mode
		await self.active_cup.save()
		return True

	# ------------------------------------------------------------------ matches

	async def last_cup(self):
		"""Return the most recently created cup (active or not), or None."""
		rows = list(await CupInfo.execute(
			CupInfo.select().order_by(CupInfo.id.desc())
		))
		return rows[0] if rows else None

	async def cup_matches(self, cup=None):
		"""Return the CupMatch rows for a cup, ordered by map index."""
		cup = cup or self.active_cup
		if not cup:
			return []
		return list(await CupMatch.execute(
			CupMatch.select().where(CupMatch.cup == cup.id).order_by(CupMatch.map_index)
		))

	async def toggle_map(self, index):
		"""Flip whether the active cup's map at `index` counts. Returns the new state or None."""
		if not self.active_cup:
			return None
		rows = list(await CupMatch.execute(
			CupMatch.select().where(
				(CupMatch.cup == self.active_cup.id) & (CupMatch.map_index == index)
			)
		))
		if not rows:
			return None
		match = rows[0]
		match.counts = not match.counts
		await match.save()
		return match.counts

	async def on_match_recorded(self, map_start_time, standings):
		"""Called by capture after a map's standings are stored."""
		if not self.active_cup:
			return

		existing = await self.cup_matches()
		if any(match.map_start_time == map_start_time for match in existing):
			return

		index = len(existing)
		await CupMatch.execute(CupMatch.insert(
			cup=self.active_cup.id,
			map_start_time=map_start_time,
			map_index=index,
			counts=True,
		))
		played = index + 1

		target = self.active_cup.map_count
		progress = '{} / {}'.format(played, target) if target else str(played)
		await self.instance.chat(
			'$ff0>>> $fffCup {}$ff0 — map {} recorded.'.format(self.active_cup.name, progress)
		)

		if target and played >= target:
			await self.complete_cup()

	async def complete_cup(self):
		cup = self.active_cup
		if not cup:
			return
		await self.stop_cup()
		await self.instance.chat('$0f0>>> $fffCup {}$0f0 complete!'.format(cup.name))
		# Final standings window is shown by the results controller (Phase 4).
		on_complete = getattr(self.app, 'on_cup_complete', None)
		if on_complete:
			await on_complete(cup)

import logging

from pyplanet.contrib.command import Command

from .. import payouts
from ..botn import resolve_map_count

logger = logging.getLogger(__name__)


class CupCommands:
	"""Registers the //cup admin commands and the /cup public commands."""

	def __init__(self, app):
		self.app = app
		self.instance = app.instance

	@property
	def cup(self):
		return self.app.cup

	async def on_start(self):
		await self.instance.command_manager.register(
			Command(command='on', namespace='cup', target=self.cmd_on, admin=True,
				description='Start a Knockout cup.')
				.add_param(name='key', required=False, default='cup', help='Cup key / preset id.')
				.add_param(name='name', required=False, nargs='*', help='Display name (optional).'),
			Command(command='off', namespace='cup', target=self.cmd_off, admin=True,
				description='Stop the active cup.'),
			Command(command='end', namespace='cup', target=self.cmd_end, admin=True,
				description='End the active cup now (announce results, same as auto-complete).'),
			Command(command='mapcount', namespace='cup', target=self.cmd_mapcount, admin=True,
				description='Set the number of maps in the cup (0 = open-ended, "all" = whole playlist).')
				.add_param(name='count', required=True),
			Command(command='edition', namespace='cup', target=self.cmd_edition, admin=True,
				description='Set the cup edition number.')
				.add_param(name='edition', required=True, type=int),
			Command(command='scoremode', namespace='cup', target=self.cmd_scoremode, admin=True,
				description='Set the points-by-placement table.')
				.add_param(name='mode', required=True),
			Command(command='setup', namespace='cup', target=self.cmd_setup, admin=True,
				description='Apply a mode/settings preset to the server.')
				.add_param(name='preset', required=True),
			Command(command='pay', namespace='cup', target=self.cmd_pay, admin=True,
				description='Pay planets to the cup standings (must be enabled).')
				.add_param(name='payout', required=False),
			Command(command='edit', namespace='cup', target=self.cmd_edit, admin=True,
				description='Toggle whether a map counts towards the cup, by index.')
				.add_param(name='index', required=True, type=int),
			Command(command='export', namespace='cup', target=self.cmd_export, admin=True,
				description='Write CSV + Discord exports of the cup standings.'),
			Command(command='status', namespace='cup', target=self.cmd_status, admin=False,
				description='Show the active cup status.'),
			Command(command='results', namespace='cup', target=self.cmd_results, admin=False,
				description='Show the cup standings.'),
			Command(command='matches', namespace='cup', target=self.cmd_matches, admin=False,
				description='List the maps played in the cup.'),
			Command(command='season', namespace='cup', target=self.cmd_season, admin=False,
				description='Show the season leaderboard across all cups.')
				.add_param(name='key', required=False, help='Limit to one cup key.'),
			Command(command='stats', namespace='cup', target=self.cmd_stats, admin=False,
				description='Show a player\'s cup history.')
				.add_param(name='login', required=True, help='Player login.'),
			Command(command='streamstart', namespace='ko', target=self.cmd_streamstart, admin=True,
				description='Mark t=0 for VOD highlight markers (stream-relative clock).'),
			Command(command='mark', namespace='ko', target=self.cmd_mark, admin=True,
				description='Write a manual VOD highlight marker.')
				.add_param(name='note', required=False, nargs='*', help='Marker note.'),
			Command(command='hud', namespace='ko', target=self.cmd_hud, admin=True,
				description='Diagnostic: report match HUD state and force a test render.'),
			Command(command='on', namespace='botn', target=self.cmd_botn_on, admin=True,
				description='Start a Bowl of the Night (TimeAttack practice until the cutoff, then knockout).')
				.add_param(name='time', required=False, help='Override cutoff time HH:MM (e.g. 18:30).'),
			Command(command='off', namespace='botn', target=self.cmd_botn_off, admin=True,
				description='Stop the Bowl of the Night.'),
			Command(command='start', namespace='botn', target=self.cmd_botn_start, admin=True,
				description='End BOTN practice now and start the knockout immediately.'),
			Command(command='countdown', namespace='botn', target=self.cmd_botn_countdown, admin=True,
				description='Set the seconds between practice closing and the knockout (e.g. 30 for testing).')
				.add_param(name='seconds', required=True, type=int),
			Command(command='status', namespace='botn', target=self.cmd_botn_status, admin=False,
				description='Show the Bowl of the Night phase and cutoff.'),
		)

	# ------------------------------------------------------------------- admin

	async def _refresh_hud_season(self):
		"""Recompute the HUD's cached season totals and repaint, so the season column
		appears/disappears immediately when a cup is started or stopped."""
		live = getattr(self.app, 'live', None)
		if live is None:
			return
		await live._refresh_season_points()
		await live._refresh_overlays()

	def _resolve_map_count(self, raw):
		"""Resolve a configured/typed cup map count against the live playlist length.
		``"all"`` / a negative number span the whole playlist (the Friday knockout cup
		that runs through every map then completes); see ``botn.resolve_map_count``."""
		return resolve_map_count(raw, self.app.playlist_length())

	async def cmd_on(self, player, data, **kwargs):
		explicit_name = ' '.join(data.name).strip() if getattr(data, 'name', None) else None

		# Pull defaults from a named cup definition in the presets file, if any.
		cup_cfg = self.app.presets.get_cup(data.key) or {}
		name = explicit_name or cup_cfg.get('name')
		# 'all' (or a negative count) spans the whole playlist: the cup completes after
		# the knockout has run through every map (the Friday cup workflow).
		map_count = self._resolve_map_count(cup_cfg.get('mapcount', 0))
		score_mode = cup_cfg.get('scoremode')
		if not score_mode:
			score_mode = await self.app.setting_default_score_mode.get_value()

		cup = await self.cup.start_cup(
			cup_key=data.key, name=name, map_count=map_count, score_mode=score_mode,
		)
		await self.instance.chat(
			'$ff0>>> $fff{}$ff0 started a cup: $fff{}$ff0 (edition {}, {}).'.format(
				player.nickname, cup.name, cup.edition,
				'{} maps'.format(map_count) if map_count else 'open-ended')
		)
		await self.app.update_widget()
		await self._refresh_hud_season()

	async def cmd_off(self, player, data, **kwargs):
		cup = await self.cup.stop_cup()
		if cup:
			await self.instance.chat('$ff0>>> Cup $fff{}$ff0 stopped.'.format(cup.name))
			await self.app.hide_widget()
			await self._refresh_hud_season()
			# Drop the server back to TimeAttack between cups.
			await self.app.return_to_timeattack()
		else:
			await self.instance.chat('$f00>>> No active cup.', player)

	async def cmd_end(self, player, data, **kwargs):
		"""Force-complete the active cup (e.g. when auto-complete did not fire)."""
		cup = self.cup.active_cup
		if not cup:
			await self.instance.chat('$f00>>> No active cup.', player)
			return
		await self.instance.chat(
			'$ff0>>> $fff{}$ff0 is ending the cup $fff{}$ff0.'.format(player.nickname, cup.name))
		await self.cup.complete_cup()
		await self.app.hide_widget()
		await self._refresh_hud_season()

	async def cmd_mapcount(self, player, data, **kwargs):
		# 'all' (or a negative count) spans the whole current playlist.
		count = self._resolve_map_count(data.count)
		if not await self.cup.set_map_count(count):
			await self.instance.chat('$f00>>> No active cup.', player)
			return
		await self.instance.chat('$ff0>>> Cup map count set to $fff{}$ff0.'.format(
			count if count else 'open-ended'))

	async def cmd_edition(self, player, data, **kwargs):
		if not await self.cup.set_edition(data.edition):
			await self.instance.chat('$f00>>> No active cup.', player)
			return
		await self.instance.chat('$ff0>>> Cup edition set to $fff{}$ff0.'.format(data.edition))

	async def cmd_scoremode(self, player, data, **kwargs):
		if not await self.cup.set_score_mode(data.mode):
			await self.instance.chat('$f00>>> No active cup.', player)
			return
		await self.instance.chat('$ff0>>> Cup score mode set to $fff{}$ff0.'.format(data.mode))

	async def cmd_setup(self, player, data, **kwargs):
		preset = self.app.presets.get_preset(data.preset)
		if not preset:
			await self.instance.chat('$f00>>> Unknown preset "{}".'.format(data.preset), player)
			return
		script = preset.get('script')
		settings = preset.get('settings') or {}
		if script:
			await self.instance.mode_manager.set_next_script(script)
		if settings:
			await self.instance.mode_manager.update_settings(settings)
		await self.instance.chat(
			'$ff0>>> Applied preset $fff{}$ff0 ({} setting(s)){}.'.format(
				data.preset, len(settings),
				' — new script loads on next map' if script else '')
		)

	async def cmd_pay(self, player, data, **kwargs):
		if not await self.app.setting_payouts_enabled.get_value():
			await self.instance.chat(
				'$f00>>> Cup payouts are disabled (enable the cup_payouts_enabled setting).', player)
			return

		cup = self.cup.active_cup or await self.cup.last_cup()
		if not cup:
			await self.instance.chat('$f00>>> No cup to pay out.', player)
			return

		payout_key = data.payout if getattr(data, 'payout', None) else None
		if not payout_key:
			payout_key = (self.app.presets.get_cup(cup.cup_key) or {}).get('payout')
		amounts = self.app.presets.get_payout(payout_key) if payout_key else []
		if not amounts:
			await self.instance.chat(
				'$f00>>> No payout "{}" configured.'.format(payout_key), player)
			return

		standings = await self.app.results.compute_standings(cup)
		plan = payouts.plan_payout(standings, amounts)
		if not plan:
			await self.instance.chat('$f00>>> Nothing to pay.', player)
			return

		paid = await payouts.pay_planets(self.instance, plan, label='{} payout'.format(cup.name))
		await self.instance.chat(
			'$ff0>>> Paid $fff{}$ff0 of {} player(s) for cup $fff{}$ff0.'.format(
				len(paid), len(plan), cup.name)
		)

	async def cmd_edit(self, player, data, **kwargs):
		state = await self.cup.toggle_map(data.index)
		if state is None:
			await self.instance.chat(
				'$f00>>> No active cup, or no map at index {}.'.format(data.index), player)
			return
		await self.instance.chat(
			'$ff0>>> Map {} now {}$ff0 the cup totals.'.format(
				data.index, 'counts towards' if state else '$888excluded from')
		)

	async def cmd_export(self, player, data, **kwargs):
		cup = self.cup.active_cup or await self.cup.last_cup()
		if not cup:
			await self.instance.chat('$f00>>> No cup to export.', player)
			return
		paths = await self.app.results.export(cup)
		if not paths:
			await self.instance.chat('$f00>>> Export failed (check the server log).', player)
			return
		await self.instance.chat(
			'$ff0>>> Exported cup standings to: $fff{}$ff0'.format(', '.join(paths)), player)

	# ------------------------------------------------------------ bowl of the night

	async def cmd_botn_on(self, player, data, **kwargs):
		time_override = getattr(data, 'time', None) or None
		await self.app.botn.start(player, time_override)

	async def cmd_botn_off(self, player, data, **kwargs):
		await self.app.botn.stop(player)

	async def cmd_botn_start(self, player, data, **kwargs):
		await self.app.botn.force_start(player)

	async def cmd_botn_countdown(self, player, data, **kwargs):
		await self.app.botn.set_countdown(player, data.seconds)

	async def cmd_botn_status(self, player, data, **kwargs):
		await self.app.botn.status(player)

	# ------------------------------------------------------------------ public

	async def cmd_status(self, player, data, **kwargs):
		cup = self.cup.active_cup
		if not cup:
			await self.instance.chat('$bbb>>> No cup is currently active.', player)
			return
		matches = await self.cup.cup_matches()
		target = '{} / {}'.format(len(matches), cup.map_count) if cup.map_count else str(len(matches))
		await self.instance.chat(
			'$bbb>>> Cup $fff{}$bbb (edition {}) — maps played: $fff{}$bbb, score mode: $fff{}$bbb.'.format(
				cup.name, cup.edition, target, cup.score_mode),
			player,
		)

	async def cmd_results(self, player, data, **kwargs):
		results = getattr(self.app, 'results', None)
		if results is None:
			await self.instance.chat('$bbb>>> Cup results are not available yet.', player)
			return
		cup = self.cup.active_cup or await self.cup.last_cup()
		await results.show(player, cup=cup)

	async def cmd_matches(self, player, data, **kwargs):
		cup = self.cup.active_cup or await self.cup.last_cup()
		if not cup:
			await self.instance.chat('$bbb>>> No cup to show maps for.', player)
			return
		await self.app.results.show_matches(player, cup)

	async def cmd_season(self, player, data, **kwargs):
		from ..views.season import SeasonView
		cup_key = getattr(data, 'key', None) or None
		standings = await self.app.season.compute_season(cup_key)
		if not standings:
			await self.instance.chat('$bbb>>> No cup results recorded yet.', player)
			return
		view = SeasonView(self.app, standings, cup_key)
		await view.display(player=player)

	async def cmd_stats(self, player, data, **kwargs):
		from ..views.season import CupStatsView
		rows, summary = await self.app.season.compute_player(data.login)
		if not rows:
			await self.instance.chat(
				'$bbb>>> No cup results for login $fff{}$bbb.'.format(data.login), player)
			return
		nickname = await self._resolve_nickname(data.login)
		view = CupStatsView(self.app, data.login, nickname, rows, summary)
		await view.display(player=player)

	async def _resolve_nickname(self, login):
		try:
			target = await self.instance.player_manager.get_player(login=login)
			return target.nickname
		except Exception:
			return login

	async def cmd_streamstart(self, player, data, **kwargs):
		markers = getattr(self.app, 'markers', None)
		if markers is None or not markers.enabled or not markers.path:
			await self.instance.chat(
				'$f00>>> VOD markers are disabled (set vod_markers_enabled + vod_markers_path).', player)
			return
		await markers.set_stream_start()
		await self.instance.chat('$ff0>>> VOD marker clock started (t=0).', player)

	async def cmd_mark(self, player, data, **kwargs):
		markers = getattr(self.app, 'markers', None)
		if markers is None or not markers.enabled or not markers.path:
			await self.instance.chat(
				'$f00>>> VOD markers are disabled (set vod_markers_enabled + vod_markers_path).', player)
			return
		note = ' '.join(data.note).strip() if getattr(data, 'note', None) else 'mark'
		await markers.log('manual', note)
		await self.instance.chat('$ff0>>> Marker written: $fff{}$ff0.'.format(note), player)

	async def cmd_hud(self, player, data, **kwargs):
		app = self.app
		live = getattr(app, 'live', None)
		# Cached flag (read once at on_start) vs the live setting value. If these
		# disagree, the cache is stale and the HUD is gated off by a value that no
		# longer reflects the setting.
		cached = getattr(app, '_match_hud_enabled', False)
		try:
			live_val = await app.setting_show_match_hud.get_value()
		except Exception as e:
			live_val = 'err:{}'.format(e)
		phase = getattr(live, 'phase', '?')
		count = getattr(live, 'count', 0)
		rnd = getattr(live, 'round', 0)
		last_err = getattr(live, 'last_hud_error', None)
		await self.instance.chat(
			'$bbb>>> HUD enabled(cached)=$fff{}$bbb setting=$fff{}$bbb phase=$fff{}$bbb '
			'alive=$fff{}$bbb round=$fff{}$bbb'.format(cached, live_val, phase, count, rnd),
			player,
		)
		# Per-callback receipt counts reveal whether the mode's callbacks reach the
		# plugin at all (all zero => the mode/server is not delivering them).
		seen = getattr(live, 'callbacks_seen', {}) or {}
		seen_str = ' '.join('{}={}'.format(name, seen.get(name, 0)) for name in (
			'KOPlayerAdded', 'KOPlayerRemoved', 'KORoundOrder', 'KORoundStart', 'KOSendWinner'))
		await self.instance.chat('$bbb>>> callbacks: $fff{}'.format(seen_str), player)
		if last_err:
			await self.instance.chat(
				'$f00>>> Last real HUD refresh error: $fff{}$f00 (this is why it is blank).'.format(last_err),
				player,
			)
		hud = getattr(app, 'hud', None)
		if hud is None:
			await self.instance.chat('$f00>>> No HUD view (plugin not fully started?).', player)
			return

		# Exercise the REAL render path (to everyone, from current match state).
		# This is the decisive test: if it throws, the problem is the real refresh;
		# if it silently hides, phase/count say no match is being raced right now.
		if live is not None:
			try:
				await hud.refresh(live)
				if phase in ('idle', 'ended') or count <= 0:
					await self.instance.chat(
						'$bbb>>> Real HUD path ran but stayed hidden: no live match '
						'(phase={} alive={}). Start/join a fresh match, then re-run.'.format(phase, count),
						player,
					)
				else:
					await self.instance.chat(
						'$0f0>>> Real HUD refreshed to everyone from live state — it should be '
						'visible now.', player)
			except Exception as e:
				logger.exception('Knockout: //ko hud real refresh failed')
				await self.instance.chat(
					'$f00>>> Real HUD refresh FAILED: {} (see server log).'.format(e), player)

		try:
			await hud.show_test(player=player)
			await self.instance.chat(
				'$bbb>>> Test HUD shown top-left (you only). If you SEE this but not the real '
				'HUD above, the issue is match state/callbacks, not rendering.', player)
		except Exception as e:
			logger.exception('Knockout: //ko hud test render failed')
			await self.instance.chat('$f00>>> Test HUD render FAILED: {} (see server log).'.format(e), player)

import logging

from pyplanet.contrib.command import Command

from .. import payouts, simulate
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
			Command(command='splits', namespace='ko', target=self.cmd_splits, admin=True,
				description='Diagnostic: report the checkpoint splits feed and force a test render.'),
			Command(command='fake', namespace='ko', target=self.cmd_fake, admin=True,
				description='Testing: connect fake players to fill the server ("off" removes them).')
				.add_param(name='count', required=True, help='How many fake players, or "off".'),
			Command(command='simulate', namespace='ko', target=self.cmd_simulate, admin=True,
				description='Testing: record fabricated knockout maps through the real scoring path.')
				.add_param(name='maps', required=False, help='How many maps to fabricate (default 1).')
				.add_param(name='players', required=False, help='Field size (default 6, connected players first).'),
			Command(command='stream', namespace='ko', target=self.cmd_stream, admin=False,
				description='Toggle stream overlays (ticker + lower-third) for yourself. '
					'Pure spectators already get them; use this on the dedicated stream box if needed.')
				.add_param(name='state', required=False, help='on | off (toggles if omitted).'),
			Command(command='on', namespace='botn', target=self.cmd_botn_on, admin=True,
				description='Start a Bowl of the Night (TimeAttack practice until the cutoff, then knockout).')
				.add_param(name='time', required=False, help='Override cutoff time HH:MM (e.g. 18:30).'),
			Command(command='off', namespace='botn', target=self.cmd_botn_off, admin=True,
				description='Stop the Bowl of the Night.'),
			Command(command='start', namespace='botn', target=self.cmd_botn_start, admin=True,
				description='End BOTN practice now and start the knockout immediately.'),
			Command(command='end', namespace='botn', target=self.cmd_botn_end, admin=True,
				description='Fallback: force a stuck knockout to end now (record the result, return to practice).'),
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

		# A live BOTN owns the cup slot and the mode schedule. Tear it down first so
		# //cup on friday can take over the server (otherwise BOTN keeps the map in
		# TimeAttack practice and the cup only "starts" as a tracking row).
		botn = getattr(self.app, 'botn', None)
		if botn is not None and getattr(botn, 'active', False):
			await botn.stop(player)

		# Apply the linked mode preset (script + settings) so the server actually leaves
		# TimeAttack and runs Knockout. Without this, //cup on only created a DB cup and
		# never switched modes — which is why Cup mode looked like it "wouldn't start".
		preset_key, preset = self.app.presets.resolve_mode_preset(data.key)
		mode_script = None
		if preset:
			mode_script = preset.get('script')
			settings = preset.get('settings') or {}
			ok = await self.app.apply_mode_preset(
				script=mode_script, settings=settings, restart=True)
			if not ok and mode_script:
				await self.instance.chat(
					'$f00>>> Mode script $fff{}$f00 did not load — cup will still track, but '
					'the server may not be in Knockout. Confirm Knockout.Script.txt is on the '
					'dedicated server.'.format(mode_script),
					player,
				)
			elif preset_key:
				await self.instance.chat(
					'$ff0>>> Applied mode preset $fff{}$ff0 ({} setting(s)).'.format(
						preset_key, len(settings)))

		cup = await self.cup.start_cup(
			cup_key=data.key, name=name, map_count=map_count, score_mode=score_mode,
			mode_script=mode_script,
		)
		raw_mapcount = cup_cfg.get('mapcount')
		if map_count and raw_mapcount is not None and str(raw_mapcount).strip().lower() == 'all':
			count_label = '{} maps (whole playlist)'.format(map_count)
		elif map_count:
			count_label = '{} maps'.format(map_count)
		else:
			count_label = 'open-ended (use //cup mapcount to set a limit)'
		await self.instance.chat(
			'$ff0>>> $fff{}$ff0 started a cup: $fff{}$ff0 (edition {}, {}).'.format(
				player.nickname, cup.name, cup.edition, count_label)
		)
		await self.instance.chat(
			'$bbb>>> Points update after each knockout map finishes (chat: "map X recorded"). '
			'Stream box: pure spectator or $fff/ko stream on$bbb.',
			player,
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
		"""Force-complete the active cup (fallback for when auto-complete did not fire).

		Also recovers a stuck knockout: best-effort record the live map first (same as
		//botn end), then complete the cup and force TimeAttack immediately. Without
		force-record, ending mid-map left zero scores even after a full race.
		"""
		cup = self.cup.active_cup
		if not cup:
			await self.instance.chat('$f00>>> No active cup.', player)
			return
		await self.instance.chat(
			'$ff0>>> $fff{}$ff0 is ending the cup $fff{}$ff0.'.format(player.nickname, cup.name))
		# Save the current map if KOMatchStandings never fired (stuck KO / early end).
		recorded = await self.app.force_record_current_match(reason='cup end')
		if recorded:
			await self.instance.chat(
				'$ff0>>> Saved live standings for the current map before ending.', player)
		# complete_cup is a no-op if force_record already finished a fixed-length cup.
		if self.cup.active_cup:
			await self.cup.complete_cup()
		await self.app.hide_widget()
		await self._refresh_hud_season()
		await self.app.return_to_timeattack()

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
		# Accept either a mode preset id (knockout_friday) or a cup name key (friday)
		# that points at one.
		preset_key, preset = self.app.presets.resolve_mode_preset(data.preset)
		if not preset:
			preset = self.app.presets.get_preset(data.preset)
			preset_key = data.preset if preset else None
		if not preset:
			known = ', '.join(sorted(self.app.presets.presets.keys())) or '(none loaded)'
			await self.instance.chat(
				'$f00>>> Unknown preset "{}". Known: $fff{}$f00.'.format(data.preset, known),
				player,
			)
			return
		script = preset.get('script')
		settings = preset.get('settings') or {}
		# Restart into the mode now (same path as //cup on / BOTN) so setup is not
		# deferred until the next map rotation.
		ok = await self.app.apply_mode_preset(
			script=script, settings=settings, restart=bool(script))
		if script and not ok:
			await self.instance.chat(
				'$f00>>> Failed to load script $fff{}$f00 for preset $fff{}$f00.'.format(
					script, preset_key),
				player,
			)
			return
		await self.instance.chat(
			'$ff0>>> Applied preset $fff{}$ff0 ({} setting(s)){}.'.format(
				preset_key, len(settings),
				' — Knockout loaded on current map' if script else '')
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

	async def cmd_botn_end(self, player, data, **kwargs):
		await self.app.botn.end_now(player)

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

	async def cmd_stream(self, player, data, **kwargs):
		"""Personal stream-HUD opt-in for the dedicated spectator / capture client.

		Pure spectators already receive the ticker and lower-third automatically.
		This command forces them on for the calling login even if that client is not
		flagged as a pure spectator, and survives reconnects until turned off.
		"""
		login = getattr(player, 'login', None)
		if not login:
			return
		wanted = getattr(self.app, 'stream_hud_logins', None)
		if wanted is None:
			self.app.stream_hud_logins = set()
			wanted = self.app.stream_hud_logins

		raw = (getattr(data, 'state', None) or '').strip().lower()
		if raw in ('on', '1', 'true', 'yes'):
			enable = True
		elif raw in ('off', '0', 'false', 'no'):
			enable = False
		elif raw in ('', None):
			enable = login not in wanted
		elif raw == 'status':
			auto = False
			try:
				flow = getattr(player, 'flow', None)
				auto = bool(flow and getattr(flow, 'is_spectator', False))
			except Exception:
				pass
			global_on = bool(getattr(self.app, '_overlays_enabled', False))
			opted = login in wanted
			await self.instance.chat(
				'$bbb>>> Stream HUD: personal=$fff{}$bbb spectator=$fff{}$bbb '
				'show_overlays(everyone)=$fff{}$bbb. Use $fff/ko stream on$bbb to force on.'.format(
					'on' if opted else 'off',
					'yes' if auto else 'no',
					'on' if global_on else 'off'),
				player,
			)
			return
		else:
			await self.instance.chat(
				'$f00>>> Usage: $fff/ko stream [on|off|status]$f00.', player)
			return

		if enable:
			wanted.add(login)
			await self.instance.chat(
				'$0f0>>> Stream overlays ON for you (ticker + lower-third). '
				'$0f0/ko stream off to disable.', player)
		else:
			wanted.discard(login)
			await self.instance.chat(
				'$ff0>>> Stream overlays personal opt-in OFF. '
				'You still see them while pure-spectating.', player)

		live = getattr(self.app, 'live', None)
		if live is not None:
			await live._refresh_overlays()

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
			'KOPlayerAdded', 'KOPlayerRemoved', 'KORoundOrder', 'KORoundStart',
			'KOSendWinner', 'KOMatchStandings', 'KOShieldAwarded', 'KOShieldUsed'))
		await self.instance.chat('$bbb>>> callbacks: $fff{}'.format(seen_str), player)
		holders = sorted(getattr(live, 'shield_holders', None) or ())
		await self.instance.chat(
			'$bbb>>> shields: $fff{}'.format(', '.join(holders) if holders else '(none)'),
			player,
		)
		cup = getattr(getattr(app, 'cup', None), 'active_cup', None)
		if cup is not None:
			played = getattr(getattr(app, 'cup', None), 'maps_played', 0)
			target = getattr(cup, 'map_count', 0) or 0
			await self.instance.chat(
				'$bbb>>> cup maps_played=$fff{}$bbb map_count=$fff{}$bbb cup_active=$fff{}$bbb'.format(
					played, target or 'open', getattr(live, 'cup_active', False)),
				player,
			)
		if last_err:
			await self.instance.chat(
				'$f00>>> Last real HUD refresh error: $fff{}$f00 (this is why it is blank).'.format(last_err),
				player,
			)
		# Scoring lives on a different path than the HUD: KOMatchStandings can arrive
		# and still score nothing if the database write fails. Report that here too,
		# since the symptom (empty /cup results, cup never completing) looks identical
		# to the mode never sending the callback.
		capture_err = getattr(live, 'last_capture_error', None)
		if capture_err:
			await self.instance.chat(
				'$f00>>> Last score-capture error: $fff{}$f00 — maps are NOT being '
				'recorded (see server log).'.format(capture_err),
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

	async def cmd_splits(self, player, data, **kwargs):
		"""Diagnostic for the bottom checkpoint-splits feed.

		The feed only paints while a scored round is live and at least one crossing
		has been recorded, and it is driven entirely by PyPlanet race signals — so
		when it stays blank the cause is one of: the signals never arrive, their
		payload has no usable checkpoint ordinal, the round/phase gate is closed, or
		the manialink itself does not render. This reports all four and then force-
		renders the panel so the last one can be ruled out by eye."""
		app = self.app
		live = getattr(app, 'live', None)
		view = getattr(app, 'splits', None)
		if live is None or view is None:
			await self.instance.chat('$f00>>> No splits view (plugin not fully started?).', player)
			return

		seen = getattr(live, 'signals_seen', {}) or {}
		rnd = getattr(live, 'round', 0)
		phase = getattr(live, 'phase', '?')
		live_round = rnd > 0 and phase in ('racing', 'showdown')
		try:
			enabled = await live._match_hud_enabled()
		except Exception as e:
			enabled = 'err:{}'.format(e)
		await self.instance.chat(
			'$bbb>>> splits: signals waypoint=$fff{}$bbb finish=$fff{}$bbb | round=$fff{}$bbb '
			'phase=$fff{}$bbb live_round=$fff{}$bbb hud_enabled=$fff{}$bbb feed=$fff{}$bbb rows'.format(
				seen.get('waypoint', 0), seen.get('finish', 0), rnd, phase, live_round,
				enabled, len(getattr(live, 'cp_feed', None) or ())),
			player,
		)
		note = getattr(live, 'last_waypoint_note', '')
		await self.instance.chat(
			'$bbb>>> last waypoint: $fff{}'.format(note or '(none received)'), player)
		if not seen.get('waypoint'):
			await self.instance.chat(
				'$ff0>>> No waypoint signals at all: the mode/server is not delivering '
				'Trackmania.Event.WayPoint to PyPlanet (finish-only rows will still appear).',
				player,
			)
		err = getattr(live, 'last_splits_error', None)
		if err:
			await self.instance.chat(
				'$f00>>> Last splits render error: $fff{}$f00 (this is why it is blank).'.format(err),
				player,
			)

		try:
			await view.show_test(player=player)
			await self.instance.chat(
				'$bbb>>> Test splits panel rendered bottom centre-right (you only). If you do NOT '
				'see it, the manialink/placement is the problem; if you do, the data path is.',
				player,
			)
		except Exception as e:
			logger.exception('Knockout: //ko splits test render failed')
			await self.instance.chat(
				'$f00>>> Test splits render FAILED: {} (see server log).'.format(e), player)

	# -------------------------------------------------------------- solo testing

	async def cmd_fake(self, player, data, **kwargs):
		"""Connect (or drop) dedicated-server fake players so a solo admin has a field.

		Uses the server's own debug methods: ``ConnectFakePlayer`` returns the new
		login, and ``DisconnectFakePlayer '*'`` removes every one of them. Fake
		players occupy slots and fire ``KOPlayerAdded``, but in TrackMania they never
		drive — so they all DNF and the mode knocks the whole field in round one,
		leaving the real player as the sole survivor. That is a one-round match, not
		a realistic elimination ladder, but it does exercise the full
		mode → KOMatchStandings → scoring chain with a proper player count.
		"""
		raw = str(getattr(data, 'count', '') or '').strip().lower()

		if raw in ('off', 'none', 'clear', 'remove', '0'):
			try:
				await self.instance.gbx('DisconnectFakePlayer', '*')
			except Exception as exc:
				logger.exception('Knockout: DisconnectFakePlayer failed')
				await self.instance.chat(
					'$f00>>> Could not disconnect the fake players: $fff{}$f00.'.format(exc), player)
				return
			await self.instance.chat('$ff0>>> Disconnected all fake players.', player)
			return

		count, error = simulate.parse_count(raw, simulate.C_MaxFakePlayers)
		if count is None:
			await self.instance.chat(
				'$f00>>> //ko fake: {}$f00. Usage: $fff//ko fake <n|off>$f00.'.format(error), player)
			return

		connected = 0
		for _ in range(count):
			try:
				await self.instance.gbx('ConnectFakePlayer')
			except Exception as exc:
				logger.exception('Knockout: ConnectFakePlayer failed')
				await self.instance.chat(
					'$f00>>> ConnectFakePlayer failed after $fff{}$f00 connected: $fff{}$f00.'.format(
						connected, exc),
					player,
				)
				break
			connected += 1

		if not connected:
			return
		await self.instance.chat(
			'$ff0>>> Connected $fff{}$ff0 fake player(s). They never drive, so every one DNFs and '
			'a knockout map ends in a single round. $fff//ko fake off$ff0 removes them.'.format(connected),
			player,
		)

	async def cmd_simulate(self, player, data, **kwargs):
		"""Record fabricated knockout maps through the real scoring path.

		Each simulated map goes through the same ``CaptureController.record_match``
		call a finished map does: the MatchInfo/PlayerScore writes, the CupMatch
		link, the running cup totals and the auto-complete check. That makes cup
		scoring testable by one admin in seconds — which is exactly what the
		``map_start_time`` overflow needed and never got, since every symptom of it
		only appeared after a whole cup had been raced.

		Rows are real. Synthetic players use ``*simbot1*``-style logins so a
		simulated cup is obvious in ``/cup results``; run it on a throwaway cup
		rather than the one you intend to keep.
		"""
		maps, error = simulate.parse_count(
			getattr(data, 'maps', None), simulate.C_MaxSimMaps, default=1)
		if maps is None:
			await self.instance.chat(
				'$f00>>> //ko simulate: {}$f00 (maps).'.format(error), player)
			return
		size, error = simulate.parse_count(
			getattr(data, 'players', None), simulate.C_MaxFakePlayers,
			default=simulate.C_DefaultSimPlayers)
		if size is None:
			await self.instance.chat(
				'$f00>>> //ko simulate: {}$f00 (players).'.format(error), player)
			return

		capture = getattr(self.app, 'capture', None)
		if capture is None:
			await self.instance.chat(
				'$f00>>> //ko simulate: the capture controller is not running.', player)
			return

		online = []
		try:
			online = [getattr(entry, 'login', None)
				for entry in self.instance.player_manager.online]
		except Exception:
			logger.exception('Knockout: //ko simulate could not list online players')
		roster = simulate.sim_roster([login for login in online if login], size)

		# Clear the stored capture error first, so the report below reflects this run
		# and not a failure left over from an earlier map.
		live = getattr(self.app, 'live', None)
		if live is not None:
			live.last_capture_error = None

		await self.instance.chat(
			'$ff0>>> Simulating $fff{}$ff0 map(s) with a $fff{}$ff0-player field. '
			'These write real rows.'.format(maps, len(roster)),
			player,
		)
		for index in range(maps):
			# Rotate the winner each map so cup points actually spread across the field.
			standings = simulate.build_sim_standings(roster, rotation=index)
			await capture.record_match(standings)

		capture_error = getattr(live, 'last_capture_error', None) if live is not None else None
		if capture_error:
			await self.instance.chat(
				'$f00>>> Simulation hit a score-capture error: $fff{}$f00 — scoring is still '
				'broken (see server log).'.format(capture_error),
				player,
			)
			return
		await self.instance.chat(
			'$0f0>>> Simulation complete — check $fff/cup results$0f0, $fff/cup matches$0f0 '
			'and the map counter in $fff/cup status$0f0.',
			player,
		)

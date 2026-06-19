import logging

from pyplanet.apps.config import AppConfig
from pyplanet.contrib.setting import Setting

from .controllers.capture import CaptureController
from .controllers.cup import CupController
from .botn import BotnController, TIMEATTACK_SCRIPT
from .controllers.commands import CupCommands
from .controllers.results import ResultsController
from .season import SeasonController
from .controllers.live import LiveController
from .markers import MarkersController
from .config import PresetConfig
from .views import CupWidget, CupTicker, CupLowerThird, MatchHud, FinishCountdown, BotnCountdown
from . import score_modes
from . import callbacks
from .loader_fix import install_selfhealing_loader
from .models import MatchInfo, PlayerScore, CupInfo, CupMatch  # noqa: F401  (registers tables)

logger = logging.getLogger(__name__)


class KnockoutConfig(AppConfig):
	game_dependencies = ['trackmania']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.setting_notifications = Setting(
			'notifications',
			'Enable Chat Notifications',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Send chat notifications for Knockout events',
			default=True,
		)
		self.setting_show_join = Setting(
			'show_join',
			'Show Player Join Notifications',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Notify when players join Knockout',
			default=True,
		)
		self.setting_show_knockout = Setting(
			'show_knockout',
			'Show Knockout Notifications',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Notify when players are knocked out',
			default=True,
		)
		self.setting_show_winner = Setting(
			'show_winner',
			'Show Winner Notifications',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Notify when a match winner is determined',
			default=True,
		)
		self.setting_cup_presets_path = Setting(
			'cup_presets_path',
			'Cup Presets File',
			Setting.CAT_BEHAVIOUR,
			type=str,
			description='Path to the cup presets JSON file (names/presets/payouts)',
			default='',
		)
		self.setting_default_score_mode = Setting(
			'cup_default_score_mode',
			'Default Cup Score Mode',
			Setting.CAT_BEHAVIOUR,
			type=str,
			description='Score mode used for new cups: {}'.format(', '.join(score_modes.mode_names())),
			default=score_modes.DEFAULT_MODE,
		)
		self.setting_payouts_enabled = Setting(
			'cup_payouts_enabled',
			'Enable Cup Planet Payouts',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Allow //cup pay to send real planets to cup winners',
			default=False,
		)
		self.setting_cup_export_path = Setting(
			'cup_export_path',
			'Cup Export Directory',
			Setting.CAT_BEHAVIOUR,
			type=str,
			description='Directory for //cup export files (blank = working directory)',
			default='',
		)
		self.setting_show_cup_widget = Setting(
			'show_cup_widget',
			'Show Live Cup Widget',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Show a live standings widget during an active cup (experimental)',
			default=False,
			change_target=self._on_display_setting_changed,
		)
		self.setting_show_overlays = Setting(
			'show_overlays',
			'Show Broadcast Overlays',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Show the live players-remaining ticker and elimination lower-third (for streams)',
			default=False,
			change_target=self._on_display_setting_changed,
		)
		self.setting_show_match_hud = Setting(
			'show_match_hud',
			'Show Live Match HUD',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Show the always-on left-side match HUD (round, players alive, KOs/round, times) to everyone',
			default=True,
			change_target=self._on_display_setting_changed,
		)
		self.setting_vod_markers_enabled = Setting(
			'vod_markers_enabled',
			'Enable VOD Highlight Markers',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Append timestamped highlight markers (eliminations, winners, etc.) to a file',
			default=False,
		)
		self.setting_vod_markers_path = Setting(
			'vod_markers_path',
			'VOD Markers File',
			Setting.CAT_BEHAVIOUR,
			type=str,
			description='Path to the VOD highlight markers file (blank = disabled)',
			default='',
		)
		self.setting_show_season_points = Setting(
			'show_season_points',
			'Show Cup Points on HUD',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Show each racer\'s running cup total (points so far in the active cup) on the match HUD',
			default=True,
			change_target=self._on_display_setting_changed,
		)
		self.setting_save_to_season = Setting(
			'save_to_season',
			'Save Results to Season Leaderboard',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='When off, cups started from now on are excluded from the season leaderboard',
			default=True,
		)
		self.setting_startup_mode = Setting(
			'startup_mode',
			'Server Startup Mode',
			Setting.CAT_BEHAVIOUR,
			type=str,
			description="What the server boots into: 'none' (leave the server's own mode "
				"untouched), 'knockout' (TimeAttack idle, waiting for an admin //cup on), "
				"or 'botn' (auto-start a Bowl of the Night). A session resumed from a "
				"restart is never overridden.",
			default='none',
		)
		self.setting_botn_cutoff_time = Setting(
			'botn_cutoff_time',
			'Bowl of the Night Start Time',
			Setting.CAT_BEHAVIOUR,
			type=str,
			description='Local HH:MM when BOTN practice ends and the knockout begins (default 17:00)',
			default='17:00',
		)
		self.setting_botn_fastest_shield = Setting(
			'botn_fastest_shield',
			'BOTN Fastest-Practice Shield',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Grant the fastest BOTN practice time a one-time shield (save) in the knockout',
			default=True,
		)
		self.setting_botn_countdown_seconds = Setting(
			'botn_countdown_seconds',
			'BOTN Countdown Seconds',
			Setting.CAT_BEHAVIOUR,
			type=int,
			description='Seconds between practice closing and the knockout starting (default 900 = 15 min). '
				'Settable live with //botn countdown <seconds> (e.g. 30 for testing)',
			default=900,
		)

	async def on_init(self):
		await self.context.setting.register(
			self.setting_notifications,
			self.setting_show_join,
			self.setting_show_knockout,
			self.setting_show_winner,
			self.setting_cup_presets_path,
			self.setting_default_score_mode,
			self.setting_payouts_enabled,
			self.setting_cup_export_path,
			self.setting_show_cup_widget,
			self.setting_show_overlays,
			self.setting_show_match_hud,
			self.setting_vod_markers_enabled,
			self.setting_vod_markers_path,
			self.setting_show_season_points,
			self.setting_save_to_season,
			self.setting_startup_mode,
			self.setting_botn_cutoff_time,
			self.setting_botn_fastest_shield,
			self.setting_botn_countdown_seconds,
		)

	async def on_start(self):
		# PyPlanet's jinja loader caches its app->templates mapping once and never
		# picks up apps loaded later via a mode change. BOTN switches modes, which
		# reloads mode-gated contrib apps (e.g. live_rankings) after that cache is
		# frozen -- their templates then 404 and their on_start dies. Make the
		# loader self-heal before any of that can happen. See loader_fix.py.
		install_selfhealing_loader()

		# Single-login KO callbacks (join / knockout / winner). Their array siblings
		# (KORoundOrder, KORoundStart, KOMatchStandings, KOShield*) are registered by
		# the controllers that own them; all parsing lives in callbacks.py.
		for code in ('KOPlayerAdded', 'KOPlayerRemoved', 'KOSendWinner'):
			callbacks.register(self, code, self.handle_knockout_callback)

		self._match_winner = None

		# Cup presets (names / mode presets / payouts) from the configured file.
		presets_path = await self.setting_cup_presets_path.get_value()
		self.presets = PresetConfig(presets_path or None)
		self.presets.load()

		# Cup controllers: state machine, score capture, and commands.
		self.cup = CupController(self)
		await self.cup.on_start()

		self.results = ResultsController(self)
		self.season = SeasonController(self)

		self.capture = CaptureController(self)
		await self.capture.on_start()

		# VOD highlight markers (file-based, off by default).
		self.markers = MarkersController(self)
		await self.markers.on_start()

		# Broadcast overlays: live ticker + transient lower-third (off by default).
		self._overlays_enabled = await self.setting_show_overlays.get_value()
		self.ticker = CupTicker(self)
		self.lower_third = CupLowerThird(self)

		# Always-on left-side match HUD shown to players and spectators (on by
		# default). Driven by the LiveController alongside the broadcast overlays.
		self._match_hud_enabled = await self.setting_show_match_hud.get_value()
		self.hud = MatchHud(self)

		# Lower-right "FINISH NOW" countdown, armed by the LiveController on the
		# first finish of a live round (mirrors the mode's S_FinishCountdown).
		self.finish_countdown = FinishCountdown(self)

		# Right-side countdown, armed by the BotnController for the whole Bowl of the
		# Night: "PRACTICE ENDS IN" to the cutoff, then "KNOCKOUT IN" through the handoff.
		self.botn_countdown = BotnCountdown(self)

		# Live match state drives the overlays and marker events.
		self.live = LiveController(self)
		await self.live.on_start()

		self.commands = CupCommands(self)
		await self.commands.on_start()

		# Bowl of the Night: daily TimeAttack practice -> Knockout handoff
		# (app-driven clock). Constructed after commands since it uses
		# commands._refresh_hud_season.
		self.botn = BotnController(self)
		await self.botn.on_start()

		# Optional live standings widget.
		self._show_widget = await self.setting_show_cup_widget.get_value()
		self.widget = CupWidget(self)
		if self._show_widget and self.cup.active_cup:
			await self.update_widget()

		# Finally, put the server into its configured resting state for this boot
		# (knockout idle in TimeAttack, or an auto-started Bowl of the Night). Runs
		# last so the cup/BOTN controllers have already resumed any live session,
		# which this then leaves untouched.
		await self._apply_startup_mode()

	async def _apply_startup_mode(self):
		"""Boot the server into its configured resting state (see startup_mode).

		'none' leaves the server's own mode alone. 'knockout' drops to TimeAttack and
		waits for an admin to //cup on. 'botn' auto-starts a Bowl of the Night. A
		session already resumed from a restart (an active cup or BOTN) is left as-is.
		"""
		try:
			mode = (await self.setting_startup_mode.get_value() or 'none').strip().lower()
		except Exception:
			logger.exception('Knockout: could not read startup_mode')
			return
		if mode == 'none':
			return
		if self.botn.active or self.cup.active_cup:
			logger.info('Knockout: startup_mode=%s skipped (session already active)', mode)
			return
		if mode == 'knockout':
			logger.info('Knockout: startup_mode=knockout -> TimeAttack, waiting for //cup on')
			await self.return_to_timeattack()
		elif mode == 'botn':
			logger.info('Knockout: startup_mode=botn -> auto-starting Bowl of the Night')
			await self.botn.start()
		else:
			logger.warning('Knockout: unknown startup_mode %r (use none/knockout/botn)', mode)

	async def return_to_timeattack(self):
		"""Drop the server back to its TimeAttack resting state (next-map switch +
		RestartMap so it takes effect on the current map)."""
		try:
			await self.instance.mode_manager.set_next_script(TIMEATTACK_SCRIPT)
			await self.instance.gbx('RestartMap')
		except Exception:
			logger.exception('Knockout: failed to return to TimeAttack')

	async def on_match_recorded(self, map_start_time, standings):
		"""Called by capture after a finished map's standings are persisted."""
		await self.cup.on_match_recorded(map_start_time, standings)
		await self.update_widget()
		# Season totals changed -> refresh the cache and repaint the HUD column.
		live = getattr(self, 'live', None)
		if live is not None:
			await live._refresh_season_points()
			await live._refresh_overlays()

	async def on_cup_complete(self, cup):
		"""Called by the cup controller when a cup reaches its map count."""
		await self.results.announce_top(cup)
		await self.hide_widget()

	async def update_widget(self):
		"""Refresh the live widget, or hide it when no cup is active / disabled."""
		if not getattr(self, '_show_widget', False) or not self.cup.active_cup:
			await self.hide_widget()
			return
		standings = await self.results.compute_standings(self.cup.active_cup)
		try:
			await self.widget.refresh(self.cup.active_cup, standings)
		except Exception:
			pass

	async def hide_widget(self):
		try:
			await self.widget.hide()
		except Exception:
			pass

	async def _on_display_setting_changed(self, *args, **kwargs):
		"""
		Re-read the cached display flags when show_overlays / show_match_hud /
		show_cup_widget are toggled at runtime (via //settings), so the change
		takes effect immediately instead of needing an app reload.
		"""
		self._overlays_enabled = await self.setting_show_overlays.get_value()
		self._match_hud_enabled = await self.setting_show_match_hud.get_value()
		self._show_widget = await self.setting_show_cup_widget.get_value()

		# Hide whatever was just turned off (a disabled view is skipped by
		# _refresh_overlays, so it would otherwise linger on screen).
		if not self._overlays_enabled:
			await self._hide_view(getattr(self, 'ticker', None))
			await self._hide_view(getattr(self, 'lower_third', None))
		if not self._match_hud_enabled:
			await self._hide_view(getattr(self, 'hud', None))
			await self._hide_view(getattr(self, 'finish_countdown', None))

		# Repaint the still-enabled overlays from the live match state, and let
		# update_widget show/hide the cup widget per its own flag + active cup.
		live = getattr(self, 'live', None)
		if live is not None:
			await live._refresh_overlays()
		await self.update_widget()

	async def _hide_view(self, view):
		if view is None:
			return
		try:
			await view.hide()
		except Exception:
			pass

	async def handle_knockout_callback(self, signal, **kwargs):
		code = signal.code
		payload = kwargs.get('player_login') or kwargs.get('login')
		login = payload[0] if isinstance(payload, (list, tuple)) and len(payload) > 0 else str(payload)

		# Live overlays / markers react regardless of the chat-notification setting.
		live = getattr(self, 'live', None)
		if live is not None:
			if code == 'KOPlayerAdded':
				await live.on_player_added(login)
			elif code == 'KOPlayerRemoved':
				await live.on_player_removed(login)
			elif code == 'KOSendWinner':
				await live.on_winner(login)

		# Chat notifications are independently gated.
		if not await self.setting_notifications.get_value():
			return

		if code == 'KOPlayerAdded':
			await self._handle_player_added(payload)
		elif code == 'KOPlayerRemoved':
			await self._handle_player_removed(payload)
		elif code == 'KOSendWinner':
			await self._handle_winner(payload)

	async def _resolve_player_name(self, login):
		try:
			player = await self.instance.get_player(login=login)
			return player.name
		except Exception:
			return login

	async def _handle_player_added(self, payload):
		show_join = await self.setting_show_join.get_value()
		if not show_join:
			return

		login = payload[0] if isinstance(payload, (list, tuple)) and len(payload) > 0 else str(payload)
		name = await self._resolve_player_name(login)
		msg = '$f90>>> $fff{name} $f90joined Knockout!'.format(name=name)
		await self.instance.chat(msg)

	async def _handle_player_removed(self, payload):
		show_knockout = await self.setting_show_knockout.get_value()
		if not show_knockout:
			return

		login = payload[0] if isinstance(payload, (list, tuple)) and len(payload) > 0 else str(payload)
		name = await self._resolve_player_name(login)
		msg = '$f00>>> $fff{name} $f00was knocked out!'.format(name=name)
		await self.instance.chat(msg)

	async def _handle_winner(self, payload):
		show_winner = await self.setting_show_winner.get_value()
		if not show_winner:
			return

		login = payload[0] if isinstance(payload, (list, tuple)) and len(payload) > 0 else str(payload)
		name = await self._resolve_player_name(login)
		self._match_winner = login
		msg = '$0f0>>> $fff{name} $0f0is the winner!'.format(name=name)
		await self.instance.chat(msg)

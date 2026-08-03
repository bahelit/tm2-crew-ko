import asyncio
import logging

from pyplanet.apps.config import AppConfig
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from pyplanet.contrib.setting import Setting

from .controllers.capture import CaptureController
from .controllers.cup import CupController
from .botn import BotnController, TIMEATTACK_SCRIPT
from .controllers.commands import CupCommands
from .controllers.results import ResultsController
from .season import SeasonController
from .controllers.live import LiveController
from .markers import MarkersController
from .config import PresetConfig, BUNDLED_PRESETS_PATH
from .views import CupWidget, CupTicker, CupLowerThird, MatchHud, FinishCountdown, BotnCountdown, SplitsHud
from . import score_modes
from . import callbacks
from .loader_fix import install_selfhealing_loader
from .models import MatchInfo, PlayerScore, CupInfo, CupMatch  # noqa: F401  (registers tables)

logger = logging.getLogger(__name__)

# Settings pushed whenever the server is handed back to its TimeAttack resting
# state. Mode script settings live in ONE server-side map keyed by setting NAME,
# so they outlive the script that set them: TimeAttack.Script.txt declares the
# same S_WarmUpNb / S_WarmUpDuration and calls MB_WarmUp() with them at map
# start, which means a knockout's warm-up rounds (the Friday preset and BOTN
# both stage 3) carry straight into the idle server and every resting map opens
# with a warm-up. These are TimeAttack's own declared defaults.
TIMEATTACK_RESET_SETTINGS = {'S_WarmUpNb': 0, 'S_WarmUpDuration': 0}

# Deferred startup-mode switch: how long to wait for PyPlanet's start_apps_after
# signal, how long to wait when that signal could not be listened for at all, and how
# long to settle before touching the mode. See _deferred_startup_mode.
STARTUP_APPS_TIMEOUT = 60.0
STARTUP_APPS_FALLBACK = 5.0
STARTUP_SETTLE = 2.0


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
			description='Path to a cup presets JSON file (names/presets/payouts). '
				'Leave blank to use the bundled apps/knockout/presets.json (friday/weekly/quick).',
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
			'Show Broadcast Overlays to Everyone',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Stream ticker + elimination lower-third: OFF = pure spectators (and anyone '
				'who ran /ko stream) only; ON = every connected client. Not required for the match '
				'HUD / cup points / splits / finish countdown.',
			default=False,
			change_target=self._on_display_setting_changed,
		)
		self.setting_show_match_hud = Setting(
			'show_match_hud',
			'Show Live Match HUD',
			Setting.CAT_BEHAVIOUR,
			type=bool,
			description='Show the always-on left-side match HUD (round, players alive, KOs/round, times), '
				'plus splits and finish countdown. On by default; always on during active cups and BOTN '
				'even if this is turned off.',
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
			description='Legacy toggle; cup points always appear on the match HUD during an active '
				'cup or BOTN (no admin action needed).',
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
				"or 'botn' (auto-start a Bowl of the Night). A KNOCKOUT_STARTUP_MODE key "
				"in the PyPlanet settings file (settings/base.py or local.py) overrides "
				"this. A session resumed from a restart is never overridden.",
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
		self.setting_botn_countdown_seconds = Setting(
			'botn_countdown_seconds',
			'BOTN Countdown Seconds',
			Setting.CAT_BEHAVIOUR,
			type=int,
			description='Seconds between practice closing and the knockout starting (default 900 = 15 min). '
				'Settable live with //botn countdown <seconds> (e.g. 30 for testing)',
			default=900,
		)
		self.setting_botn_warmup_laps = Setting(
			'botn_warmup_laps',
			'BOTN Warm-up Laps',
			Setting.CAT_BEHAVIOUR,
			type=int,
			description='Warm-up laps the knockout runs before eliminations begin (S_WarmUpNb). '
				'0 = none; default 3',
			default=3,
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
			self.setting_botn_countdown_seconds,
			self.setting_botn_warmup_laps,
		)

	async def on_start(self):
		# One-shot: force the next map to load in TimeAttack after a fixed-length cup
		# completes (Friday cup). BOTN uses botn._force_ta_next_map instead.
		self._force_ta_cup_next_map = False
		self.context.signals.listen(mp_signals.map.map_start, self._on_cup_map_start_handoff)

		# Re-arm mode script callbacks on every map. The paths that switch scripts
		# (BOTN's practice/knockout handoff, return_to_timeattack) fire RestartMap and
		# move on without waiting, so they cannot re-arm the incoming script
		# themselves. map_start is the first moment it is reliably running.
		self.context.signals.listen(mp_signals.map.map_start, self._on_map_start_callbacks)

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

		# Fake field requested by //ko fake, remembered so apply_mode_preset can put
		# S_DebugBotsCount back when Knockout loads. The setting is Knockout-only, so
		# //ko fake before //cup on cannot push it (the server idles in TimeAttack) --
		# and the first Knockout Match_StartMap would then run
		# Users_SetNbFakeUsers(0, 0) and wipe the bots just as the cup begins.
		self.fake_players_wanted = 0

		# Cup presets (names / mode presets / payouts). Prefer an explicit path from
		# the PyPlanet settings file or //settings; otherwise use the bundled defaults
		# that ship inside apps/knockout/ so a plain deploy gets friday/weekly/quick.
		presets_path = self._settings_file_cup_presets_path()
		if not presets_path:
			presets_path = await self.setting_cup_presets_path.get_value()
		if not presets_path:
			presets_path = BUNDLED_PRESETS_PATH
		self.presets = PresetConfig(presets_path)
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

		# Broadcast / stream overlays: ticker + lower-third. Global show_overlays
		# pushes them to everyone; otherwise they go to pure spectators and any
		# login that opted in with /ko stream (the dedicated stream box).
		self._overlays_enabled = await self.setting_show_overlays.get_value()
		self.stream_hud_logins = set()
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
		# Night: "PRACTICE ENDS IN" to the cutoff, then "STARTING IN" through the handoff.
		self.botn_countdown = BotnCountdown(self)

		# Bottom centre-right rolling feed of checkpoint splits, driven by the
		# LiveController's waypoint handler during live rounds (gated on the match HUD).
		self.splits = SplitsHud(self)

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
		#
		# NOT awaited here: PyPlanet's Apps.start() walks its app registry with
		# `for label, app in self.apps.items(): await app.on_start()`. A mode change
		# makes ModeManager call Apps.check(), which re-populates apps that support the
		# new mode straight into that same OrderedDict (live_rankings does not support
		# our Knockout mode, so a Knockout -> TimeAttack switch reloads it). Switching
		# modes inline let that land while we were still awaiting inside on_start --
		# "RuntimeError: OrderedDict mutated during iteration", which aborts the whole
		# boot: no apps started, no HUD, no commands, and a traceback that names only
		# PyPlanet. Returning first lets the iteration finish.
		self._apps_started = asyncio.Event()
		self._apps_started_signal = False
		try:
			from pyplanet.core import signals as core_signals
			self.context.signals.listen(
				core_signals.pyplanet_start_apps_after, self._on_apps_started)
			self._apps_started_signal = True
		except Exception:
			# Older/newer builds may not expose it; the fallback wait covers us.
			logger.exception('Knockout: could not listen for start_apps_after')
		self._startup_task = asyncio.ensure_future(self._deferred_startup_mode())

	async def _on_apps_started(self, *args, **kwargs):
		"""PyPlanet has finished starting every app -- nothing is iterating the app
		registry any more, so it is safe to change the mode script."""
		self._apps_started.set()

	async def _deferred_startup_mode(self):
		"""Apply the configured startup mode once PyPlanet has finished booting.

		Bounded either way: if the signal never arrives the server still lands in its
		configured resting state, a few seconds late, rather than staying in whatever
		mode it came up in.
		"""
		timeout = STARTUP_APPS_TIMEOUT if self._apps_started_signal else STARTUP_APPS_FALLBACK
		try:
			try:
				await asyncio.wait_for(self._apps_started.wait(), timeout=timeout)
			except asyncio.TimeoutError:
				logger.warning(
					'Knockout: PyPlanet did not report its apps started within %ss; '
					'applying the startup mode anyway', timeout)
			await asyncio.sleep(STARTUP_SETTLE)
			await self._apply_startup_mode()
		except asyncio.CancelledError:
			raise
		except Exception:
			logger.exception('Knockout: could not apply the startup mode')

	async def _apply_startup_mode(self):
		"""Boot the server into its configured resting state.

		The mode comes from a ``KNOCKOUT_STARTUP_MODE`` key in the PyPlanet settings
		module (``settings/base.py`` or ``settings/local.py``) if set -- so the server
		can be configured to "just launch" from a file -- otherwise from the live
		``startup_mode`` setting (//settings). 'none' leaves the server's own mode
		alone, 'knockout' drops to TimeAttack and waits for an admin //cup on, 'botn'
		auto-starts a Bowl of the Night. A session already resumed from a restart (an
		active cup or BOTN) is left as-is.
		"""
		mode, source = await self._resolve_startup_mode()
		if mode == 'none':
			return
		if mode == 'botn':
			# A genuinely in-progress practice phase is left to resume (its cutoff was
			# re-armed on boot); anything else -- a handed-off knockout left active by a
			# restart, or some other active cup -- is replaced with a fresh BOTN so a
			# configured boot always lands in practice rather than a stale knockout.
			if self.botn.active and self.botn.phase == 'practice':
				logger.info('Knockout: startup_mode=botn (%s) -> resuming in-progress practice', source)
				return
			logger.info('Knockout: startup_mode=botn (%s) -> starting a fresh Bowl of the Night', source)
			await self.botn.start_fresh()
		elif mode == 'knockout':
			# A resumed cup keeps running; otherwise idle in TimeAttack until //cup on.
			if self.cup.active_cup:
				logger.info('Knockout: startup_mode=knockout (%s) -> resumed cup, leaving as-is', source)
				return
			logger.info('Knockout: startup_mode=knockout (%s) -> TimeAttack, waiting for //cup on', source)
			await self.return_to_timeattack()
		else:
			logger.warning('Knockout: unknown startup_mode %r (%s); use none/knockout/botn', mode, source)

	async def _resolve_startup_mode(self):
		"""Return ``(mode, source)``. A ``KNOCKOUT_STARTUP_MODE`` key in the PyPlanet
		settings file wins over the live ``startup_mode`` setting, so the boot mode can
		be pinned in config for launch-and-play."""
		file_mode = self._settings_file_startup_mode()
		if file_mode:
			return file_mode, 'config file'
		try:
			value = (await self.setting_startup_mode.get_value() or 'none').strip().lower()
		except Exception:
			logger.exception('Knockout: could not read startup_mode setting')
			return 'none', 'setting (error)'
		return value, 'setting'

	@staticmethod
	def _settings_file_startup_mode():
		"""Read ``KNOCKOUT_STARTUP_MODE`` from the PyPlanet settings module, or None if
		unset. Lets the boot mode live in ``settings/base.py`` / ``settings/local.py``."""
		try:
			from pyplanet.conf import settings as pp_settings
			raw = getattr(pp_settings, 'KNOCKOUT_STARTUP_MODE', None)
		except Exception:
			return None
		if raw is None:
			return None
		value = str(raw).strip().lower()
		return value or None

	@staticmethod
	def _settings_file_cup_presets_path():
		"""Read ``KNOCKOUT_CUP_PRESETS_PATH`` from the PyPlanet settings module, or None
		if unset. The live ``cup_presets_path`` setting (//settings) wins when this is absent."""
		try:
			from pyplanet.conf import settings as pp_settings
			raw = getattr(pp_settings, 'KNOCKOUT_CUP_PRESETS_PATH', None)
		except Exception:
			return None
		if raw is None:
			return None
		value = str(raw).strip()
		return value or None

	async def enable_script_callbacks(self):
		"""Re-arm the mode script's XmlRpc callback library after a script change.

		Libs/Nadeo/XmlRpc2 boots DISABLED and gates every callback on that flag; the
		only switch is the XmlRpc.EnableCallbacks script method. PyPlanet sends it
		exactly once, in GbxRemote.connect(), against whichever script was running
		then -- see pyplanet/core/gbx/remote.py. Nothing re-sends it when the script
		changes, so every mode we load here (//cup on, //botn, return_to_timeattack)
		comes up with callbacks off and the controller goes deaf: no KO* standings,
		no waypoints, no scores, and no error on either side.

		Cheap and idempotent, so we just do it after every script load rather than
		trying to detect the case. It must run once the new script is actually
		LIVE -- called straight after RestartMap it would only re-arm the outgoing
		one -- which is why the general net is the map_start hook below.

		Returns True when the call went through.
		"""
		try:
			await self.instance.gbx(
				'TriggerModeScriptEventArray', 'XmlRpc.EnableCallbacks', ['true'])
		except Exception:
			logger.exception('Knockout: could not re-enable mode script callbacks')
			return False
		return True

	async def _on_map_start_callbacks(self, *args, **kwargs):
		"""Keep mode script callbacks armed across map and script changes."""
		await self.enable_script_callbacks()

	async def clear_knockout_warmup(self):
		"""Zero the warm-up settings on the way back to TimeAttack.

		Must run BEFORE the script switch: TimeAttack reads S_WarmUpNb in its own
		Match_StartMap, so a value cleared afterwards is one map too late. See
		TIMEATTACK_RESET_SETTINGS for why anything is inherited at all.
		"""
		mm = self.instance.mode_manager
		# Live push is what actually clears it -- the value carries into the next
		# script -- but stage it too, for hosts that flush next-settings on load.
		try:
			stage = getattr(mm, 'update_next_settings', None)
			if stage is not None:
				await stage(dict(TIMEATTACK_RESET_SETTINGS))
		except Exception:
			logger.exception('Knockout: failed to stage the TimeAttack warm-up reset')
		try:
			await mm.update_settings(dict(TIMEATTACK_RESET_SETTINGS))
		except Exception:
			logger.exception('Knockout: failed to clear the knockout warm-up settings')

	async def return_to_timeattack(self):
		"""Drop the server back to its TimeAttack resting state (next-map switch +
		RestartMap so it takes effect on the current map)."""
		await self.clear_knockout_warmup()
		try:
			await self.instance.mode_manager.set_next_script(TIMEATTACK_SCRIPT)
			await self.instance.gbx('RestartMap')
		except Exception:
			logger.exception('Knockout: failed to return to TimeAttack')
		# No enable_script_callbacks() here: RestartMap has not brought the new script
		# up yet, so the call would land on the outgoing one. The map_start hook
		# re-arms the idle mode once it is actually running.

	async def stream_overlay_targets(self):
		"""Who should receive the stream-only ticker / lower-third.

		Returns:
		  * ``None`` — show to everyone (global ``show_overlays`` is on).
		  * a list of player objects — pure spectators plus anyone who opted in
		    with ``/ko stream`` (the dedicated stream spectator machine).
		  * an empty list — nobody (hide).
		"""
		if getattr(self, '_overlays_enabled', False):
			return None
		wanted = set(getattr(self, 'stream_hud_logins', ()) or ())
		targets = []
		try:
			online = self.instance.player_manager.online
		except Exception:
			return []
		for entry in online:
			login = getattr(entry, 'login', None)
			if not login:
				continue
			if login in wanted:
				targets.append(entry)
				continue
			flow = getattr(entry, 'flow', None)
			if flow is not None and getattr(flow, 'is_spectator', False):
				targets.append(entry)
		return targets

	async def push_stream_view(self, view, visible=True):
		"""Show or hide a stream overlay for the current target set.

		When ``visible`` is False the view is hidden for everyone. When True it is
		pushed to global (if show_overlays) or to each spectator/opt-in client, and
		explicitly hidden for everyone else so a racer who was spectating loses it.
		"""
		if view is None:
			return
		if not visible:
			try:
				await view.hide()
			except Exception:
				logger.exception('Knockout: failed to hide stream view')
			return

		targets = await self.stream_overlay_targets()
		if targets is None:
			try:
				await view.display()
			except Exception:
				logger.exception('Knockout: failed to display stream view globally')
			return

		try:
			online = list(self.instance.player_manager.online)
		except Exception:
			online = list(targets)

		# TemplateView takes ``player_logins`` -- a list of login STRINGS -- on both
		# display() and hide(). Not ``player``: that is the ListView signature, and on
		# a TemplateView it lands in display()'s **kwargs and is silently ignored (so
		# the overlay goes to everyone), while hide() has no **kwargs at all and
		# raises TypeError. One call each, rather than one per player.
		def _logins(players):
			return {str(login) for login in
				(getattr(entry, 'login', None) for entry in players) if login}

		target_logins = _logins(targets)
		online_logins = _logins(online)
		show = sorted(target_logins & online_logins)
		hide = sorted(online_logins - target_logins)
		try:
			if show:
				await view.display(player_logins=show)
			if hide:
				await view.hide(player_logins=hide)
		except Exception:
			logger.exception('Knockout: failed to push stream view')


	async def apply_mode_preset(self, script=None, settings=None, restart=True):
		"""Load a mode script and/or settings the same way BOTN does.

		Staging alone (set_next_script without RestartMap) only takes effect on the
		next map rotation, which is why ``//cup setup`` used to look like it did nothing
		during BOTN/TimeAttack. With ``restart=True`` (the default) we:

		1. Stage settings for the next script load when supported.
		2. ``set_next_script`` + ``RestartMap`` so the mode loads on the *current* map.
		3. Once the script is live, push settings again onto the running mode so values
		   that the mode reads at map-start (warm-up laps, shields, …) actually land.

		Returns True when a script was requested and confirmed live (or no script was
		requested and settings were applied). False when a requested script never loaded.
		"""
		import asyncio
		import time as _time

		settings = dict(settings or {})
		mm = self.instance.mode_manager

		# Carry a //ko fake field into the Knockout load. Only when a Knockout script
		# is actually being loaded: S_DebugBotsCount does not exist in TimeAttack, and
		# SetModeScriptSettings faults on the whole batch if any key is unknown.
		bots_wanted = int(getattr(self, 'fake_players_wanted', 0) or 0)
		if bots_wanted and 'knockout' in (script or '').lower():
			settings.setdefault('S_DebugBotsCount', bots_wanted)

		async def _apply(stage):
			if not settings:
				return
			try:
				if stage:
					fn = getattr(mm, 'update_next_settings', None)
					if fn is not None:
						await fn(settings)
						return
				await mm.update_settings(settings)
			except Exception:
				logger.exception(
					'Knockout: failed to apply mode settings (stage=%s)', stage)

		async def _current_script(refresh=True):
			try:
				return (await mm.get_current_script(refresh=refresh)) or ''
			except TypeError:
				try:
					return (await mm.get_current_script()) or ''
				except Exception:
					return ''
			except Exception:
				return ''

		# 8s was too tight in practice: RestartMap still has to run out the current
		# map's end-of-map sequence (score compute, ladder close, podium, unload)
		# before the new script loads, which on a live server took ~11s. Timing out
		# skips the post-load _apply(stage=False), so warm-up laps / shields /
		# S_DebugBotsCount never reach the running mode and the admin gets a "did not
		# load" warning about a script that loaded fine moments later.
		async def _await_script(wanted, timeout=25.0, interval=0.25):
			name = wanted.lower().rsplit('/', 1)[-1].split('.')[0]
			deadline = _time.time() + timeout
			while _time.time() < deadline:
				if name in (await _current_script()).lower():
					return True
				await asyncio.sleep(interval)
			logger.warning(
				'Knockout: mode script %s did not load within %ss', wanted, timeout)
			return False

		if script:
			await _apply(stage=True)
			try:
				await mm.set_next_script(script)
				if restart:
					await self.instance.gbx('RestartMap')
			except Exception:
				logger.exception('Knockout: failed to load mode script %s', script)
				return False
			if restart:
				ok = await _await_script(script)
				if ok:
					# Before the settings push: a freshly loaded script has XmlRpc
					# callbacks off (see enable_script_callbacks), and everything the
					# app does from here on assumes the mode can talk back.
					await self.enable_script_callbacks()
					if settings:
						await _apply(stage=False)
				return ok
			# Queued only: settings stay staged for the next map.
			return True

		# Settings only, no script change — push onto the running mode.
		if settings:
			await _apply(stage=False)
		return True

	def arm_cup_handoff_immediately(self):
		"""Set the cup handoff flag synchronously (see capture.record_match)."""
		self._force_ta_cup_next_map = True

	async def _on_cup_map_start_handoff(self, *args, **kwargs):
		"""Reload the post-cup map in TimeAttack when a queued script alone did not."""
		if not self._force_ta_cup_next_map:
			return
		self._force_ta_cup_next_map = False
		await self.return_to_timeattack()
		logger.info('Knockout: forced TimeAttack on the post-cup map')

	async def queue_timeattack(self):
		"""Queue TimeAttack for the NEXT map without restarting the current one. Used
		when a knockout map is ending (e.g. a cup just completed on its last map): the
		mode's own map-end advances to the next playlist map, which then loads in
		TimeAttack rather than continuing the knockout rotation."""
		# This is the usual end-of-cup path (capture arms it on the last map), so the
		# warm-up reset has to happen here too, not just in return_to_timeattack.
		await self.clear_knockout_warmup()
		try:
			await self.instance.mode_manager.set_next_script(TIMEATTACK_SCRIPT)
		except Exception:
			logger.exception('Knockout: failed to queue TimeAttack')

	def playlist_length(self, default=7):
		"""Number of maps in the server's current playlist (matchsettings), or
		``default`` if it can't be read. Used to size cups that should span the whole
		map list (the weekly BOTN, the Friday 'all maps' knockout cup)."""
		try:
			maps = self.instance.map_manager.maps
			count = len(maps) if maps else 0
			return count or default
		except Exception:
			logger.exception('Knockout: could not read playlist length')
			return default

	async def on_match_recorded(self, map_start_time, standings):
		"""Called by capture after a finished map's standings are persisted."""
		await self.cup.on_match_recorded(map_start_time, standings)
		await self.update_widget()
		# Season totals changed -> refresh the cache and repaint the HUD column.
		live = getattr(self, 'live', None)
		if live is not None:
			await live._refresh_season_points()
			await live._refresh_overlays()
		# A BOTN knockout map just finished: hand the night's result to the BOTN
		# controller so it returns to TimeAttack, advances to the next playlist map,
		# and re-arms tomorrow's cutoff. Runs after the cup update above so the BOTN
		# controller sees whether this map completed the weekly cup.
		botn = getattr(self, 'botn', None)
		if botn is not None and botn.active and botn.phase == 'knockout':
			await botn.on_knockout_recorded()

	async def on_cup_complete(self, cup):
		"""Called by the cup controller when a cup reaches its map count (e.g. a Friday
		knockout cup that has run through the whole playlist), and by ``//cup end``.

		Announces the winner in chat and opens standings for everyone online so admins
		do not need to remember ``/cup results``.
		"""
		await self.results.announce_top(cup)
		await self.results.show_all(cup)
		await self.hide_widget()
		# The cup just completed on its final knockout map; drop back to TimeAttack for
		# the next map so the server doesn't keep cycling knockout after the cup is done.
		# capture.record_match usually arms this before the first await; repeat here in
		# case standings were processed without passing through capture.
		self.arm_cup_handoff_immediately()
		await self.queue_timeattack()

	async def force_record_current_match(self, reason='manual'):
		"""Best-effort record the live knockout's standings through the normal capture
		path, for the ``//botn end`` / ``//cup end`` admin fallback.

		The mode normally drives this by emitting KOMatchStandings at map end; if a
		knockout is stuck (that callback never fires) the map never records and the
		cup/BOTN never advance. Here we synthesise standings from the live HUD state and
		push them through ``capture.record_match`` -- the SAME entry point the callback
		uses -- so the save, cup update, HUD refresh and BOTN/cup transition all run
		exactly as they would automatically. Returns True if standings were recorded.

		Note: this records the *result* in the plugin; the caller is still responsible
		for forcing the running mode off the stuck map (a RestartMap), since ManiaScript
		keeps looping regardless of what the plugin records."""
		live = getattr(self, 'live', None)
		if live is None:
			return False
		# Only synthesise a result while a Knockout mode is actually loaded, so stale
		# live state left over in another mode can never be recorded as a phantom map.
		if not getattr(live, 'is_knockout', False):
			logger.info('Knockout: force-record (%s) skipped -- not in a Knockout mode', reason)
			return False
		standings = live.synth_standings()
		if not standings:
			logger.info('Knockout: force-record (%s) found no live standings to save', reason)
			return False
		logger.info('Knockout: force-recording %d live standings (%s)', len(standings), reason)
		# False when the mode already reported this map: saying "saved" there would be
		# a lie, and re-storing it would count as an extra cup map.
		return bool(await self.capture.record_match(standings))

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
		self._show_widget = await self.setting_show_cup_widget.get_value()

		# Match HUD package (left panel, splits, finish countdown) uses the live
		# controller's effective gate: always on during cup/BOTN even if the global
		# show_match_hud setting is off. Stream overlays retarget via _refresh_overlays
		# (spectators / opt-in / everyone depending on show_overlays).
		live = getattr(self, 'live', None)
		if live is not None:
			try:
				hud_on = await live._match_hud_enabled()
			except Exception:
				hud_on = True
			self._match_hud_enabled = hud_on
			if not hud_on:
				await self._hide_view(getattr(self, 'hud', None))
				await self._hide_view(getattr(self, 'finish_countdown', None))
				await self._hide_view(getattr(self, 'splits', None))
			await live._refresh_overlays()
		else:
			self._match_hud_enabled = await self.setting_show_match_hud.get_value()

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
		# These three are registered without a parser, so the payload arrives as
		# `source` -- see callbacks.callback_login.
		login = callbacks.callback_login(kwargs)

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
			await self._handle_player_added(login)
		elif code == 'KOPlayerRemoved':
			await self._handle_player_removed(login)
		elif code == 'KOSendWinner':
			await self._handle_winner(login)

	async def _resolve_player_name(self, login):
		try:
			player = await self.instance.get_player(login=login)
			return player.name
		except Exception:
			return login

	async def _handle_player_added(self, login):
		show_join = await self.setting_show_join.get_value()
		if not show_join:
			return

		name = await self._resolve_player_name(login)
		msg = '$f90>>> $fff{name} $f90joined Knockout!'.format(name=name)
		await self.instance.chat(msg)

	async def _handle_player_removed(self, login):
		show_knockout = await self.setting_show_knockout.get_value()
		if not show_knockout:
			return

		name = await self._resolve_player_name(login)
		msg = '$f00>>> $fff{name} $f00was knocked out!'.format(name=name)
		await self.instance.chat(msg)

	async def _handle_winner(self, login):
		show_winner = await self.setting_show_winner.get_value()
		if not show_winner:
			return

		name = await self._resolve_player_name(login)
		self._match_winner = login
		msg = '$0f0>>> $fff{name} $0f0is the winner!'.format(name=name)
		await self.instance.chat(msg)

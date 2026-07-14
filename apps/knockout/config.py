import json
import logging
import os

logger = logging.getLogger(__name__)

# Bundled defaults ship with the app package so a plain apps/knockout/ deploy
# gets the friday/weekly/quick cups without a separate config step.
BUNDLED_PRESETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'presets.json')


class PresetConfig:
	"""
	Loads cup presets from a JSON file with three sections:

	* ``names``   - cup definitions (display name, linked preset/payout/scoremode/mapcount)
	* ``presets`` - mode script + script_settings to push via //cup setup / //cup on
	* ``payouts`` - planet amounts by placement
	"""

	def __init__(self, path=None):
		self.path = path
		self.names = {}
		self.presets = {}
		self.payouts = {}

	def load(self):
		self.names = {}
		self.presets = {}
		self.payouts = {}
		if not self.path:
			return False
		try:
			with open(self.path, 'r', encoding='utf-8') as handle:
				data = json.load(handle)
		except (OSError, ValueError) as exc:
			logger.warning('Knockout: could not load cup presets from %s: %s', self.path, exc)
			return False
		self.names = data.get('names', {}) or {}
		self.presets = data.get('presets', {}) or {}
		self.payouts = data.get('payouts', {}) or {}
		logger.info('Knockout: loaded %d cup name(s), %d preset(s), %d payout(s) from %s',
			len(self.names), len(self.presets), len(self.payouts), self.path)
		return True

	def get_cup(self, key):
		"""Return a names entry, or None."""
		return self.names.get(key)

	def get_preset(self, key):
		"""Return a presets entry (script + settings), or None."""
		return self.presets.get(key)

	def get_payout(self, key):
		"""Return a payout amount list, or an empty list."""
		return self.payouts.get(key, []) or []

	def resolve_mode_preset(self, cup_key):
		"""Return ``(preset_key, preset_dict)`` for a cup key, or ``(None, None)``.

		Looks up a named cup's linked ``preset`` field first (e.g. friday ->
		knockout_friday), then falls back to treating the key itself as a mode
		preset id (so ``//cup setup knockout_friday`` and ``//cup on friday`` both work).
		"""
		if not cup_key:
			return None, None
		cup_cfg = self.get_cup(cup_key) or {}
		preset_key = cup_cfg.get('preset') or cup_key
		preset = self.get_preset(preset_key)
		if not preset:
			return None, None
		return preset_key, preset

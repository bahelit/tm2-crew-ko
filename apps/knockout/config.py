import json
import logging

logger = logging.getLogger(__name__)


class PresetConfig:
	"""
	Loads cup presets from a JSON file with three sections:

	* ``names``   - cup definitions (display name, linked preset/payout/scoremode/mapcount)
	* ``presets`` - mode script + script_settings to push via //cup setup
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

"""
Points-by-placement tables used to turn each map's finishing order into cup
points. Selectable per cup via `//cup scoremode <id>`.
"""

SCORE_MODES = {
	'default': {
		'name': 'Default (10-8-6-5-4-3-2-1)',
		'points': [10, 8, 6, 5, 4, 3, 2, 1],
	},
	'f1': {
		'name': 'F1 (25-18-15-12-10-8-6-4-2-1)',
		'points': [25, 18, 15, 12, 10, 8, 6, 4, 2, 1],
	},
	'flat': {
		'name': 'Flat (1 point for the win)',
		'points': [1],
	},
	'survival': {
		'name': 'Survival (sum knockout points)',
		'points': [],
		'use_ko_points': True,
	},
}

DEFAULT_MODE = 'default'


def get_score_mode(mode_id):
	"""Return the score-mode definition, falling back to the default."""
	return SCORE_MODES.get(mode_id, SCORE_MODES[DEFAULT_MODE])


def is_valid(mode_id):
	return mode_id in SCORE_MODES


def cup_points(mode_id, placement, ko_points=0):
	"""
	Cup points for a finish.

	:param mode_id:    Score mode id.
	:param placement:  Zero-based placement on the map (0 = winner).
	:param ko_points:  The player's raw knockout survival score on the map.
	"""
	mode = get_score_mode(mode_id)
	if mode.get('use_ko_points'):
		return ko_points
	table = mode['points']
	if 0 <= placement < len(table):
		return table[placement]
	return 0


def mode_names():
	"""Return ``{id: display name}`` for help/listing."""
	return {mode_id: mode['name'] for mode_id, mode in SCORE_MODES.items()}

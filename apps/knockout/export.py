import csv
import io
import logging
import os
import re

logger = logging.getLogger(__name__)


def _strip_formatting(nickname):
	"""Remove ManiaPlanet $-formatting codes for plain-text output."""
	return re.sub(r'\$(?:[0-9a-fA-F]{1,3}|[lhpLHP]\[[^\]]*\]|[a-zA-Z<>])', '', nickname or '')


def build_csv(cup, standings):
	"""Return cup standings as a CSV string."""
	buffer = io.StringIO()
	writer = csv.writer(buffer)
	writer.writerow(['rank', 'login', 'nickname', 'cup_points', 'ko_points', 'maps'])
	for rank, row in enumerate(standings, 1):
		writer.writerow([
			rank, row['login'], _strip_formatting(row['nickname']),
			row['cup_points'], row['ko_points'], row['maps'],
		])
	return buffer.getvalue()


def build_discord(cup, standings):
	"""Return cup standings as a Discord-friendly markdown code block."""
	lines = [
		'**{} — edition {}**'.format(_strip_formatting(cup.name), cup.edition),
		'```',
		'{:>3}  {:<24} {:>7} {:>6} {:>4}'.format('#', 'Player', 'CupPts', 'KOPts', 'Map'),
	]
	for rank, row in enumerate(standings, 1):
		lines.append('{:>3}  {:<24} {:>7} {:>6} {:>4}'.format(
			rank, _strip_formatting(row['nickname'])[:24],
			row['cup_points'], row['ko_points'], row['maps'],
		))
	lines.append('```')
	return '\n'.join(lines)


def _filename(cup, extension):
	safe_key = re.sub(r'[^0-9A-Za-z_-]+', '_', cup.cup_key or 'cup')
	return 'knockout_cup_{}_e{}.{}'.format(safe_key, cup.edition, extension)


def write_exports(cup, standings, directory=''):
	"""
	Write CSV and Discord-markdown files for a cup. Returns the list of paths
	written. `directory` defaults to the current working directory.
	"""
	directory = directory or '.'
	written = []
	for extension, builder in (('csv', build_csv), ('md', build_discord)):
		path = os.path.join(directory, _filename(cup, extension))
		try:
			with open(path, 'w', encoding='utf-8') as handle:
				handle.write(builder(cup, standings))
			written.append(path)
		except OSError as exc:
			logger.warning('Knockout: could not write export %s: %s', path, exc)
	return written

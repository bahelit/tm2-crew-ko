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


def format_completion_messages(standings, count=3):
	"""
	Build public chat lines for a finished cup (winner + podium).

	Pure helper so unit tests can cover wording without PyPlanet. The cup
	controller already emits the ``Cup … complete!`` line before these.

	Returns a list of ManiaPlanet-coloured chat strings. Empty standings yield a
	single explicit "no results" line so end never goes silent.
	"""
	if not standings:
		return [
			'$f00>>> Cup complete but no map results were recorded.',
		]

	lines = []
	winner = standings[0]
	lines.append(
		'$0f0>>> $fffWinner: {}$z $0f0— $fff{}$0f0 pts'.format(
			winner.get('nickname') or winner.get('login') or '?',
			winner.get('cup_points', 0),
		)
	)

	medals = ['$ff0 1.', '$bbb 2.', '$d80 3.']
	for index, row in enumerate(standings[: max(0, int(count))]):
		label = medals[index] if index < len(medals) else '   {}.'.format(index + 1)
		lines.append(
			'{} $fff{}$z $bbb- {} pts'.format(
				label,
				row.get('nickname') or row.get('login') or '?',
				row.get('cup_points', 0),
			)
		)

	lines.append('$bbb>>> Full standings: $fff/cup results')
	return lines


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

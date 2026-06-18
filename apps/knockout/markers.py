import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


def _format_offset(seconds):
	"""Render a stream-relative offset as H:MM:SS."""
	seconds = int(max(0, seconds))
	hours, rem = divmod(seconds, 3600)
	minutes, secs = divmod(rem, 60)
	return '{:d}:{:02d}:{:02d}'.format(hours, minutes, secs)


def format_line(event, detail='', stream_start=None, now=None):
	"""
	Build one marker line. Exposed as a module function so it can be unit-tested
	without a running server:

		<iso wall-clock>\t<stream offset or '-'>\t<event>\t<detail>
	"""
	now = now if now is not None else time.time()
	wall = datetime.fromtimestamp(now).isoformat(timespec='seconds')
	offset = _format_offset(now - stream_start) if stream_start is not None else '-'
	detail = (detail or '').replace('\t', ' ').replace('\n', ' ')
	return '{}\t{}\t{}\t{}'.format(wall, offset, event, detail)


class MarkersController:
	"""
	Appends timestamped highlight markers to a file so a livestream VOD can be
	clipped quickly afterwards. Off by default; enabled via settings. The
	stream-relative clock starts at //ko streamstart.
	"""

	def __init__(self, app):
		self.app = app
		self.instance = app.instance
		self.enabled = False
		self.path = None
		self.stream_start = None

	async def on_start(self):
		self.enabled = await self.app.setting_vod_markers_enabled.get_value()
		self.path = (await self.app.setting_vod_markers_path.get_value()) or None

	async def set_stream_start(self):
		"""Mark t=0 for stream-relative offsets and write a stream_start marker."""
		self.stream_start = time.time()
		await self.log('stream_start', '')
		return self.stream_start

	async def log(self, event, detail=''):
		if not self.enabled or not self.path:
			return
		line = format_line(event, detail, self.stream_start)
		try:
			with open(self.path, 'a', encoding='utf-8') as handle:
				handle.write(line + '\n')
		except OSError as exc:
			logger.warning('Knockout: could not write VOD marker to %s: %s', self.path, exc)

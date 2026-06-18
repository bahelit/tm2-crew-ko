"""Work around a PyPlanet template-loader caching flaw that breaks apps loaded
after boot via a mode change.

PyPlanet's jinja prefix loader (``pyplanet.core.ui.loader._PyPlanetLoader``)
builds its ``app_label -> templates/`` mapping lazily *once*, the first time any
template renders, and caches it forever. Apps that aren't loaded at that moment
are permanently missing from the mapping, so every one of their templates raises
``TemplateNotFound``.

This bites mode-gated contrib apps. When the server boots in a mode an app does
not support (e.g. our Crew Knockout mode, which ``live_rankings.is_mode_supported``
rejects), ``apps.check()`` unloads that app before the loader mapping is frozen.
A later mode switch (the BOTD flow moves the server to TimeAttack) reloads the app
and runs its ``on_start``, but the cached loader has no prefix for it -- so
``live_rankings``'s ``on_start`` dies on ``widget.display()``, leaving its
``race_widget`` as ``None`` and crashing every later signal it handles
(``scores``, ``podium_start``, ...).

The fix: make the loader self-heal. On a miss, rebuild the mapping from the
currently-loaded apps and retry once. ``get_mapping()`` reads live from
``Controller.instance.apps.apps``, so a rebuild picks up anything loaded since
boot. This fixes every late-loaded app, not just ``live_rankings``.

Idempotent and patches the class (so it applies to the cached singleton too), so
it is safe to call from any app's ``on_start``.
"""

from jinja2 import TemplateNotFound

from pyplanet.core.ui import loader as _loader


def install_selfhealing_loader():
	cls = _loader._PyPlanetLoader
	if getattr(cls, '_knockout_selfhealing', False):
		return

	_orig_get_loader = cls.get_loader

	def get_loader(self, template):
		try:
			return _orig_get_loader(self, template)
		except TemplateNotFound:
			# An app may have been (re)loaded after the mapping was frozen.
			# Rebuild from the live app registry and retry once.
			self.mapping = self.get_mapping()
			return _orig_get_loader(self, template)

	cls.get_loader = get_loader
	cls._knockout_selfhealing = True

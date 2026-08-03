"""
Unit tests for cup preset loading (bundled defaults + resolve_mode_preset).

Run with:  python -m pytest tests/test_knockout_presets.py
       or:  python tests/test_knockout_presets.py
"""
import importlib.util
import json
import os
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_KO = os.path.join(_HERE, '..', 'apps', 'knockout')


def _load(name, filename):
	spec = importlib.util.spec_from_file_location(name, os.path.join(_KO, filename))
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


config = _load('ko_config', 'config.py')


def test_bundled_presets_path_exists():
	assert os.path.isfile(config.BUNDLED_PRESETS_PATH)
	assert config.BUNDLED_PRESETS_PATH.endswith('presets.json')


def test_bundled_presets_load_friday():
	pc = config.PresetConfig(config.BUNDLED_PRESETS_PATH)
	assert pc.load() is True
	assert 'friday' in pc.names
	assert 'knockout_friday' in pc.presets
	friday = pc.get_cup('friday')
	assert friday['name'] == 'Friday Knockout Cup'
	assert friday['preset'] == 'knockout_friday'
	assert friday['mapcount'] == 'all'
	preset = pc.get_preset('knockout_friday')
	assert 'Knockout.Script.txt' in preset['script']
	assert preset['settings'].get('S_EnableShields') is True


def test_resolve_mode_preset_from_cup_key():
	pc = config.PresetConfig(config.BUNDLED_PRESETS_PATH)
	pc.load()
	key, preset = pc.resolve_mode_preset('friday')
	assert key == 'knockout_friday'
	assert preset['settings']['S_WarmUpNb'] == 2
	assert preset['settings']['S_WarmUpDuration'] == 120


def test_resolve_mode_preset_from_preset_id():
	pc = config.PresetConfig(config.BUNDLED_PRESETS_PATH)
	pc.load()
	key, preset = pc.resolve_mode_preset('knockout_friday')
	assert key == 'knockout_friday'
	assert preset is not None


def test_resolve_mode_preset_unknown():
	pc = config.PresetConfig(config.BUNDLED_PRESETS_PATH)
	pc.load()
	key, preset = pc.resolve_mode_preset('nope')
	assert key is None
	assert preset is None


def test_load_missing_path():
	pc = config.PresetConfig('/no/such/presets.json')
	assert pc.load() is False
	assert pc.names == {}
	assert pc.presets == {}


def test_load_empty_path():
	pc = config.PresetConfig(None)
	assert pc.load() is False


def test_load_custom_override():
	payload = {
		'names': {'custom': {'name': 'Custom', 'preset': 'p1', 'mapcount': 2}},
		'presets': {'p1': {'script': 'Modes/TrackMania/Knockout.Script.txt', 'settings': {}}},
		'payouts': {},
	}
	with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
		json.dump(payload, handle)
		path = handle.name
	try:
		pc = config.PresetConfig(path)
		assert pc.load() is True
		assert pc.get_cup('custom')['name'] == 'Custom'
		key, preset = pc.resolve_mode_preset('custom')
		assert key == 'p1'
		assert 'Knockout' in preset['script']
	finally:
		os.unlink(path)


if __name__ == '__main__':
	failed = 0
	for name, fn in sorted(globals().items()):
		if not name.startswith('test_') or not callable(fn):
			continue
		try:
			fn()
			print('ok   ', name)
		except Exception as exc:
			failed += 1
			print('FAIL ', name, '—', exc)
	raise SystemExit(1 if failed else 0)

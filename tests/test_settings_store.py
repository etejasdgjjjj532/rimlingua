"""User preferences: folder settings, defaults, autosave, export/import and a kept-aside corrupt file."""
import json
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.settings import SettingsStore, settings_summary


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'settings.json'

    def test_new_keys_have_safe_defaults(self):
        data = SettingsStore(self.path).data
        self.assertEqual(data['workshop_folder'], '')
        self.assertEqual(data['mods_folder'], '')
        self.assertEqual(data['external_mod_folders'], [])
        self.assertEqual(data['mods_config_path'], '')
        self.assertEqual(data['default_translator'], '')
        self.assertEqual(data['default_license'], '')
        self.assertEqual(data['default_languages'], ['Japanese'])
        self.assertEqual(data['cache_directory'], '')
        self.assertEqual(data['autosave_seconds'], 60)

    def test_invalid_values_fall_back_to_defaults(self):
        self.path.write_text(json.dumps({
            'workshop_folder': 3, 'external_mod_folders': ['/a', 5], 'default_languages': ['Klingon'],
            'autosave_seconds': 2, 'default_translator': ['x'], 'cache_directory': None}), encoding='utf-8')
        data = SettingsStore(self.path).data
        self.assertEqual(data['workshop_folder'], '')
        self.assertEqual(data['external_mod_folders'], [])
        self.assertEqual(data['default_languages'], ['Japanese'])
        self.assertEqual(data['autosave_seconds'], 60)
        self.assertEqual(data['default_translator'], '')
        self.assertEqual(data['cache_directory'], '')

    def test_autosave_zero_means_off_and_bounds_are_kept(self):
        self.path.write_text('{"autosave_seconds": 0}', encoding='utf-8')
        self.assertEqual(SettingsStore(self.path).data['autosave_seconds'], 0)
        self.path.write_text('{"autosave_seconds": 99999}', encoding='utf-8')
        self.assertEqual(SettingsStore(self.path).data['autosave_seconds'], 60)

    def test_corrupt_file_is_kept_aside_and_defaults_are_used(self):
        self.path.write_text('{not json', encoding='utf-8')
        store = SettingsStore(self.path)
        self.assertTrue(store.load_error)
        self.assertIsNotNone(store.kept_aside)
        self.assertEqual(store.kept_aside.read_text(encoding='utf-8'), '{not json')
        self.assertEqual(store.data['ui_language'], 'system')
        store.save()
        self.assertEqual(store.kept_aside.read_text(encoding='utf-8'), '{not json')

    def test_non_object_file_is_kept_aside_too(self):
        self.path.write_text('[1, 2]', encoding='utf-8')
        store = SettingsStore(self.path)
        self.assertIsNotNone(store.kept_aside)
        self.assertTrue(store.kept_aside.is_file())

    def test_export_and_import_round_trip_preferences_only(self):
        store = SettingsStore(self.path)
        store.data.update(default_translator='Goma', external_mod_folders=['/mods/a'], autosave_seconds=120,
                          recent_projects=['/private/project.json'])
        exported = self.root / 'exported.json'
        store.export_to(exported)
        written = json.loads(exported.read_text(encoding='utf-8'))
        self.assertNotIn('recent_projects', written)
        self.assertNotIn('daily_counts', written)
        other = SettingsStore(self.root / 'other.json')
        other.data['recent_projects'] = ['/keep/me.json']
        other.import_from(exported)
        self.assertEqual(other.data['default_translator'], 'Goma')
        self.assertEqual(other.data['external_mod_folders'], ['/mods/a'])
        self.assertEqual(other.data['autosave_seconds'], 120)
        self.assertEqual(other.data['recent_projects'], ['/keep/me.json'])
        self.assertEqual(json.loads((self.root / 'other.json').read_text(encoding='utf-8'))['default_translator'], 'Goma')

    def test_import_rejects_a_file_that_is_not_settings(self):
        bad = self.root / 'bad.json'
        bad.write_text('[]', encoding='utf-8')
        store = SettingsStore(self.path)
        with self.assertRaises(ValueError):
            store.import_from(bad)

    def test_import_validates_values(self):
        imported = self.root / 'in.json'
        imported.write_text('{"autosave_seconds": "fast", "default_translator": "A"}', encoding='utf-8')
        store = SettingsStore(self.path)
        store.import_from(imported)
        self.assertEqual(store.data['autosave_seconds'], 60)
        self.assertEqual(store.data['default_translator'], 'A')

    def test_summary_masks_paths(self):
        store = SettingsStore(self.path)
        secret = str(self.root / 'goma-secret-folder')
        store.data.update(workshop_folder=secret, external_mod_folders=[secret, '/nope'], game_paths=[secret],
                          mods_config_path=secret, cache_directory=secret, default_translator='Goma Person')
        summary = settings_summary(store.data)
        self.assertNotIn('goma-secret-folder', summary)
        self.assertNotIn('Goma Person', summary)
        self.assertIn('workshop_folder', summary)
        self.assertIn('external_mod_folders: 2', summary)
        self.assertIn('autosave_seconds: 60', summary)


if __name__ == '__main__':
    unittest.main()

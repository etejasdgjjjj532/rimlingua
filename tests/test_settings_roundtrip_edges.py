"""Settings export/import edge cases: full roundtrip, unknown keys, wrong types, nesting, empty and broken files."""
import json
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.settings import DEFAULTS, NOT_EXPORTED, SettingsStore


# Valid, non-default value for every key in DEFAULTS.
NON_DEFAULT = {
    'ui_language': 'en', 'font_size': 14, 'tutorial_dismissed': True,
    'recent_projects': ['/private/project.json'], 'favorite_sources': ['/fav/source'],
    'game_paths': ['/games/rimworld'], 'game_library': '/library', 'inspect_metadata': False,
    'release_repository': 'owner/repo', 'check_updates': True, 'theme_mode': 'dark',
    'show_tree': False, 'reduce_motion': True, 'daily_counts': {'2026-11-21': 3},
    'workshop_folder': '/workshop', 'mods_folder': '/mods', 'external_mod_folders': ['/extra'],
    'mods_config_path': '/config/ModsConfig.xml', 'default_translator': 'テスト翻訳者',
    'default_license': 'MIT', 'default_languages': ['Japanese', 'English'],
    'cache_directory': '/cache', 'autosave_seconds': 300, 'backup_generations': 5,
}


class SettingsRoundtripEdgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def store(self, name='settings.json'):
        return SettingsStore(self.root / name)

    def write(self, text, name='in.json'):
        path = self.root / name
        path.write_text(text, encoding='utf-8')
        return path

    def test_fixture_covers_every_default_key(self):
        self.assertEqual(set(NON_DEFAULT), set(DEFAULTS))

    def test_export_then_import_roundtrips_every_portable_key(self):
        source = self.store('source.json')
        source.data.update(NON_DEFAULT)
        source.export_to(self.root / 'out.json')
        written = json.loads((self.root / 'out.json').read_text(encoding='utf-8'))
        for key in NOT_EXPORTED:
            self.assertNotIn(key, written)
        target = self.store('target.json')
        target.data['recent_projects'] = ['/keep/me.json']
        target.data['daily_counts'] = {'2026-01-01': 1}
        target.import_from(self.root / 'out.json')
        for key in DEFAULTS:
            if key in NOT_EXPORTED:
                continue
            self.assertEqual(target.data[key], NON_DEFAULT[key], key)
        self.assertEqual(target.data['recent_projects'], ['/keep/me.json'])
        self.assertEqual(target.data['daily_counts'], {'2026-01-01': 1})

    def test_roundtrip_keeps_the_saved_file_loadable_by_a_new_store(self):
        source = self.store('source.json')
        source.data.update(NON_DEFAULT)
        source.export_to(self.root / 'out.json')
        target = self.store('target.json')
        target.import_from(self.root / 'out.json')
        reloaded = SettingsStore(self.root / 'target.json')
        self.assertEqual(reloaded.load_error, '')
        self.assertEqual(reloaded.data['default_translator'], 'テスト翻訳者')
        self.assertEqual(reloaded.data['autosave_seconds'], 300)

    def test_unknown_keys_are_ignored_and_not_written_back(self):
        path = self.write(json.dumps({
            'font_size': 16, 'future_feature': {'enabled': True}, 'another_unknown': [1, 2],
            'recent_projects': ['/from/file.json'], 'daily_counts': {'2026-11-21': 99},
        }, ensure_ascii=False))
        target = self.store()
        target.import_from(path)
        self.assertEqual(target.data['font_size'], 16)
        self.assertNotIn('future_feature', target.data)
        self.assertNotIn('another_unknown', target.data)
        self.assertEqual(target.data['recent_projects'], [])
        self.assertEqual(target.data['daily_counts'], {})
        saved = json.loads((self.root / 'settings.json').read_text(encoding='utf-8'))
        self.assertNotIn('future_feature', saved)
        self.assertNotIn('another_unknown', saved)

    def test_file_with_only_unknown_keys_changes_nothing(self):
        target = self.store()
        before = json.loads(json.dumps(target.data))
        target.import_from(self.write('{"nope": 1}'))
        self.assertEqual(target.data, before)

    def test_wrong_types_fall_back_to_defaults(self):
        wrong = {
            'ui_language': 'fr', 'font_size': '14', 'tutorial_dismissed': 'yes',
            'inspect_metadata': 0, 'check_updates': None, 'theme_mode': 'pink', 'show_tree': 1,
            'reduce_motion': 'true', 'autosave_seconds': 60.0, 'backup_generations': '3',
            'workshop_folder': 5, 'game_library': ['/x'], 'release_repository': None,
            'external_mod_folders': 'C:/mods', 'game_paths': 7, 'favorite_sources': {'a': 1},
            'default_languages': 'Japanese', 'default_license': False,
        }
        target = self.store()
        target.import_from(self.write(json.dumps(wrong)))
        for key in wrong:
            self.assertEqual(target.data[key], DEFAULTS[key], key)
            self.assertIs(type(target.data[key]), type(DEFAULTS[key]), key)  # 1 == True would hide a wrong type

    def test_bool_is_not_accepted_as_an_integer_setting(self):
        target = self.store()
        target.import_from(self.write('{"font_size": true, "autosave_seconds": true, "backup_generations": false}'))
        self.assertEqual(target.data['font_size'], DEFAULTS['font_size'])
        self.assertEqual(target.data['autosave_seconds'], DEFAULTS['autosave_seconds'])
        self.assertEqual(target.data['backup_generations'], DEFAULTS['backup_generations'])

    def test_integer_bounds_are_inclusive_and_out_of_range_values_reset(self):
        target = self.store()
        target.import_from(self.write('{"font_size": 8, "backup_generations": 9999, "autosave_seconds": 3600}'))
        self.assertEqual(target.data['font_size'], 8)
        self.assertEqual(target.data['backup_generations'], 9999)
        self.assertEqual(target.data['autosave_seconds'], 3600)
        target.import_from(self.write('{"font_size": 7, "backup_generations": 10000, "autosave_seconds": 3601}'))
        self.assertEqual(target.data['font_size'], DEFAULTS['font_size'])
        self.assertEqual(target.data['backup_generations'], DEFAULTS['backup_generations'])
        self.assertEqual(target.data['autosave_seconds'], DEFAULTS['autosave_seconds'])

    def test_nested_values_inside_known_keys_are_rejected(self):
        nested = {
            'external_mod_folders': [['/a']], 'favorite_sources': [{'path': '/b'}],
            'game_paths': [None], 'default_languages': [['Japanese']],
            'default_translator': {'name': 'Goma'}, 'cache_directory': ['/c'],
        }
        target = self.store()
        target.import_from(self.write(json.dumps(nested)))
        self.assertEqual(target.data['external_mod_folders'], [])
        self.assertEqual(target.data['favorite_sources'], [])
        self.assertEqual(target.data['game_paths'], [])
        self.assertEqual(target.data['default_languages'], ['Japanese'])
        self.assertEqual(target.data['default_translator'], '')
        self.assertEqual(target.data['cache_directory'], '')

    def test_deeply_nested_unknown_value_does_not_break_import(self):
        payload = '{"unknown": ' + '[' * 200 + ']' * 200 + ', "font_size": 13}'
        target = self.store()
        target.import_from(self.write(payload))
        self.assertEqual(target.data['font_size'], 13)
        self.assertNotIn('unknown', target.data)

    def test_excessively_nested_file_raises_value_error_and_keeps_settings(self):
        target = self.store()
        target.data['font_size'] = 13
        depth = 200000
        path = self.write('{"x": ' + '[' * depth + ']' * depth + '}')
        with self.assertRaises(ValueError):
            target.import_from(path)
        self.assertEqual(target.data['font_size'], 13)

    def test_empty_file_raises_value_error_and_keeps_settings(self):
        target = self.store()
        target.data['font_size'] = 13
        with self.assertRaises(ValueError):
            target.import_from(self.write(''))
        self.assertEqual(target.data['font_size'], 13)
        self.assertFalse((self.root / 'settings.json').exists())

    def test_invalid_json_raises_value_error_and_does_not_touch_the_saved_file(self):
        target = self.store()
        target.save()
        saved_before = (self.root / 'settings.json').read_bytes()
        for text in ('{not json', '{"font_size": 14', '{"font_size": 14,}', 'NaN-ish'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    target.import_from(self.write(text))
                self.assertEqual(target.data['font_size'], DEFAULTS['font_size'])
                self.assertEqual((self.root / 'settings.json').read_bytes(), saved_before)

    def test_non_object_json_raises_value_error(self):
        target = self.store()
        for text in ('[]', '"text"', 'null', '42', 'true', '[{"font_size": 14}]'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    target.import_from(self.write(text))
                self.assertEqual(target.data['font_size'], DEFAULTS['font_size'])

    def test_undecodable_bytes_raise_value_error(self):
        path = self.root / 'binary.json'
        path.write_bytes(b'{"default_translator": "\xff\xfe"}')
        target = self.store()
        with self.assertRaises(ValueError):
            target.import_from(path)
        self.assertEqual(target.data['default_translator'], '')

    def test_oversized_file_is_rejected_before_parsing(self):
        path = self.root / 'huge.json'
        path.write_text('{"font_size": 14}' + ' ' * (1024 * 1024), encoding='utf-8')
        target = self.store()
        with self.assertRaises(ValueError):
            target.import_from(path)
        self.assertEqual(target.data['font_size'], DEFAULTS['font_size'])

    def test_missing_file_raises_os_error_for_the_gui_to_report(self):
        with self.assertRaises(OSError):
            self.store().import_from(self.root / 'absent.json')

    def test_japanese_text_survives_export_as_utf8(self):
        source = self.store('source.json')
        source.data['default_translator'] = '日本語の翻訳者'
        source.export_to(self.root / 'out.json')
        raw = (self.root / 'out.json').read_bytes()
        self.assertIn('日本語の翻訳者'.encode('utf-8'), raw)
        target = self.store('target.json')
        target.import_from(self.root / 'out.json')
        self.assertEqual(target.data['default_translator'], '日本語の翻訳者')

    def test_import_saves_the_normalized_values_to_disk(self):
        target = self.store()
        target.import_from(self.write('{"font_size": "huge", "external_mod_folders": [1]}'))
        saved = json.loads((self.root / 'settings.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['font_size'], DEFAULTS['font_size'])
        self.assertEqual(saved['external_mod_folders'], [])

    def test_unhashable_ui_language_is_normalized(self):
        target = self.store()
        target.import_from(self.write('{"ui_language": ["ja"]}'))
        self.assertEqual(target.data['ui_language'], 'system')

    def test_unhashable_theme_mode_is_normalized(self):
        target = self.store()
        target.import_from(self.write('{"theme_mode": {"mode": "dark"}}'))
        self.assertEqual(target.data['theme_mode'], 'system')

    def test_startup_survives_unhashable_ui_language_in_saved_file(self):
        self.write('{"ui_language": ["ja"]}', name='settings.json')
        store = SettingsStore(self.root / 'settings.json')
        self.assertEqual(store.data['ui_language'], 'system')


if __name__ == '__main__':
    unittest.main()

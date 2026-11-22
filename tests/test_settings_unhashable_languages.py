"""Malformed (unhashable) language lists must fall back to the default, never raise."""
import json
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.settings import SettingsStore


class UnhashableLanguageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_import_of_nested_list_language_falls_back_to_default(self):
        store = SettingsStore(self.root / 'settings.json')
        source = self.root / 'in.json'
        source.write_text(json.dumps({'default_languages': [[]]}), encoding='utf-8')
        store.import_from(source)
        self.assertEqual(store.data['default_languages'], ['Japanese'])

    def test_load_of_dict_element_falls_back_to_default(self):
        path = self.root / 'settings.json'
        path.write_text(json.dumps({'default_languages': [{}, 'Japanese']}), encoding='utf-8')
        self.assertEqual(SettingsStore(path).data['default_languages'], ['Japanese'])

    def test_deeply_nested_import_is_a_value_error(self):
        store = SettingsStore(self.root / 'settings.json')
        source = self.root / 'deep.json'
        source.write_text('{"default_translator":' + '[' * 100000 + ']' * 100000 + '}', encoding='utf-8')
        with self.assertRaises(ValueError):
            store.import_from(source)


if __name__ == '__main__':
    unittest.main()

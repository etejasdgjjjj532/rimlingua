"""The interface language defaults to the OS language; English wins when the OS list holds both."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rimworld_translator.settings import DEFAULTS, SettingsStore, normalize, resolve_ui_language


class ResolveUiLanguageTests(unittest.TestCase):
    def test_explicit_choices_ignore_the_os(self):
        self.assertEqual(resolve_ui_language('ja', ['en-US']), 'ja')
        self.assertEqual(resolve_ui_language('en', ['ja-JP']), 'en')

    def test_system_follows_a_japanese_os(self):
        self.assertEqual(resolve_ui_language('system', ['ja-JP', 'ja']), 'ja')
        self.assertEqual(resolve_ui_language('system', ['ja_JP']), 'ja')

    def test_system_follows_an_english_os(self):
        self.assertEqual(resolve_ui_language('system', ['en-US', 'en']), 'en')

    def test_english_wins_when_both_languages_are_listed(self):
        self.assertEqual(resolve_ui_language('system', ['ja-JP', 'ja', 'en-US', 'en']), 'en')
        self.assertEqual(resolve_ui_language('system', ['en-GB', 'ja']), 'en')

    def test_other_languages_fall_back_to_english(self):
        self.assertEqual(resolve_ui_language('system', ['de-DE', 'de']), 'en')
        self.assertEqual(resolve_ui_language('system', ['C']), 'en')
        self.assertEqual(resolve_ui_language('system', []), 'en')

    def test_an_unknown_stored_value_behaves_like_system(self):
        self.assertEqual(resolve_ui_language('fr', ['ja-JP']), 'ja')
        self.assertEqual(resolve_ui_language(None, ['ja-JP']), 'ja')

    def test_the_pinned_os_language_replaces_the_os_query(self):
        for pinned, expected in (('en-US', 'en'), ('ja-JP,ja', 'ja'), ('ja-JP, en-US', 'en'), ('de-DE', 'en')):
            with patch.dict(os.environ, {'RW_TRANSLATOR_SYSTEM_LANGUAGES': pinned}):
                self.assertEqual(resolve_ui_language('system'), expected, pinned)

    def test_a_blank_pin_is_ignored_and_the_os_is_asked(self):
        with patch.dict(os.environ, {'RW_TRANSLATOR_SYSTEM_LANGUAGES': '  '}):
            self.assertIn(resolve_ui_language('system'), {'ja', 'en'})

    def test_an_explicit_choice_beats_the_pin(self):
        with patch.dict(os.environ, {'RW_TRANSLATOR_SYSTEM_LANGUAGES': 'en-US'}):
            self.assertEqual(resolve_ui_language('ja'), 'ja')

    def test_the_real_os_query_returns_a_supported_language(self):
        self.assertIn(resolve_ui_language('system'), {'ja', 'en'})


class StoredLanguageTests(unittest.TestCase):
    def test_default_follows_the_os(self):
        self.assertEqual(DEFAULTS['ui_language'], 'system')

    def test_valid_values_are_kept(self):
        for value in ('system', 'ja', 'en'):
            self.assertEqual(normalize({**DEFAULTS, 'ui_language': value})['ui_language'], value)

    def test_unsupported_or_unhashable_values_fall_back_to_system(self):
        for value in ('fr', '', None, 3, ['ja'], {'a': 1}):
            self.assertEqual(normalize({**DEFAULTS, 'ui_language': value})['ui_language'], 'system', value)

    def test_import_of_a_nested_language_does_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SettingsStore(root / 'settings.json')
            source = root / 'incoming.json'
            source.write_text(json.dumps({'ui_language': ['en']}), encoding='utf-8')
            store.import_from(source)
            self.assertEqual(store.data['ui_language'], 'system')


if __name__ == '__main__':
    unittest.main()

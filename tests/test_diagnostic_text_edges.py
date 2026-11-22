"""Edge inputs for diagnostic_text.explain and its helpers: empty, None-like, long, multi-line and Japanese text."""
import dataclasses
import unittest

from rimworld_translator import diagnostic_text
from rimworld_translator.diagnostic_text import PlainDiagnostic, explain, known_codes, technical_label

GENERIC_JA_TITLE = '確認が必要な診断があります'
GENERIC_EN_TITLE = 'A diagnostic needs a look'


class EmptyAndNoneInputTests(unittest.TestCase):
    def test_empty_dict_falls_back_to_generic_japanese_text(self):
        plain = explain({}, 'ja')
        self.assertEqual(plain.code, '')
        self.assertEqual(plain.title, GENERIC_JA_TITLE)
        self.assertEqual(plain.technical, '')

    def test_empty_dict_in_english_uses_english_generic_text(self):
        plain = explain({}, 'en')
        self.assertEqual(plain.title, GENERIC_EN_TITLE)
        self.assertNotEqual(plain.action, '')

    def test_none_values_are_treated_as_empty(self):
        plain = explain({'code': None, 'message': None, 'suggestion': None}, 'ja')
        self.assertEqual((plain.code, plain.title, plain.technical), ('', GENERIC_JA_TITLE, ''))

    def test_whitespace_only_message_is_not_japanese_and_stays_generic(self):
        plain = explain({'message': '   \n\t  '}, 'en')
        self.assertEqual(plain.title, GENERIC_EN_TITLE)
        # The whitespace is kept in technical details, unchanged.
        self.assertEqual(plain.technical, '   \n\t  ')

    def test_known_code_with_empty_message_still_gets_its_table_title(self):
        plain = explain({'code': 'loadfolders', 'message': ''}, 'ja')
        self.assertEqual(plain.title, 'LoadFolders.xml を読み取れませんでした')
        self.assertEqual(plain.technical, 'code: loadfolders')

    def test_known_code_with_unmatched_message_replaces_parameter_with_ellipsis(self):
        plain = explain({'code': 'unknown-condition', 'message': 'foo'}, 'en')
        self.assertIn('"…"', plain.title)
        self.assertNotIn('{n}', plain.title)

    def test_explicit_code_wins_over_codeless_text_recognition(self):
        plain = explain({'code': 'unknown-code-x', 'message': '3 additional distinct warnings omitted'}, 'ja')
        self.assertEqual(plain.code, 'unknown-code-x')
        self.assertEqual(plain.title, GENERIC_JA_TITLE)

    def test_empty_code_with_codeless_warning_text_is_recognised(self):
        plain = explain({'code': '', 'message': '3 additional distinct warnings omitted'}, 'ja')
        self.assertEqual(plain.code, 'warnings-omitted')
        self.assertEqual(plain.title, '表示しきれない診断がほかに 3 件あります')

    def test_unknown_language_is_treated_as_english(self):
        plain = explain({'code': 'loadfolders', 'message': 'x'}, 'fr')
        self.assertEqual(plain.title, 'Could not read LoadFolders.xml')
        self.assertEqual(explain({}, 'fr').title, GENERIC_EN_TITLE)


class LongInputTests(unittest.TestCase):
    def test_very_long_unknown_message_is_kept_whole_in_technical_details(self):
        message = 'x' * 50000
        plain = explain({'code': 'brand-new-thing', 'message': message}, 'ja')
        self.assertEqual(plain.technical, 'code: brand-new-thing\n' + message)
        self.assertEqual(plain.title, GENERIC_JA_TITLE)

    def test_very_long_message_with_known_code_does_not_hang_and_keeps_the_name(self):
        # Colon-heavy input is the worst case for the "(?:.*: )?" pattern used by several rows.
        message = 'Defs/a.xml: ' * 2000 + 'Tail.Name'
        plain = explain({'code': 'invalid-key', 'message': message}, 'en')
        self.assertTrue(plain.title.startswith('Skipped a key that cannot be used: '))
        self.assertIn('Tail.Name', plain.title)

    def test_long_parameter_is_substituted_in_full(self):
        name = 'Mod.' + 'Name' * 500
        plain = explain({'code': 'inheritance', 'message': f'inheritance {name}: missing'}, 'en')
        self.assertIn(name, plain.title)


class MultilineAndSuggestionTests(unittest.TestCase):
    def test_newlines_in_technical_text_are_preserved_in_order(self):
        plain = explain({'code': 'xml', 'message': 'Defs/a.xml: line1\nline2',
                         'suggestion': 'first\nsecond'}, 'ja')
        self.assertEqual(plain.technical, 'code: xml\nDefs/a.xml: line1\nline2\nfirst\nsecond')

    def test_dot_does_not_cross_newlines_so_parameter_is_not_extracted(self):
        # "." in the duplicate-row regex stops at a newline, so the title falls back to the ellipsis.
        plain = explain({'code': 'duplicate', 'message': 'blocked: X\n(Defs/a.xml)'}, 'en')
        self.assertTrue(plain.title.endswith(': …'), plain.title)

    def test_multiline_message_with_colon_still_extracts_path_for_xml_row(self):
        plain = explain({'code': 'xml', 'message': 'Defs/a.xml:\nparse error'}, 'en')
        self.assertIn('Defs/a.xml', plain.title)

    def test_suggestion_only_without_code_or_japanese_is_folded_into_technical(self):
        plain = explain({'message': 'Something odd', 'suggestion': 'Look here'}, 'en')
        self.assertEqual(plain.title, GENERIC_EN_TITLE)
        self.assertEqual(plain.technical, 'Something odd\nLook here')

    def test_japanese_message_without_code_is_shown_as_written_even_in_english_ui(self):
        # Current behaviour: already-plain Japanese text is passed through regardless of the language setting.
        plain = explain({'message': '日本語の診断です', 'suggestion': '確認してください'}, 'en')
        self.assertEqual(plain.title, '日本語の診断です')
        self.assertEqual(plain.action, '確認してください')
        self.assertEqual(plain.technical, '')

    def test_japanese_message_without_suggestion_gives_empty_action(self):
        plain = explain({'message': 'テスト'}, 'ja')
        self.assertEqual(plain.title, 'テスト')
        self.assertEqual(plain.action, '')


class JapaneseCharacterTests(unittest.TestCase):
    def test_japanese_folder_name_is_extracted_from_load_path_row(self):
        plain = explain({'code': 'load-path', 'message': 'Bad load folder: 日本語フォルダー/漢字'}, 'ja')
        self.assertIn('日本語フォルダー/漢字', plain.title)

    def test_japanese_mod_name_survives_in_missing_dependency_title(self):
        plain = explain({'code': 'missing-dependency',
                         'message': 'Prerequisite MODs not installed: 日本語MOD (a.b); 2 fields cannot be checked.'}, 'ja')
        self.assertIn('日本語MOD (a.b)', plain.title)

    def test_half_width_katakana_only_message_is_not_treated_as_japanese(self):
        # Current behaviour: the Japanese check covers hiragana, full-width katakana and kanji only.
        plain = explain({'message': 'ｶﾀｶﾅ'}, 'en')
        self.assertEqual(plain.title, GENERIC_EN_TITLE)
        self.assertEqual(plain.technical, 'ｶﾀｶﾅ')

    def test_japanese_punctuation_alone_is_not_treated_as_japanese(self):
        plain = explain({'message': '。、'}, 'ja')
        self.assertEqual(plain.title, GENERIC_JA_TITLE)

    def test_mixed_japanese_and_english_message_with_code_uses_table_title(self):
        plain = explain({'code': 'patch-root', 'message': 'パッチ: root replace'}, 'ja')
        self.assertEqual(plain.title, 'パッチはルート要素を置換・削除できません')
        self.assertIn('パッチ: root replace', plain.technical)


class TechnicalLabelTests(unittest.TestCase):
    def test_japanese_label_is_default(self):
        self.assertEqual(technical_label(), '技術的な詳細')
        self.assertEqual(technical_label('ja'), '技術的な詳細')

    def test_any_other_language_gets_english_label(self):
        self.assertEqual(technical_label('en'), 'Technical details')
        self.assertEqual(technical_label('fr'), 'Technical details')
        self.assertEqual(technical_label(''), 'Technical details')


class KnownCodesTests(unittest.TestCase):
    def test_known_codes_is_a_non_empty_tuple_without_duplicates(self):
        codes = known_codes()
        self.assertIsInstance(codes, tuple)
        self.assertGreater(len(codes), 40)
        self.assertEqual(len(codes), len(set(codes)))

    def test_every_known_code_renders_without_error_for_empty_message(self):
        for code in known_codes():
            plain = explain({'code': code}, 'ja')
            self.assertEqual(plain.code, code)
            self.assertTrue(plain.title, code)
            self.assertIn(f'code: {code}', plain.technical)


class PlainDiagnosticTests(unittest.TestCase):
    def test_result_is_a_frozen_dataclass(self):
        plain = explain({'code': 'loadfolders'}, 'ja')
        self.assertIsInstance(plain, PlainDiagnostic)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plain.title = 'changed'

    def test_module_exports_the_helpers_used_by_the_gui(self):
        for name in ('explain', 'technical_label', 'known_codes', 'PlainDiagnostic'):
            self.assertTrue(hasattr(diagnostic_text, name), name)


if __name__ == '__main__':
    unittest.main()

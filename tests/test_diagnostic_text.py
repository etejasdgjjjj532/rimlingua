"""Diagnostics are shown in plain words; the developer English is folded away as technical details."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QPlainTextEdit, QToolButton
from rimworld_translator import diagnostic_text
from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.gui import Window

PKG = Path(__file__).resolve().parents[1] / 'rimworld_translator'
CODE_SOURCES = ['extraction.py', 'scan_context.py', 'gui.py', 'dependency_profiles.py']
CODE_PATTERN = re.compile(r"""(?:\bwarn|\badd)\(\s*['"]([a-z][a-z-]+)['"]|['"]code['"]\s*:\s*['"]([a-z][a-z-]+)['"]""")
JAPANESE = re.compile('[ぁ-んァ-ン一-龥]')


def emitted_codes():
    found = set()
    for name in CODE_SOURCES:
        for match in CODE_PATTERN.finditer((PKG / name).read_text(encoding='utf-8')):
            found.add(match.group(1) or match.group(2))
    return found


class MappingTests(unittest.TestCase):
    def test_every_emitted_code_has_japanese_and_english_text(self):
        codes = emitted_codes()
        self.assertGreater(len(codes), 40)
        self.assertEqual(sorted(codes - set(diagnostic_text.known_codes())), [])
        for code in diagnostic_text.known_codes():
            for language in ('ja', 'en'):
                plain = diagnostic_text.explain({'code': code, 'message': 'x', 'suggestion': ''}, language)
                self.assertTrue(plain.title, (code, language))
                self.assertTrue(plain.action, (code, language))
            self.assertRegex(diagnostic_text.explain({'code': code, 'message': 'x'}, 'ja').title, JAPANESE, code)
            self.assertNotRegex(diagnostic_text.explain({'code': code, 'message': 'x'}, 'en').title, JAPANESE, code)

    def test_parameters_are_pulled_out_of_the_original_message(self):
        plain = diagnostic_text.explain({'code': 'unresolved-class', 'source_file': 'Defs/A.xml',
                                         'message': 'Class Foo.Bar not found; reading Thing_1 as ThingDef'}, 'ja')
        self.assertIn('Foo.Bar', plain.title)
        self.assertIn('ThingDef', plain.title)
        plain = diagnostic_text.explain({'code': 'missing-dependency',
                                         'message': 'Prerequisite MODs not installed: Core Lib (a.b); 3 fields cannot be checked.'}, 'en')
        self.assertIn('Core Lib (a.b)', plain.title)

    def test_original_english_is_kept_as_technical_details(self):
        raw = {'code': 'duplicate', 'message': 'Duplicate active key blocked: X (Defs/a.xml)', 'suggestion': 'Check duplicate definitions'}
        plain = diagnostic_text.explain(raw, 'ja')
        self.assertNotIn('Duplicate active key', plain.title + plain.action)
        self.assertIn('Duplicate active key blocked', plain.technical)
        self.assertIn('Check duplicate definitions', plain.technical)
        self.assertIn('duplicate', plain.technical)

    def test_unknown_code_falls_back_to_a_plain_sentence_with_the_raw_text_folded(self):
        raw = {'code': 'brand-new-thing', 'message': 'Something odd happened in Foo'}
        for language in ('ja', 'en'):
            plain = diagnostic_text.explain(raw, language)
            self.assertNotIn('Something odd', plain.title + plain.action)
            self.assertIn('Something odd happened in Foo', plain.technical)
        self.assertRegex(diagnostic_text.explain(raw, 'ja').title, JAPANESE)

    def test_already_plain_japanese_messages_pass_through(self):
        raw = {'message': '半角カナが含まれています', 'suggestion': '全角カナに直してください'}
        plain = diagnostic_text.explain(raw, 'ja')
        self.assertEqual((plain.title, plain.action), ('半角カナが含まれています', '全角カナに直してください'))

    def test_codeless_schema_and_omitted_warnings_are_recognised(self):
        self.assertEqual(diagnostic_text.explain({'message': 'Foo.dll: metadata unavailable: bad'}, 'en').code, 'metadata')
        self.assertEqual(diagnostic_text.explain(
            {'message': '12 additional distinct warnings omitted (total events 99); inspect source context manually'}, 'en').code,
            'warnings-omitted')


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / 'source'
        source.mkdir()
        entry = Entry(id='DefInjected:ThingDef:Panel.label', kind='DefInjected', group='ThingDef', key='Panel.label',
                      english='panel', source_file='Defs/Panel.xml')
        path = root / 'work/project.json'
        Project.create(source, Scan(entries=[entry])).save(path)
        self.window = Window(settings_path=root / 'settings.json')
        self.window.load_project(path)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def open_dialog(self, diagnostics, language):
        self.window.ui_language = language
        self.window.project.diagnostics = diagnostics
        seen = {}
        def execute(dialog):
            listing = dialog.findChild(QListWidget)
            seen['labels'] = [listing.item(i).text() for i in range(listing.count())]
            listing.setCurrentRow(0)
            seen['detail'] = dialog.findChild(QPlainTextEdit, 'diagnosticDetail').toPlainText()
            technical = dialog.findChild(QPlainTextEdit, 'diagnosticTechnical')
            seen['technical'] = technical.toPlainText()
            seen['technical_visible_before'] = technical.isVisibleTo(dialog)
            toggle = dialog.findChild(QToolButton, 'diagnosticTechnicalToggle')
            toggle.click()
            seen['technical_visible_after'] = technical.isVisibleTo(dialog)
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', execute):
            self.window.show_warnings()
        return seen

    DIAGNOSTICS = [{'code': 'missing-folder', 'message': 'Load folder missing: v1.6/Defs', 'source_file': 'LoadFolders.xml',
                    'entry_id': '', 'suggestion': 'Check source context; exclude uncertain candidates.'}]

    def test_japanese_title_with_folded_technical_details(self):
        seen = self.open_dialog(self.DIAGNOSTICS, 'ja')
        self.assertRegex(seen['labels'][0], '[ぁ-ん]')
        self.assertNotIn('Load folder missing', seen['labels'][0])
        self.assertNotIn('Load folder missing', seen['detail'])
        self.assertIn('Load folder missing: v1.6/Defs', seen['technical'])
        self.assertFalse(seen['technical_visible_before'])
        self.assertTrue(seen['technical_visible_after'])

    def test_english_ui_gets_plain_english(self):
        seen = self.open_dialog(self.DIAGNOSTICS, 'en')
        self.assertNotRegex(seen['labels'][0] + seen['detail'], '[ぁ-んァ-ン一-龥]')
        self.assertNotIn('Load folder missing', seen['labels'][0])
        self.assertIn('Load folder missing', seen['technical'])


if __name__ == '__main__':
    unittest.main()

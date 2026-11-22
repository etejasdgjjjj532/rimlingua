"""Safety diagnostics retain inspectable provenance without changing saved work."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QPlainTextEdit
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


class SafetyDiagnosticProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source'
        (source / 'Defs').mkdir(parents=True)
        self.xml = source / 'Defs' / 'Private.xml'
        self.xml.write_text('<Defs><Example.Def><defName>Panel</defName>'
                            '<label>Panel label</label><privateText>Internal dispatch</privateText>'
                            '</Example.Def></Defs>')
        catalog = source / 'Languages/English/DefInjected/Example.Def/private.xml'
        catalog.parent.mkdir(parents=True)
        catalog.write_text('<LanguageData><Panel.privateText>Internal dispatch</Panel.privateText></LanguageData>')
        schema = TranslationSchema({'Example.Def': TypeSpec('Example.Def', fields={
            'label': FieldSpec('System.String'),
            'privateText': FieldSpec('System.String', ('NoTranslateAttribute',))})})
        result = scan_mod(source, schema=schema)
        self.assertEqual([e.key for e in result.entries], ['Panel.label'])
        project = Project.create(source, result)
        entry = project.entries[0]
        entry.japanese, entry.approved, entry.reviewed = '保存済みパネル', True, True
        self.path = self.root / 'work/project.json'
        project.save(self.path)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.path)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def inspect(self, callback):
        def execute(dialog):
            listing = dialog.findChild(QListWidget)
            callback(listing, dialog.findChild(QPlainTextEdit, 'diagnosticDetail'))
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', execute):
            self.window.show_warnings()

    def test_excluded_field_diagnostic_keeps_actual_xml_origin_visible(self):
        before_project = self.path.read_bytes()
        before_xml = self.xml.read_bytes()
        def check(listing, detail):
            row = next(i for i, d in enumerate(self.window.project.diagnostics)
                       if d['code'] == 'non-localizable-field')
            diagnostic = self.window.project.diagnostics[row]
            self.assertEqual(diagnostic['source_file'], 'Languages/English/DefInjected/Example.Def/private.xml')
            self.assertNotIn('Languages/English/DefInjected/Example.Def/private.xml', diagnostic['message'])
            listing.setCurrentRow(row)
            self.assertTrue(detail.isReadOnly())
            self.assertIn('Languages/English/DefInjected/Example.Def/private.xml', detail.toPlainText(),
                          'Internal-field safety review must retain its stored XML source')
            # The reason is developer text: it lives in the folded technical details.
            self.assertIn('NoTranslateAttribute', detail.parent().findChild(QPlainTextEdit, 'diagnosticTechnical').toPlainText())
        self.inspect(check)
        self.assertEqual(self.path.read_bytes(), before_project)
        self.assertEqual(self.xml.read_bytes(), before_xml)

    def test_structured_safety_provenance_and_legacy_record_do_not_change_saved_work(self):
        self.window.project.diagnostics = [
            dict(code='non-localizable-field', message='Excluded internal field',
                 source_file='Patches/Owner.xml', owner_type='Example.PrivateOwner',
                 field_path='Panel.privateText', suggestion='Keep the internal value unchanged.'),
            dict(message='Legacy diagnostic without provenance'),
            dict(code='unknown-field', message='Unverified body without CLR owner',
                 source_file='Defs/Unknown.xml', source_text='Unverified tooltip', safety='unverified'),
        ]
        self.assertTrue(self.window.save(export=False))
        before_bytes = self.path.read_bytes()
        before_diagnostics = copy.deepcopy(self.window.project.diagnostics)
        def check(listing, detail):
            text = detail.toPlainText()
            for value in ('Patches/Owner.xml', 'Example.PrivateOwner', 'Panel.privateText'):
                self.assertIn(value, text)
            self.assertNotIn('原文:', text)
            listing.setCurrentRow(1)
            self.assertNotIn('Example.PrivateOwner', detail.toPlainText())
            self.assertNotIn('Patches/Owner.xml', detail.toPlainText())
            listing.setCurrentRow(2)
            for value in ('Defs/Unknown.xml', 'Unverified tooltip', '未検証', '不明'):
                self.assertIn(value, detail.toPlainText())
        self.inspect(check)
        self.assertEqual(self.path.read_bytes(), before_bytes)
        self.assertEqual(self.window.project.diagnostics, before_diagnostics)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.path)
        self.assertEqual(restored.diagnostics, before_diagnostics)
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(restored.entries[0].japanese, '保存済みパネル')
        self.assertTrue(restored.entries[0].approved)
        self.assertTrue(restored.entries[0].reviewed)

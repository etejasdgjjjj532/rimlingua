"""Large retained diagnostics have bounded previews without losing review data."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QListWidget, QPlainTextEdit
from rimworld_translator.core import Entry, Project, Scan, scan_mod
from rimworld_translator.gui import Window


class DiagnosticPreviewBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source'
        source.mkdir()
        entry = Entry(id='DefInjected:ThingDef:Panel.label', kind='DefInjected', group='ThingDef',
                      key='Panel.label', english='panel', source_file='Defs/Panel.xml',
                      japanese='保存済みパネル', approved=True, reviewed=True)
        self.path = self.root / 'work/project.json'
        Project.create(source, Scan(entries=[entry])).save(self.path)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.path)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def inspect(self, callback):
        def execute(dialog):
            callback(dialog, dialog.findChild(QListWidget),
                     dialog.findChild(QPlainTextEdit, 'diagnosticDetail'))
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', execute):
            self.window.show_warnings()

    def test_large_retained_fields_are_explicitly_bounded_before_qt_layout(self):
        body = '長' * 100_000 + 'hidden suffix'
        candidate = dict(code='unknown-field', message=body, source_file=body,
                         owner_type=body, field_path=body, source_text=body,
                         suggestion=body, entry_id=self.window.project.entries[0].id)
        self.window.project.diagnostics = [candidate]
        def check(dialog, listing, detail):
            item = listing.currentItem()
            self.assertLess(len(item.text()), 700, 'List rows must not lay out full diagnostic text')
            self.assertLess(len(item.toolTip()), 4300)
            text = detail.toPlainText()
            self.assertLess(len(text), 26_000, 'Each diagnostic field needs its own bounded preview')
            self.assertIn('省略', text)
            self.assertIn(str(len(body)), text)
            self.assertIn('未検証', text)
            self.assertTrue(detail.isReadOnly())
            self.assertEqual(item.data(Qt.UserRole + 1), candidate)
            with patch.object(self.window, 'navigate_entry') as navigate:
                listing.itemDoubleClicked.emit(item)
                navigate.assert_not_called()
        self.inspect(check)

    def test_hidden_suffix_remains_searchable_and_saved_review_state_is_unchanged(self):
        candidate = dict(code='unknown-field', message='Unverified body',
                         source_file='Defs/Panel.xml', owner_type='Unknown.Owner',
                         field_path='Panel.tooltipText',
                         source_text='x' * 100_000 + '<b>TAIL-NEEDLE</b>',
                         source_text_length=100_018, source_text_truncated=False)
        self.window.project.diagnostics = [candidate, dict(message='Ordinary short diagnostic')]
        self.assertTrue(self.window.save(export=False))
        before = self.path.read_bytes()
        before_diagnostics = copy.deepcopy(self.window.project.diagnostics)
        def check(dialog, listing, detail):
            self.assertLess(len(detail.toPlainText()), 5000)
            search = dialog.findChild(QLineEdit, 'diagnosticSearch')
            search.setText('tail-needle')
            self.assertEqual(listing.count(), 1)
            self.assertEqual(listing.currentItem().data(Qt.UserRole + 1), candidate)
            self.assertIn('省略', detail.toPlainText())
            search.setText('ordinary short')
            self.assertNotIn('Ordinary short diagnostic', detail.toPlainText())
            self.assertIn('Ordinary short diagnostic', dialog.findChild(QPlainTextEdit, 'diagnosticTechnical').toPlainText())
            search.clear()
            self.assertEqual(listing.count(), 2)
        self.inspect(check)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.window.project.diagnostics, before_diagnostics)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.path)
        self.assertEqual(restored.diagnostics, before_diagnostics)
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(restored.entries[0].japanese, '保存済みパネル')
        self.assertTrue(restored.entries[0].approved)
        self.assertTrue(restored.entries[0].reviewed)

    def test_actual_xml_unknown_field_name_has_a_bounded_review_preview(self):
        source = self.root / 'source'
        (source / 'Defs').mkdir()
        field = 'tooltip' + 'x' * 10_000
        xml = source / 'Defs/LargeField.xml'
        xml.write_text(f'<Defs><ThingDef><defName>Panel</defName><label>panel</label>'
                       f'<{field}>Unverified text</{field}></ThingDef></Defs>')
        before = xml.read_bytes()
        result = scan_mod(source)
        candidate = next(d for d in result.diagnostics if d.get('code') == 'unknown-field')
        self.assertIn(field, candidate['field_path'])
        self.assertEqual(candidate['source_text'], 'Unverified text')
        self.window.project.diagnostics = [candidate]
        def check(dialog, listing, detail):
            self.assertLess(len(listing.currentItem().text()), 700)
            self.assertLess(len(detail.toPlainText()), 10_000)
            self.assertIn('Unverified text', detail.toPlainText())
            self.assertIn('省略', detail.toPlainText())
            self.assertEqual(listing.currentItem().data(Qt.UserRole + 1), candidate)
        self.inspect(check)
        self.assertEqual(xml.read_bytes(), before)

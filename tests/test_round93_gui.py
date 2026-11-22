"""Find a retained candidate's matching source page without changing saved work."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton
from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.gui import Window


class DiagnosticSourceMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / 'source'
        source.mkdir()
        entry = Entry(id='DefInjected:ThingDef:Panel.label', kind='DefInjected', group='ThingDef',
                      key='Panel.label', english='panel', source_file='Defs/Panel.xml',
                      japanese='保存済みパネル', approved=True, reviewed=True)
        candidate = dict(code='unknown-field', message='retained candidate', owner_type='Unknown.Owner',
                         source_file='Defs/Panel.xml', field_path='Panel.tooltipText',
                         source_text='ß' * 4095 + 'xx' + 'Straße' + chr(0x1F680) + 'z' * 5000,
                         entry_id=entry.id)
        self.path = root / 'work/project.json'
        Project.create(source, Scan(entries=[entry], diagnostics=[candidate])).save(self.path)
        self.window = Window(settings_path=root / 'settings.json')
        self.window.load_project(self.path)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def inspect(self, callback):
        def execute(dialog):
            callback(dialog, dialog.findChild(QListWidget), dialog.findChild(QPlainTextEdit, 'diagnosticDetail'))
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', execute):
            self.window.show_warnings()

    def test_matching_source_page_maps_casefold_offsets_and_preserves_saved_translation(self):
        before = self.path.read_bytes()
        diagnostics = copy.deepcopy(self.window.project.diagnostics)
        def check(dialog, listing, detail):
            search = dialog.findChild(QLineEdit, 'diagnosticSearch')
            jump = dialog.findChild(QPushButton, 'diagnosticSourceMatchPage')
            self.assertIsNotNone(jump, 'A retained source match needs direct inspection without hundreds of page clicks')
            self.assertFalse(jump.isEnabled())
            search.setText('STRASSE')
            self.assertEqual(listing.count(), 1)
            self.assertNotIn('Straße', detail.toPlainText())
            self.assertTrue(jump.isEnabled())
            jump.click()
            self.assertIn('Straße' + chr(0x1F680), detail.toPlainText())
            self.assertIn('4097–8192', dialog.findChild(QLabel, 'diagnosticSourcePageStatus').text())
            self.assertLess(len(detail.toPlainText()), 5000)
            self.assertTrue(detail.isReadOnly())
            listing.itemDoubleClicked.emit(listing.currentItem())
            self.assertEqual(dialog.result(), 0)
        self.inspect(check)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.window.project.diagnostics, diagnostics)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.path)
        self.assertEqual(restored.diagnostics, diagnostics)
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(restored.entries[0].japanese, '保存済みパネル')
        self.assertTrue(restored.entries[0].approved)
        self.assertTrue(restored.entries[0].reviewed)

    def test_source_jump_disables_for_metadata_only_matches_and_clears_with_selection(self):
        self.window.project.diagnostics.extend([
            dict(code='unknown-field', message='retained candidate', source_text='different retained text',
                 source_text_truncated=True, source_text_length=100000),
            dict(code='qa', message='retained candidate normal', entry_id=self.window.project.entries[0].id),
        ])
        def check(dialog, listing, detail):
            search = dialog.findChild(QLineEdit, 'diagnosticSearch')
            jump = dialog.findChild(QPushButton, 'diagnosticSourceMatchPage')
            self.assertIsNotNone(jump, 'Source match navigation must distinguish metadata matches')
            search.setText('STRASSE')
            jump.click()
            self.assertIn('Straße', detail.toPlainText())
            search.setText('retained candidate')
            self.assertFalse(jump.isEnabled())
            self.assertIn('1–4096', dialog.findChild(QLabel, 'diagnosticSourcePageStatus').text())
            listing.setCurrentRow(1)
            self.assertFalse(jump.isEnabled())
            self.assertIn('100000', detail.toPlainText())
            listing.setCurrentRow(2)
            self.assertFalse(jump.isEnabled())
            search.clear()
            self.assertFalse(jump.isEnabled())
            search.setText('does not exist')
            self.assertFalse(jump.isEnabled())
            self.assertEqual(detail.toPlainText(), '')
        self.inspect(check)

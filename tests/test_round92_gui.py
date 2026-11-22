"""Retained candidate source text can be inspected in bounded pages."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton
from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.gui import Window


class DiagnosticSourcePagingTests(unittest.TestCase):
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
        candidate = dict(code='unknown-field', message='Retained candidate', owner_type='Unknown.Owner',
                         source_file='Defs/Panel.xml', field_path='Panel.tooltipText',
                         source_text='あ' * 4095 + chr(0x1F680) + '<color=red>second</color>' + 'う' * (4096 - len('<color=red>second</color>')) + '終端',
                         entry_id=entry.id)
        self.path = self.root / 'work/project.json'
        Project.create(source, Scan(entries=[entry], diagnostics=[candidate])).save(self.path)
        self.window = Window(settings_path=self.root / 'settings.json')
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

    def test_retained_source_pages_reveal_tail_without_promoting_or_changing_saved_work(self):
        before = self.path.read_bytes()
        diagnostics = copy.deepcopy(self.window.project.diagnostics)
        def check(dialog, listing, detail):
            previous = dialog.findChild(QPushButton, 'diagnosticSourcePreviousPage')
            following = dialog.findChild(QPushButton, 'diagnosticSourceNextPage')
            status = dialog.findChild(QLabel, 'diagnosticSourcePageStatus')
            self.assertIsNotNone(following, 'Retained source beyond the first preview needs an inspection route')
            self.assertFalse(previous.isEnabled())
            self.assertTrue(following.isEnabled())
            self.assertIn('1–4096', status.text())
            self.assertIn(chr(0x1F680), detail.toPlainText())
            following.click()
            self.assertIn('<color=red>second</color>', detail.toPlainText())
            self.assertNotIn('終端', detail.toPlainText())
            self.assertIn('4097–8192', status.text())
            following.click()
            self.assertIn('終端', detail.toPlainText())
            self.assertFalse(following.isEnabled())
            self.assertTrue(previous.isEnabled())
            self.assertLess(len(detail.toPlainText()), 5000)
            self.assertTrue(detail.isReadOnly())
            self.assertIn('未検証', detail.toPlainText())
            with patch.object(self.window, 'navigate_entry') as navigate:
                listing.itemDoubleClicked.emit(listing.currentItem())
                navigate.assert_not_called()
            previous.click()
            self.assertIn('<color=red>second</color>', detail.toPlainText())
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

    def test_selection_and_filter_reset_source_page_and_truncation_never_invents_missing_text(self):
        self.window.project.diagnostics.extend([
            dict(code='unknown-field', message='Scanner truncated candidate', source_text='visible prefix',
                 source_text_truncated=True, source_text_length=100_000),
            dict(code='qa', message='Normal diagnostic', entry_id=self.window.project.entries[0].id),
        ])
        def check(dialog, listing, detail):
            following = dialog.findChild(QPushButton, 'diagnosticSourceNextPage')
            previous = dialog.findChild(QPushButton, 'diagnosticSourcePreviousPage')
            status = dialog.findChild(QLabel, 'diagnosticSourcePageStatus')
            self.assertIsNotNone(following, 'Candidate source navigation controls must exist')
            following.click()
            listing.setCurrentRow(1)
            self.assertFalse(following.isEnabled())
            self.assertFalse(previous.isEnabled())
            self.assertIn('100000', detail.toPlainText())
            self.assertIn('省略', detail.toPlainText())
            self.assertIn('visible prefix', detail.toPlainText())
            listing.setCurrentRow(0)
            self.assertIn('1–4096', status.text())
            following.click()
            search = dialog.findChild(QLineEdit, 'diagnosticSearch')
            search.setText('終端')
            self.assertEqual(listing.count(), 1)
            self.assertIn('1–4096', status.text())
            search.setText('Normal diagnostic')
            self.assertFalse(following.isEnabled())
            self.assertFalse(previous.isEnabled())
            self.assertEqual(status.text(), '')
            # Developer text is folded into the technical pane; the visible part is plain.
            self.assertNotIn('Normal diagnostic', detail.toPlainText())
            self.assertIn('Normal diagnostic', dialog.findChild(QPlainTextEdit, 'diagnosticTechnical').toPlainText())
            search.setText('does not exist')
            self.assertEqual(detail.toPlainText(), '')
            self.assertEqual(status.text(), '')
        self.inspect(check)

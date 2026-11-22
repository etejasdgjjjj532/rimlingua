"""Retained candidate provenance can be searched without mutating saved work."""
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


class DiagnosticSearchTests(unittest.TestCase):
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
            search = dialog.findChild(QLineEdit, 'diagnosticSearch')
            self.assertIsNotNone(search, 'Candidate source/owner needs search across retained pages')
            callback(dialog, search, dialog.findChild(QListWidget))
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', execute):
            self.window.show_warnings()

    def test_source_owner_field_and_literal_body_search_all_retained_pages(self):
        candidate = dict(code='unknown-field', message='Unverified candidate',
                         source_file='Patches/Unique.xml', owner_type='Unknown.Strauße',
                         field_path='parts.0.tooltipText', source_text='<b>[literal].*</b>',
                         suggestion='Inspect the CLR declaration', safety='unverified')
        self.window.project.diagnostics = [dict(message=f'Ordinary {i}') for i in range(3001)] + [candidate]
        def check(dialog, search, listing):
            for needle in ('PATCHES/UNIQUE.XML', 'unknown.strAUSSE', 'parts.0.tooltipText', '[literal].*',
                           'Inspect the CLR declaration', 'unknown-field'):
                with self.subTest(needle=needle):
                    search.setText(needle)
                    self.assertEqual(listing.count(), 1)
                    self.assertEqual(listing.currentItem().data(Qt.UserRole + 1), candidate)
                    detail = dialog.findChild(QPlainTextEdit, 'diagnosticDetail')
                    self.assertTrue(detail.isReadOnly())
                    self.assertIn('<b>[literal].*</b>', detail.toPlainText())
                    self.assertIn('未検証', detail.toPlainText())
                    status = dialog.findChild(QLabel, 'diagnosticPageStatus').text()
                    self.assertIn('3002', status)
                    self.assertIn('1', status)
                    self.assertFalse(dialog.findChild(QPushButton, 'diagnosticNextPage').isEnabled())
            search.setText('No such retained diagnostic')
            self.assertEqual(listing.count(), 0)
            self.assertEqual(dialog.findChild(QPlainTextEdit, 'diagnosticDetail').toPlainText(), '')
            search.clear()
            self.assertEqual(listing.count(), 1500)
            self.assertEqual(listing.currentItem().data(Qt.UserRole + 1)['message'], 'Ordinary 0')
            self.assertTrue(dialog.findChild(QPushButton, 'diagnosticNextPage').isEnabled())
        self.inspect(check)

    def test_search_resets_page_binding_and_preserves_saved_translation_state(self):
        entry = self.window.project.entries[0]
        candidate = dict(code='unknown-field', message='Chosen unverified', entry_id=entry.id,
                         source_file=entry.source_file, owner_type='Unknown.Tail', field_path='tooltip',
                         source_text='Candidate body', safety='unverified')
        ordinary = dict(message='Chosen normal', entry_id=entry.id)
        self.window.project.diagnostics = [ordinary] + [dict(message=f'Other {i}') for i in range(1500)] + [candidate]
        self.assertTrue(self.window.save(export=False))
        before_bytes = self.path.read_bytes()
        before_diagnostics = copy.deepcopy(self.window.project.diagnostics)
        def check(dialog, search, listing):
            dialog.findChild(QPushButton, 'diagnosticNextPage').click()
            self.assertEqual(listing.count(), 2)
            search.setText('Chosen')
            self.assertEqual(listing.count(), 2)
            self.assertFalse(dialog.findChild(QPushButton, 'diagnosticPreviousPage').isEnabled())
            self.assertEqual(listing.currentItem().data(Qt.UserRole + 1), ordinary)
            listing.setCurrentRow(1)
            with patch.object(self.window, 'navigate_entry') as navigate:
                listing.itemDoubleClicked.emit(listing.currentItem())
                navigate.assert_not_called()
            listing.setCurrentRow(0)
            with patch.object(self.window, 'navigate_entry') as navigate:
                listing.itemDoubleClicked.emit(listing.currentItem())
                navigate.assert_called_once_with(entry.id)
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

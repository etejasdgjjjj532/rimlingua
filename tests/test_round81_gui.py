"""All retained diagnostics remain reachable without altering translation state."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QListWidget, QPlainTextEdit, QPushButton
from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.gui import Window


class DiagnosticPaginationTests(unittest.TestCase):
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

    def inspect_diagnostics(self, inspect):
        def execute(dialog):
            inspect(dialog, dialog.findChild(QListWidget))
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', execute):
            self.window.show_warnings()

    def controls(self, dialog):
        previous = dialog.findChild(QPushButton, 'diagnosticPreviousPage')
        following = dialog.findChild(QPushButton, 'diagnosticNextPage')
        self.assertIsNotNone(previous, 'Retained diagnostics need page navigation')
        self.assertIsNotNone(following, 'Diagnostics after 1500 must remain reachable')
        return previous, following

    def test_every_retained_candidate_after_1500_other_diagnostics_is_reachable(self):
        ordinary = [dict(message=f'ordinary-{i}') for i in range(1500)]
        candidates = [dict(code='unknown-field', message=f'candidate-{i}', source_file=f'Defs/{i}.xml',
                           owner_type=f'Unknown.Owner{i}', field_path='tooltipText',
                           source_text=f'Unverified body {i}', safety='unverified') for i in range(3014)]
        self.window.project.diagnostics = ordinary + candidates
        def inspect(dialog, listing):
            previous, following = self.controls(dialog)
            self.assertFalse(previous.isEnabled())
            seen = []
            while True:
                seen.extend(listing.item(i).data(Qt.UserRole + 1)['message'] for i in range(listing.count()))
                if not following.isEnabled():
                    break
                following.click()
            self.assertEqual(len(seen), 4514)
            self.assertEqual(len(set(seen)), 4514)
            self.assertEqual(seen[1499:1502], ['ordinary-1499', 'candidate-0', 'candidate-1'])
            self.assertEqual(seen[-1], 'candidate-3013')
            listing.setCurrentRow(listing.count() - 1)
            detail = dialog.findChild(QPlainTextEdit, 'diagnosticDetail')
            self.assertTrue(detail.isReadOnly())
            self.assertIn('Unknown.Owner3013', detail.toPlainText())
            self.assertIn('Unverified body 3013', detail.toPlainText())
            self.assertIn('未検証', detail.toPlainText())
            summary = dialog.findChild(QLabel, 'diagnosticPageStatus').text()
            self.assertIn('4514', summary)
        self.inspect_diagnostics(inspect)

    def test_page_round_trip_keeps_item_binding_and_saved_translation_state(self):
        entry = self.window.project.entries[0]
        ordinary = dict(message='Normal QA entry', entry_id=entry.id)
        candidate = dict(code='unknown-field', message='Tail unknown', entry_id=entry.id,
                         source_file=entry.source_file, owner_type='Unknown.Tail',
                         field_path='tooltipText', source_text='Tail body', safety='unverified')
        self.window.project.diagnostics = [ordinary] + [dict(message=f'Other {i}') for i in range(1499)] + [candidate]
        self.assertTrue(self.window.save(export=False))
        before_bytes = self.path.read_bytes()
        before_diagnostics = copy.deepcopy(self.window.project.diagnostics)
        def inspect(dialog, listing):
            previous, following = self.controls(dialog)
            following.click()
            item = listing.currentItem()
            self.assertEqual(item.data(Qt.UserRole + 1), candidate)
            self.assertEqual(item.data(Qt.UserRole), entry.id)
            detail = dialog.findChild(QPlainTextEdit, 'diagnosticDetail')
            self.assertIn('Unknown.Tail', detail.toPlainText())
            with patch.object(self.window, 'navigate_entry') as navigate:
                listing.itemDoubleClicked.emit(item)
                navigate.assert_not_called()
            previous.click()
            self.assertEqual(listing.currentItem().data(Qt.UserRole + 1), ordinary)
            self.assertNotIn('Unknown.Tail', detail.toPlainText())
            with patch.object(self.window, 'navigate_entry') as navigate:
                listing.itemDoubleClicked.emit(listing.currentItem())
                navigate.assert_called_once_with(entry.id)
        self.inspect_diagnostics(inspect)
        self.assertEqual(self.path.read_bytes(), before_bytes)
        self.assertEqual(self.window.project.diagnostics, before_diagnostics)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.path)
        self.assertEqual(restored.diagnostics, before_diagnostics)
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(restored.entries[0].japanese, '保存済みパネル')
        self.assertTrue(restored.entries[0].approved)
        self.assertTrue(restored.entries[0].reviewed)

    def test_empty_and_exact_page_boundaries_disable_unavailable_navigation(self):
        self.window.project.entries.clear()
        self.window.project.warnings.clear()
        for count in (0, 1, 1500):
            with self.subTest(count=count):
                self.window.project.diagnostics = [dict(message=f'Diagnostic {i}') for i in range(count)]
                def inspect(dialog, listing):
                    previous, following = self.controls(dialog)
                    self.assertFalse(previous.isEnabled())
                    self.assertFalse(following.isEnabled())
                    self.assertEqual(listing.count(), count)
                    if not count:
                        self.assertEqual(dialog.findChild(QPlainTextEdit, 'diagnosticDetail').toPlainText(), '')
                self.inspect_diagnostics(inspect)

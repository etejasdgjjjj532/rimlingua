"""Unknown-field diagnostics support review without promoting or redirecting entries."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QPlainTextEdit
from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.gui import Window


class UnknownCandidateReviewTests(unittest.TestCase):
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
                      japanese='保存済みのパネル', approved=True, reviewed=True)
        diagnostic = dict(code='unknown-field', message='Field absent from CLR schema: Defs/Panel.xml: Panel.tooltipText',
                          source_file='Defs/Panel.xml', owner_type='Example.UnknownComp',
                          field_path='comps.0.tooltipText', source_text='Move faster when enabled <color=green>now</color>',
                          safety='unverified', entry_id='', suggestion='Inspect owner before translation.')
        project = Project.create(source, Scan(entries=[entry], diagnostics=[diagnostic]))
        self.path = self.root / 'work/project.json'
        project.save(self.path)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.path)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def open_diagnostics(self, inspect):
        def execute(dialog):
            listing = dialog.findChild(QListWidget)
            listing.setCurrentRow(0)
            self.app.processEvents()
            inspect(dialog, listing)
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', execute):
            self.window.show_warnings()

    def test_candidate_detail_shows_origin_owner_field_and_plain_source_as_unverified(self):
        def inspect(dialog, listing):
            detail = dialog.findChild(QPlainTextEdit, 'diagnosticDetail')
            self.assertIsNotNone(detail, 'Unknown candidates need inspectable source and owner details')
            self.assertTrue(detail.isReadOnly())
            text = detail.toPlainText()
            for expected in ('Defs/Panel.xml', 'Example.UnknownComp', 'comps.0.tooltipText',
                             'Move faster when enabled <color=green>now</color>', '未検証', '正式出力'):
                self.assertIn(expected, text)
            self.assertIn('未検証', listing.item(0).text())
        self.open_diagnostics(inspect)

    def test_candidate_double_click_does_not_navigate_to_unrelated_label(self):
        def inspect(dialog, listing):
            with patch.object(self.window, 'navigate_entry') as navigate:
                listing.itemDoubleClicked.emit(listing.item(0))
                navigate.assert_not_called()
        self.open_diagnostics(inspect)

    def test_read_only_review_keeps_saved_translation_approval_and_entry_set(self):
        before = self.path.read_bytes()
        self.open_diagnostics(lambda *_: None)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.path)
        self.assertEqual(len(restored.entries), 1)
        entry = restored.entries[0]
        self.assertEqual(entry.japanese, '保存済みのパネル')
        self.assertTrue(entry.approved)
        self.assertTrue(entry.reviewed)
        self.assertEqual(restored.diagnostics[0]['source_text'], 'Move faster when enabled <color=green>now</color>')

    def test_multiple_legacy_and_truncated_candidates_keep_normal_entry_navigation(self):
        self.window.project.diagnostics.extend([
            dict(code='unknown-field', message='Legacy unknown field', source_file='Defs/Legacy.xml'),
            dict(code='unknown-field', message='Long unknown field', source_text='visible prefix',
                 source_text_truncated=True, source_text_length=5000),
            dict(code='qa', message='Normal entry diagnostic', entry_id=self.window.project.entries[0].id),
        ])
        def inspect(dialog, listing):
            detail = dialog.findChild(QPlainTextEdit, 'diagnosticDetail')
            listing.setCurrentRow(1)
            self.assertIn('Defs/Legacy.xml', detail.toPlainText())
            self.assertIn('不明', detail.toPlainText())
            self.assertNotIn('Example.UnknownComp', detail.toPlainText())
            listing.setCurrentRow(2)
            self.assertIn('省略', detail.toPlainText())
            self.assertIn('5000', detail.toPlainText())
            self.assertIn('visible prefix', detail.toPlainText())
            with patch.object(self.window, 'navigate_entry') as navigate:
                listing.itemDoubleClicked.emit(listing.item(3))
                navigate.assert_called_once_with(self.window.project.entries[0].id)
        self.open_diagnostics(inspect)

"""Diagnostics only navigate through explicit links to existing entries."""
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


class DiagnosticNavigationSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source'
        (source / 'Defs').mkdir(parents=True)
        self.xml = source / 'Defs/Panel.xml'
        self.xml.write_text('<Defs><ThingDef><defName>Panel</defName><label>panel</label></ThingDef>'
                            '<ThingDef><defName>Bad Name</defName><label>invalid label</label></ThingDef></Defs>')
        (source / 'Defs/Other.xml').write_text('<Defs><ThingDef><defName>Other</defName>'
                                              '<label>other</label></ThingDef></Defs>')
        result = scan_mod(source)
        self.assertEqual({entry.key for entry in result.entries}, {'Panel.label', 'Other.label'})
        project = Project.create(source, result)
        for entry in project.entries:
            entry.japanese, entry.approved, entry.reviewed = '保存済み' + entry.key, True, True
        self.path = self.root / 'work/project.json'
        project.save(self.path)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.path)
        self.window.navigate_entry('DefInjected:ThingDef:Other.label')
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def inspect(self, callback):
        def execute(dialog):
            callback(dialog, dialog.findChild(QListWidget))
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', execute):
            self.window.show_warnings()

    def test_real_file_diagnostic_does_not_redirect_to_an_unrelated_label(self):
        before_project, before_xml = self.path.read_bytes(), self.xml.read_bytes()
        def check(dialog, listing):
            row = next(i for i, d in enumerate(self.window.project.diagnostics) if d['code'] == 'unnamed')
            diagnostic = self.window.project.diagnostics[row]
            self.assertEqual(diagnostic['entry_id'], '')
            self.assertIn('Defs/Panel.xml', diagnostic['message'])
            listing.setCurrentRow(row)
            listing.itemDoubleClicked.emit(listing.currentItem())
            self.assertEqual(self.window.current.id, 'DefInjected:ThingDef:Other.label',
                             'A shared XML source is not an entry identity')
            self.assertEqual(dialog.result(), QDialog.Rejected)
            self.assertIn('Defs/Panel.xml', dialog.findChild(QPlainTextEdit, 'diagnosticDetail').toPlainText())
        self.inspect(check)
        self.assertEqual(self.path.read_bytes(), before_project)
        self.assertEqual(self.xml.read_bytes(), before_xml)

    def test_ambiguous_legacy_and_stale_links_keep_review_open_but_explicit_entry_link_works(self):
        self.window.project.diagnostics = [
            dict(message='Legacy warning for Panel.labelExtra'),
            dict(message='Legacy file warning: Defs/Panel.xml'),
            dict(message='Removed entry', entry_id='DefInjected:ThingDef:Removed.label'),
            dict(message='Actual entry warning', entry_id='DefInjected:ThingDef:Panel.label'),
        ]
        self.assertTrue(self.window.save(export=False))
        before_bytes = self.path.read_bytes()
        before_diagnostics = copy.deepcopy(self.window.project.diagnostics)
        def check(dialog, listing):
            for row in range(3):
                with self.subTest(row=row):
                    self.window.navigate_entry('DefInjected:ThingDef:Other.label')
                    dialog.setResult(QDialog.Rejected)
                    listing.setCurrentRow(row)
                    listing.itemDoubleClicked.emit(listing.currentItem())
                    self.assertEqual(self.window.current.id, 'DefInjected:ThingDef:Other.label')
                    self.assertEqual(dialog.result(), QDialog.Rejected,
                                     'An unresolved link must keep the review dialog open')
            listing.setCurrentRow(3)
            listing.itemDoubleClicked.emit(listing.currentItem())
            self.assertEqual(self.window.current.id, 'DefInjected:ThingDef:Panel.label')
            self.assertEqual(dialog.result(), QDialog.Accepted)
        self.inspect(check)
        self.assertEqual(self.path.read_bytes(), before_bytes)
        self.assertEqual(self.window.project.diagnostics, before_diagnostics)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.path)
        self.assertEqual(restored.diagnostics, before_diagnostics)
        self.assertEqual({entry.key for entry in restored.entries}, {'Panel.label', 'Other.label'})
        for entry in restored.entries:
            self.assertEqual(entry.japanese, '保存済み' + entry.key)
            self.assertTrue(entry.approved)
            self.assertTrue(entry.reviewed)

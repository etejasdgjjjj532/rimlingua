"""Reopen the last successful trial snapshot without changing saved bytes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QPlainTextEdit
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window


class TrialReportReopenRound64Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        for relative, text in {
            'About/About.xml': '<ModMetaData><packageId>test.gui64</packageId><supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/main.xml': '<LanguageData><Safe>Hello</Safe><Unsafe>Hello {0}</Unsafe></LanguageData>',
        }.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        project = Project.create_versions(self.source, {
            v: scan_mod(self.source, game_version=v) for v in ('1.6', '1.10')})
        for version in ('1.6', '1.10'):
            project.switch_version(version)
            project.set_translation('Keyed:Keyed:Safe', 'こんにちは ' + version)
            project.set_translation('Keyed:Keyed:Unsafe', '危険')
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.window.resize(960, 760)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def action(self):
        action = self.window.findChild(QAction, 'reopenTrialOutputReport')
        self.assertIsNotNone(action, 'Users need a way to reopen the last successful report without re-exporting')
        return action

    def click_reopen(self):
        action = self.action()
        if not action.isEnabled():
            return
        top = next(a for a in self.window.menuBar().actions() if a.menu() and action in a.menu().actions())
        QTest.mouseClick(self.window.menuBar(), Qt.LeftButton, pos=self.window.menuBar().actionGeometry(top).center())
        self.app.processEvents()
        menu = top.menu()
        QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())
        self.app.processEvents()

    def export(self):
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self.assertTrue(self.window.generate_versions_test())
        self.app.processEvents()
        return self.window.trial_output_report

    @staticmethod
    def tree(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_close_and_escape_reopen_success_snapshot_without_save_or_export(self):
        action = self.action()
        self.assertFalse(action.isEnabled())
        for height in (660, 760):
            self.window.resize(960, height)
            self.app.processEvents()
            for widget in (self.window.table,):
                self.assertTrue(self.window.rect().contains(widget.mapTo(self.window, widget.rect().bottomRight())),
                                f'{widget.objectName() or "table"} must remain inside at 960x{height}')
        report = self.export()
        text = report.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText()
        self.assertIn('1.6 / 危険な訳', text)
        self.assertIn('1.10 / 危険な訳', text)
        self.assertIn('成功時点', text)
        self.window.project.set_translation('Keyed:Keyed:Safe', '後から編集')
        self.window.dirty = True
        before = self.tree(self.root)
        with patch.object(self.window, 'save', side_effect=AssertionError('Reopening must not save')), \
             patch('rimworld_translator.gui.export_versions_test', side_effect=AssertionError('Reopening must not export')):
            for close in ('button', 'escape'):
                if close == 'button':
                    QTest.mouseClick(report.findChild(QDialogButtonBox).button(QDialogButtonBox.Close), Qt.LeftButton)
                else:
                    QTest.keyClick(report, Qt.Key_Escape)
                self.assertFalse(report.isVisible())
                self.assertTrue(action.isEnabled())
                self.click_reopen()
                self.assertTrue(report.isVisible())
                self.assertEqual(report.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText(), text)
                self.assertTrue(self.window.dirty)
                self.assertEqual(self.tree(self.root), before)
        self.assertTrue(action.isVisible())

    def test_successful_project_change_invalidates_reopen_and_busy_disables_it(self):
        report = self.export()
        action = self.action()
        self.window.busy = True
        self.window.set_project_controls(False)
        self.assertFalse(action.isEnabled())
        self.window.busy = False
        self.window.set_project_controls(True)
        self.assertTrue(action.isEnabled())
        other = self.root / 'other/project.json'
        Project.create(self.source, scan_mod(self.source)).save(other)
        self.window.load_project(other)
        self.assertFalse(report.isVisible())
        self.assertFalse(action.isEnabled())
        self.assertIsNone(self.window.trial_output_report)
        self.click_reopen()
        self.assertIsNone(self.window.trial_output_report)

    def test_failed_load_and_failed_export_preserve_reopen_snapshot(self):
        report = self.export()
        action = self.action()
        text = report.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText()
        QTest.keyClick(report, Qt.Key_Escape)
        with patch.object(self.window, 'error'):
            self.window.load_project(self.root / 'missing.json')
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), \
                 patch('rimworld_translator.gui.export_versions_test', side_effect=OSError('Synthetic failure')):
                self.assertFalse(self.window.generate_versions_test())
        self.assertIs(self.window.trial_output_report, report)
        self.assertTrue(action.isEnabled())
        self.click_reopen()
        self.assertTrue(report.isVisible())
        self.assertEqual(report.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText(), text)

"""Trial-output snapshots belong to the loaded project and remain complete."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QPlainTextEdit
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window


class TrialReportProjectBoundaryRound63Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        files = {
            'About/About.xml': '<ModMetaData><packageId>test.gui63</packageId><supportedVersions>'
                '<li>1.10</li><li>1.6</li><li>1.9</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/a.xml': '<LanguageData><Safe>safe</Safe>'
                '<First>first {0}</First><Second>second {0}</Second></LanguageData>',
            'Languages/English/Strings/Names/A.txt': 'Alpha\nBeta\n',
        }
        for relative, content in files.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self.versions = ('1.6', '1.9', '1.10')
        project = Project.create_versions(self.source, {
            v: scan_mod(self.source, game_version=v) for v in self.versions})
        for v in self.versions:
            project.switch_version(v)
            project.set_translation('Keyed:Keyed:Safe', f'安全 {v}')
            for key in ('First', 'Second'):
                project.set_translation(f'Keyed:Keyed:{key}', '危険')
            project.set_translation('Strings:Names/A.txt:line_0', '甲')
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.window.show()
        self.addCleanup(self.close_window)
        self.output = self.saved.parent / 'mod-test'
        self.source_before = self.tree(self.source)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    @staticmethod
    def tree(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def click_trial(self, answer=QMessageBox.Yes):
        seen = []
        def reply():
            box = QApplication.activeModalWidget()
            if isinstance(box, QMessageBox):
                seen.append(box.text())
                if answer == 'close':
                    box.close()
                else:
                    QTest.mouseClick(box.button(answer), Qt.LeftButton)
        QTimer.singleShot(0, reply)
        QTest.mouseClick(self.window.test_export_button, Qt.LeftButton)
        self.app.processEvents()
        self.assertEqual(len(seen), 1)
        self.assertIn('Q17', seen[0])

    def test_successful_project_switch_closes_previous_success_report(self):
        self.click_trial()
        old = self.window.trial_output_report
        self.assertTrue(old.isVisible())
        before = self.tree(self.output)
        other = Project.create(self.source, scan_mod(self.source))
        other_saved = self.root / 'other/project.json'
        other.save(other_saved)
        self.window.load_project(other_saved)
        self.assertEqual(self.window.project_path, other_saved)
        self.assertFalse(old.isVisible(), 'The previous project success report must close on project switch')
        self.assertIsNone(self.window.trial_output_report)
        self.assertEqual(self.tree(self.output), before)
        self.assertEqual(self.tree(self.source), self.source_before)

    def test_failed_project_switch_preserves_success_snapshot_and_output(self):
        self.click_trial()
        old = self.window.trial_output_report
        text = old.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText()
        before = self.tree(self.output)
        broken = self.root / 'broken.json'
        broken.write_text('{broken', encoding='utf-8')
        with patch.object(self.window, 'error'):
            self.window.load_project(broken)
        self.assertEqual(self.window.project_path, self.saved)
        self.assertIs(self.window.trial_output_report, old)
        self.assertTrue(old.isVisible())
        self.assertEqual(old.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText(), text)
        self.assertEqual(self.tree(self.output), before)

    def test_new_project_scan_closes_previous_success_report(self):
        self.click_trial()
        old = self.window.trial_output_report
        before = self.tree(self.output)
        new_path = self.root / 'new-workspace/project.json'
        result = scan_mod(self.source, game_version='1.6')
        self.window.scan_finished(self.source, new_path, result, None)
        self.assertEqual(self.window.project_path, new_path)
        self.assertTrue(new_path.is_file())
        self.assertFalse(old.isVisible(), 'A new project must close the previous project success report')
        self.assertIsNone(self.window.trial_output_report)
        self.assertEqual(self.tree(self.output), before)

    def test_cancelled_or_failed_new_scan_keeps_previous_success_report(self):
        self.click_trial()
        old = self.window.trial_output_report
        before = self.tree(self.output)
        new_path = self.root / 'new-workspace/project.json'
        for error in ('cancelled', 'Synthetic scan failure'):
            with self.subTest(error=error), patch.object(self.window, 'error'):
                self.window.scan_finished(self.source, new_path, None, error)
            self.assertEqual(self.window.project_path, self.saved)
            self.assertIs(self.window.trial_output_report, old)
            self.assertTrue(old.isVisible())
            self.assertFalse(new_path.exists())
            self.assertEqual(self.tree(self.output), before)

    def test_exact_warning_identities_close_cancel_and_retry_with_real_qt(self):
        saved_before = self.saved.read_bytes()
        self.click_trial('close')
        self.assertFalse(self.output.exists())
        self.assertIsNone(self.window.trial_output_report)
        self.assertEqual(self.saved.read_bytes(), saved_before)
        self.click_trial()
        report = self.window.trial_output_report
        text = report.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText()
        # Independent oracle: 1 unverified notice + 3 * (2 unsafe keys + 1 partial Strings).
        notices = text.split('\n\n')[1:]
        self.assertEqual(len(notices), 10)
        self.assertEqual(len(set(notices)), 10)
        self.assertTrue(notices[0].startswith('1. 試験出力:'))
        for index, version in enumerate(self.versions):
            offset = 1 + index * 3
            for i, key in enumerate(('First', 'Second')):
                self.assertIn(f'{version} / 危険な訳を試験出力から除外: Japanese / {key}:', notices[offset+i])
            self.assertIn(f'{version} / Stringsファイルを試験出力から除外: Japanese / Names/A.txt:', notices[offset+2])
            base = self.output / version / 'Languages/Japanese'
            data = ET.parse(base / 'Keyed/Keyed.xml').getroot()
            self.assertEqual([(node.tag, node.text) for node in data], [('Safe', f'安全 {version}')])
            self.assertFalse((base / 'Strings/Names/A.txt').exists())
        before = self.tree(self.output)
        buttons = report.findChild(QDialogButtonBox)
        QTest.mouseClick(buttons.button(QDialogButtonBox.Close), Qt.LeftButton)
        self.assertFalse(report.isVisible())
        self.click_trial(QMessageBox.No)
        self.assertIs(self.window.trial_output_report, report)
        self.assertFalse(report.isVisible())
        self.assertEqual(self.tree(self.output), before)
        self.click_trial()
        updated = self.window.trial_output_report
        self.assertIsNot(updated, report)
        self.assertTrue(updated.isVisible())
        self.assertEqual(updated.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText(), text)
        self.assertEqual(self.tree(self.output), before)
        QTest.keyClick(updated, Qt.Key_Escape)
        self.assertFalse(updated.isVisible())
        self.assertEqual(self.tree(self.source), self.source_before)

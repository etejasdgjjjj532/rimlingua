"""Trial-output notices remain complete, copyable snapshots of successful output."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPlainTextEdit, QPushButton
from rimworld_translator.core import Project, export_mod, export_versions_test, scan_mod
from rimworld_translator.gui import Window


class TrialOutputReportRound59Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        files = {
            'About/About.xml': '<ModMetaData><packageId>test.warningreport</packageId><supportedVersions>'
                '<li>1.10</li><li>1.6</li><li>1.9</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/Trial.xml': '<LanguageData>' + ''.join(
                f'<Notice{i}>Value {{0}}</Notice{i}>' for i in range(12)) + '</LanguageData>',
            'Languages/English/Strings/Names/Trial.txt': 'Alpha\nBeta\n',
        }
        for relative, content in files.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self.original = self.tree(self.source)
        self.versions = ('1.6', '1.9', '1.10')
        project = Project.create_versions(self.source, {
            version: scan_mod(self.source, game_version=version) for version in self.versions})
        for version in self.versions:
            project.switch_version(version)
            for entry in project.entries:
                if entry.kind == 'Keyed':
                    project.set_translation(entry.id, '危険 {9}')
                elif entry.key == 'line_0':
                    project.set_translation(entry.id, '一行だけ')
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.addCleanup(self.close_window)
        self.output = self.saved.parent / 'mod-test'

    def close_window(self):
        for dialog in self.window.findChildren(QDialog):
            dialog.close()
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def tree(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def click_trial(self, answer=QMessageBox.Yes):
        seen = []
        def reply():
            box = QApplication.activeModalWidget()
            if isinstance(box, QMessageBox):
                seen.append(box)
                box.button(answer).click()
        QTimer.singleShot(0, reply)
        self.window.test_export_button.click()
        self.assertEqual(len(seen), 1)
        self.app.processEvents()

    def report(self):
        dialog = getattr(self.window, 'trial_output_report', None)
        self.assertIsNotNone(dialog, 'Successful trial output needs a complete warning report')
        self.assertEqual(dialog.objectName(), 'trialOutputReport')
        return dialog

    def test_all_api_warnings_are_visible_and_copied_as_plain_text(self):
        expected = export_versions_test(self.window.project, self.saved.parent / 'oracle-output')
        self.assertGreater(len(expected), 8)
        self.click_trial()
        report = self.report()
        self.assertTrue(report.isVisible())
        self.assertFalse(report.isModal())
        text = report.findChild(QPlainTextEdit, 'trialOutputNotices')
        self.assertIsNotNone(text)
        self.assertTrue(text.isReadOnly())
        complete = text.toPlainText()
        self.assertTrue(complete.endswith('\n\n'.join(f'{i}. {warning}' for i, warning in enumerate(expected, 1))))
        for token in ('Q17', '未検証', str(self.output), str(len(expected)), '抽出できなかった項目'):
            self.assertIn(token, complete)
        text.verticalScrollBar().setValue(text.verticalScrollBar().maximum())
        self.assertGreater(text.verticalScrollBar().maximum(), 0)
        text.selectAll()
        QTest.keyClicks(text, 'must not replace read-only text')
        self.assertEqual(text.toPlainText(), complete)
        cursor = text.textCursor()
        cursor.clearSelection()
        text.setTextCursor(cursor)
        copy_button = report.findChild(QPushButton, 'copyTrialOutputNotices')
        self.assertIsNotNone(copy_button)
        copy_button.click()
        self.assertEqual(self.app.clipboard().text(), complete)
        with self.assertRaisesRegex(ValueError, 'formal multi-version'):
            export_mod(self.window.project, self.saved.parent / 'mod')
        self.assertEqual(self.tree(self.source), self.original)

    def test_cancel_and_json_failure_do_not_create_success_report(self):
        before = self.saved.read_bytes()
        self.click_trial(QMessageBox.No)
        self.assertIsNone(getattr(self.window, 'trial_output_report', None))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.saved.read_bytes(), before)
        backup = self.saved.with_name('backup.json')
        self.saved.rename(backup)
        self.saved.mkdir()
        with patch.object(self.window, 'error') as errors:
            self.click_trial()
        self.assertTrue(errors.called)
        self.assertIsNone(getattr(self.window, 'trial_output_report', None))
        self.assertFalse(self.output.exists())
        self.saved.rmdir()
        backup.rename(self.saved)
        self.click_trial()
        self.assertTrue(self.report().isVisible())

    def test_failed_output_keeps_previous_report_then_retry_replaces_it(self):
        self.click_trial()
        report = self.report()
        old_text = report.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText()
        before = self.tree(self.output)
        for version in self.versions:
            self.window.project.switch_version(version)
            for entry in self.window.project.entries:
                self.window.project.set_translation(entry.id, '修復 {0}' if entry.kind == 'Keyed' else '修復行')
        self.window.on_edit()
        # A real symlink conflict must leave both previous output and its report intact.
        victim = self.output / '1.6/Languages/Japanese/Keyed/Keyed.xml'
        victim.parent.mkdir(parents=True, exist_ok=True)
        target = self.root / 'protected.txt'
        target.write_text('protected', encoding='utf-8')
        victim.symlink_to(target)
        with patch.object(self.window, 'error') as errors:
            self.click_trial()
        self.assertTrue(errors.called)
        self.assertIs(self.report(), report)
        self.assertEqual(report.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText(), old_text)
        self.assertEqual(target.read_text(), 'protected')
        victim.unlink()
        self.assertEqual(self.tree(self.output), before)
        self.click_trial()
        self.assertIsNot(self.report(), report)
        updated = self.report().findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText()
        self.assertNotIn('危険な訳を試験出力から除外', updated)
        self.assertNotIn('Stringsファイルを試験出力から除外', updated)
        self.assertIn('修復 {0}', (self.output / '1.6/Languages/Japanese/Keyed/Keyed.xml').read_text())
        self.assertEqual(self.tree(self.source), self.original)

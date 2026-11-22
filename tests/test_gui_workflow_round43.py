"""Current-version rescans keep failed saves retryable and source changes isolated."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window


class RescanSaveRecoveryRound43Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def assert_rescan_save_recovery(self, multiple_versions):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            keyed = source / 'Languages/English/Keyed/a.xml'
            keyed.parent.mkdir(parents=True)
            keyed.write_text('<LanguageData><Greeting>Hello</Greeting></LanguageData>')
            about = source / 'About/About.xml'
            about.parent.mkdir()
            about.write_text('<ModMetaData><packageId>test.rescanretry</packageId>'
                '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
            identity = 'Keyed:Keyed:Greeting'
            if multiple_versions:
                project = Project.create_versions(source, {
                    version: scan_mod(source, game_version=version) for version in ('1.6', '1.10')})
                project.switch_version('1.10')
                project.set_translation(identity, '別版で承認済みの訳')
                project.mark_reviewed(identity, approved=True)
                project.switch_version('1.6')
            else:
                project = Project.create(source, scan_mod(source))
            project.set_translation(identity, '変更前の原文で承認した訳')
            project.mark_reviewed(identity, approved=True)
            saved = root / 'workspace/project.json'
            project.save(saved)
            disk = saved.read_bytes()
            window = Window(settings_path=root / 'settings.json')
            try:
                window.load_project(saved)
                self.assertFalse(window.dirty)
                self.assertFalse(window.autosave.isActive())
                keyed.write_text('<LanguageData><Greeting>Hello again</Greeting></LanguageData>')
                result = scan_mod(source)
                blocked = saved.parent / 'blocked.json'
                blocked.mkdir()
                window.project_path = blocked
                window.busy = True
                window.set_project_controls(False)
                # Suppress only the modal error box; scan, merge and JSON failure are real.
                with patch.object(window, 'error'):
                    window.scan_finished(source, None, result, '')
                self.assertTrue(window.dirty)
                self.assertTrue(window.autosave.isActive())
                self.assertNotIn('スキャン完了', window.statusBar().currentMessage())
                self.assertIn('未保存', window.guidance.text())
                self.assertEqual(saved.read_bytes(), disk)
                self.assertTrue(blocked.is_dir())
                self.assertTrue(window.save_button.isEnabled())
                self.assertFalse(window.busy)
                entry = window.project.entry_index()[identity]
                self.assertEqual(entry.english, 'Hello again')
                self.assertEqual(entry.previous_english, 'Hello')
                self.assertEqual(entry.japanese, '変更前の原文で承認した訳')
                self.assertTrue(entry.changed and entry.review)
                self.assertFalse(entry.reviewed or entry.approved)
                window.project_path = saved
                window.autosave.setInterval(20)
                deadline = time.monotonic() + 3
                while window.dirty and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.assertFalse(window.dirty)
                restored = Project.load(saved)
                entry = restored.entry_index()[identity]
                self.assertTrue(entry.changed and entry.review)
                self.assertFalse(entry.reviewed or entry.approved)
                if multiple_versions:
                    restored.switch_version('1.10')
                    entry = restored.entry_index()[identity]
                    self.assertEqual(entry.english, 'Hello')
                    self.assertEqual(entry.japanese, '別版で承認済みの訳')
                    self.assertTrue(entry.reviewed and entry.approved)
                    self.assertFalse(entry.changed or entry.review)
                self.assertFalse((saved.parent / 'mod').exists())
            finally:
                window.dirty = False
                window.close()
                self.app.processEvents()

    def test_single_version_rescan_retries_real_save_failure(self):
        self.assert_rescan_save_recovery(False)

    def test_multiversion_rescan_retries_without_changing_other_version(self):
        self.assert_rescan_save_recovery(True)

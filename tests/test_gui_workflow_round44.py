"""Failed initial exports leave newly scanned projects available for saving."""
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


class InitialScanSaveRecoveryRound44Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def assert_initial_scan_retry(self, failure):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            keyed = source / 'Languages/English/Keyed/a.xml'
            keyed.parent.mkdir(parents=True)
            keyed.write_text('<LanguageData><Greeting>Hello</Greeting></LanguageData>')
            about = source / 'About/About.xml'
            about.parent.mkdir()
            about.write_text('<ModMetaData><packageId>test.initialretry</packageId>'
                '<supportedVersions><li>1.6</li></supportedVersions></ModMetaData>')
            original = keyed.read_bytes()
            workspace = root / 'workspace'
            workspace.mkdir()
            saved = workspace / 'project.json'
            blocker = saved if failure == 'json' else workspace / 'mod'
            if failure == 'json':
                blocker.mkdir()
            else:
                blocker.write_text('keep this existing file')
            window = Window(settings_path=root / 'settings.json')
            try:
                window.busy = True
                window.set_project_controls(False)
                # Suppress the error modal only; both I/O failures are real.
                with patch.object(window, 'error'):
                    window.scan_finished(source, saved, scan_mod(source), '')
                self.assertTrue(window.dirty)
                self.assertTrue(window.autosave.isActive())
                self.assertNotIn('スキャン完了', window.statusBar().currentMessage())
                self.assertIn('未保存', window.guidance.text())
                self.assertTrue(window.save_button.isEnabled())
                self.assertFalse(window.busy)
                self.assertEqual(keyed.read_bytes(), original)
                if failure == 'json':
                    self.assertTrue(blocker.is_dir())
                    blocker.rmdir()
                else:
                    self.assertEqual(blocker.read_text(), 'keep this existing file')
                    blocker.unlink()
                window.autosave.setInterval(20)
                deadline = time.monotonic() + 3
                while window.dirty and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.assertFalse(window.dirty)
                restored = Project.load(saved)
                self.assertEqual(restored.game_version, '1.6')
                self.assertEqual(restored.entry_index()['Keyed:Keyed:Greeting'].english, 'Hello')
                self.assertEqual(restored.get_translation('Keyed:Keyed:Greeting'), '')
                self.assertFalse(restored.entry_index()['Keyed:Keyed:Greeting'].approved)
                self.assertTrue((workspace / 'mod/About/About.xml').is_file())
                self.assertEqual(keyed.read_bytes(), original)
            finally:
                window.dirty = False
                window.close()
                self.app.processEvents()

    def test_new_project_retries_initial_json_save_failure(self):
        self.assert_initial_scan_retry('json')

    def test_new_project_retries_initial_xml_export_failure(self):
        self.assert_initial_scan_retry('xml')

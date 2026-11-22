"""Version additions that fail to save remain visible and retryable."""
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
from rimworld_translator.multiversion import scan_declared_versions


class DeclaredVersionSaveFailureRound42Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_clean_project_version_additions_retry_after_real_save_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            for relative, content in {
                'About/About.xml': '<ModMetaData><packageId>test.versionretry</packageId>'
                    '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>',
                'Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
            }.items():
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            identity = 'Keyed:Keyed:Greeting'
            project = Project.create(source, scan_mod(source))
            project.set_translation(identity, '保持する訳')
            project.mark_reviewed(identity, approved=True)
            saved = root / 'workspace/project.json'
            project.save(saved)
            disk = saved.read_bytes()
            window = Window(settings_path=root / 'settings.json')
            try:
                window.load_project(saved)
                self.assertFalse(window.dirty)
                self.assertFalse(window.autosave.isActive())
                # A directory cannot be replaced by the atomic JSON writer.
                blocked = root / 'workspace/blocked.json'
                blocked.mkdir()
                window.project_path = blocked
                window.busy = True
                window.set_project_controls(False)
                with patch.object(window, 'error') as error:
                    window.declared_scan_finished(scan_declared_versions(source), '')
                self.assertEqual(error.call_count, 1)
                self.assertEqual(saved.read_bytes(), disk)
                self.assertTrue(blocked.is_dir())
                self.assertTrue(window.dirty)
                self.assertEqual(set(window.project.version_profiles), {'1.6', '1.10'})
                self.assertIn('未保存', window.guidance.text())
                self.assertTrue(window.autosave.isActive())
                self.assertTrue(window.version_selector.isEnabled())
                self.assertTrue(window.save_button.isEnabled())
                self.assertFalse(window.busy)
                window.project_path = saved
                window.autosave.setInterval(20)
                deadline = time.monotonic() + 3
                while window.dirty and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.assertFalse(window.dirty)
                restored = Project.load(saved)
                self.assertEqual(restored.game_version, '1.6')
                self.assertEqual(restored.get_translation(identity), '保持する訳')
                self.assertTrue(restored.entry_index()[identity].approved)
                restored.switch_version('1.10')
                self.assertEqual(restored.get_translation(identity), '')
                self.assertFalse(restored.entry_index()[identity].approved)
                self.assertFalse((saved.parent / 'mod').exists())
            finally:
                window.dirty = False
                window.close()
                self.app.processEvents()

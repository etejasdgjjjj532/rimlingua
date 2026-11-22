"""A failed idle save keeps edits recoverable and requests an explicit retry."""
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


class IdleSaveFailureRound57Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate(), 'Expected Qt idle-save state was not reached')

    def assert_idle_save_recovery(self, multiple_versions):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            for relative, content in {
                'About/About.xml': '<ModMetaData><packageId>test.idlesaveretry</packageId>'
                    '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>',
                'Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
            }.items():
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            original = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            if multiple_versions:
                project = Project.create_versions(source, {
                    v: scan_mod(source, game_version=v) for v in ('1.6', '1.10')})
            else:
                project = Project.create(source, scan_mod(source))
            identity = 'Keyed:Keyed:Greeting'
            saved = root / 'workspace/project.json'
            project.save(saved)
            disk = saved.read_bytes()
            window = Window(settings_path=root / 'settings.json')
            try:
                window.load_project(saved)
                # A directory at the atomic writer's destination causes a real
                # I/O failure. Keep the saved bytes separately for restoration.
                backup = saved.with_name('previous.json')
                saved.rename(backup)
                saved.mkdir()
                errors = []
                with patch.object(window, 'error', side_effect=lambda error: errors.append(str(error))):
                    window.autosave.setInterval(20)
                    window.japanese.setPlainText('明示再試行で保持する訳')
                    window.mark_reviewed(approved=True)
                    self.wait_for(lambda: bool(errors))
                    self.assertTrue(window.dirty)
                    self.assertFalse(window.autosave.isActive())
                    self.assertTrue(window.save_button.isEnabled())
                    self.assertEqual(backup.read_bytes(), disk)
                    self.assertTrue(saved.is_dir())
                    self.assertFalse((saved.parent / 'mod').exists())
                    self.assertIn('自動保存に失敗', window.guidance.text())
                    self.assertIn('再試行', window.guidance.text())
                    self.assertIn('未保存', window.statusBar().currentMessage())
                    # Leave the obstruction in place for several idle intervals:
                    # there must be no repeated modal error or implicit retry.
                    stop = time.monotonic() + 0.12
                    while time.monotonic() < stop:
                        self.app.processEvents()
                        time.sleep(0.005)
                    self.assertEqual(len(errors), 1)
                    saved.rmdir()
                    backup.rename(saved)
                    window.save_button.click()
                self.assertFalse(window.dirty)
                restored = Project.load(saved)
                self.assertEqual(restored.get_translation(identity), '明示再試行で保持する訳')
                self.assertTrue(restored.entry_index()[identity].approved)
                if multiple_versions:
                    self.assertEqual(set(restored.version_profiles), {'1.6', '1.10'})
                    restored.switch_version('1.10')
                    self.assertEqual(restored.get_translation(identity), '')
                    self.assertFalse(restored.entry_index()[identity].approved)
                    # The existing Q17 formal all-version block remains intact.
                    self.assertFalse((saved.parent / 'mod').exists())
                else:
                    output = saved.parent / 'mod/Languages/Japanese/Keyed/Keyed.xml'
                    self.assertIn('明示再試行で保持する訳', output.read_text(encoding='utf-8'))
                self.assertEqual({p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}, original)
            finally:
                window.dirty = False
                window.close()
                self.app.processEvents()

    def test_single_version_idle_failure_requests_retry_then_saves(self):
        self.assert_idle_save_recovery(False)

    def test_all_declared_versions_idle_failure_preserves_independent_edits(self):
        self.assert_idle_save_recovery(True)

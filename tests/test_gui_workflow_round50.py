"""Message-less scan failures remain errors and allow a safe retry."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window


class EmptyScanErrorRound50Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def finish_worker(self, window):
        self.assertTrue(window.thread.wait(5000))
        deadline = time.monotonic() + 3
        while window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(window.busy)

    def assert_empty_error_retry(self, declared_versions):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            about = source / 'About/About.xml'
            about.parent.mkdir(parents=True)
            about.write_text('<ModMetaData><packageId>test.emptyerror</packageId>'
                '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
            keyed = source / 'Languages/English/Keyed/a.xml'
            keyed.parent.mkdir(parents=True)
            keyed.write_text('<LanguageData><Greeting>Hello</Greeting></LanguageData>')
            original = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            saved = root / 'workspace/project.json'
            Project.create(source, scan_mod(source)).save(saved)
            disk = saved.read_bytes()
            window = Window(settings_path=root / 'settings.json')
            try:
                window.load_project(saved)
                window.japanese.setPlainText('保持する編集中の訳')
                window.mark_reviewed(approved=True)
                before = copy.deepcopy(window.project)
                errors, slot_errors = [], []
                target = ('rimworld_translator.multiversion.scan_declared_versions' if declared_versions
                          else 'rimworld_translator.gui.scan_mod')
                # Inject an I/O exception at the scan boundary; real workers,
                # queued slots, project state, retry scan and JSON remain real.
                with patch('rimworld_translator.platforms.discover_installations', return_value=[]), \
                     patch.object(window, 'error', side_effect=lambda error: errors.append(str(error))), \
                     patch.object(sys, 'excepthook', side_effect=lambda *error: slot_errors.append(error)):
                    with patch(target, side_effect=OSError()):
                        window.start_scan(source, declared_versions=declared_versions)
                        self.finish_worker(window)
                    self.assertTrue(errors and errors[0], 'The failed scan must show a nonempty error')
                    self.assertEqual(slot_errors, [], 'A failed scan must not crash its GUI result slot')
                    self.assertEqual(window.project, before)
                    self.assertEqual(saved.read_bytes(), disk)
                    self.assertTrue(window.dirty)
                    self.assertTrue(window.autosave.isActive())
                    self.assertTrue(window.save_button.isEnabled())
                    self.assertTrue(window.scan_declared_button.isEnabled())
                    window.start_scan(source, declared_versions=declared_versions)
                    self.finish_worker(window)
                self.assertEqual(len(errors), 1)
                self.assertFalse(window.dirty)
                restored = Project.load(saved)
                identity = 'Keyed:Keyed:Greeting'
                self.assertEqual(restored.get_translation(identity), '保持する編集中の訳')
                self.assertTrue(restored.entry_index()[identity].approved)
                if declared_versions:
                    self.assertEqual(set(restored.version_profiles), {'1.6', '1.10'})
                    restored.switch_version('1.10')
                    self.assertEqual(restored.get_translation(identity), '')
                    self.assertFalse(restored.entry_index()[identity].approved)
                    self.assertFalse((saved.parent / 'mod').exists())
                else:
                    output = saved.parent / 'mod/Languages/Japanese/Keyed/Keyed.xml'
                    self.assertIn('保持する編集中の訳', output.read_text())
                self.assertEqual({p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}, original)
            finally:
                if window.busy:
                    window.cancel_scan()
                    window.thread.wait(20000)
                    self.app.processEvents()
                window.dirty = False
                window.close()
                self.app.processEvents()

    def test_single_version_empty_io_error_preserves_edits_and_retries(self):
        self.assert_empty_error_retry(False)

    def test_declared_versions_empty_io_error_preserves_edits_and_retries(self):
        self.assert_empty_error_retry(True)

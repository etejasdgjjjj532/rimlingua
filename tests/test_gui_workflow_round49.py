"""Cancellation wins until completed scan results are accepted by the GUI."""
import copy
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


class QueuedScanCancellationRound49Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def assert_queued_cancellation(self, declared_versions):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            about = source / 'About/About.xml'
            about.parent.mkdir(parents=True)
            about.write_text('<ModMetaData><packageId>test.queuedcancel</packageId>'
                '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
            keyed = source / 'Languages/English/Keyed/a.xml'
            keyed.parent.mkdir(parents=True)
            keyed.write_text('<LanguageData><Greeting>Hello</Greeting></LanguageData>')
            identity = 'Keyed:Keyed:Greeting'
            project = Project.create(source, scan_mod(source))
            saved = root / 'workspace/project.json'
            project.save(saved)
            disk = saved.read_bytes()
            window = Window(settings_path=root / 'settings.json')
            try:
                window.load_project(saved)
                window.japanese.setPlainText('取消前の編集中の訳')
                window.mark_reviewed(approved=True)
                before = copy.deepcopy(window.project)
                keyed.write_text('<LanguageData><Greeting>Hello again</Greeting></LanguageData>')
                original = keyed.read_bytes()
                # Isolate installation discovery; scanning and Qt delivery stay real.
                with patch('rimworld_translator.platforms.discover_installations', return_value=[]):
                    window.start_scan(source, declared_versions=declared_versions)
                    self.assertTrue(window.thread.wait(5000))
                # Let the real worker finish without delivering queued GUI signals.
                # Cancel is still visible and promises to preserve current data.
                self.assertTrue(window.busy)
                window.cancel_scan()
                deadline = time.monotonic() + 3
                while window.busy and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.assertFalse(window.busy)
                self.assertEqual(window.project, before)
                self.assertEqual(saved.read_bytes(), disk)
                self.assertTrue(window.dirty)
                self.assertTrue(window.autosave.isActive())
                self.assertIn('中止', window.statusBar().currentMessage())
                self.assertTrue(window.save_button.isEnabled())
                self.assertTrue(window.scan_declared_button.isEnabled())
                self.assertFalse((saved.parent / 'mod').exists())
                self.assertTrue(window.save(export=False))
                restored = Project.load(saved)
                self.assertEqual(restored.version_profiles, {})
                self.assertEqual(restored.get_translation(identity), '取消前の編集中の訳')
                self.assertTrue(restored.entry_index()[identity].approved)
                self.assertEqual(restored.entry_index()[identity].english, 'Hello')
                self.assertEqual(keyed.read_bytes(), original)
            finally:
                if window.busy:
                    window.cancel_scan()
                    window.thread.wait(20000)
                    self.app.processEvents()
                window.dirty = False
                window.close()
                self.app.processEvents()

    def test_cancel_queued_single_version_rescan_preserves_pending_edits(self):
        self.assert_queued_cancellation(False)

    def test_cancel_queued_declared_versions_preserves_pending_edits(self):
        self.assert_queued_cancellation(True)

"""A rejected single-version rescan must resume pending translation autosaves."""
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


class SingleVersionAutosaveRound36Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        for relative, content in {
            'About/About.xml': '<ModMetaData><packageId>test.singleautosave</packageId>'
                '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
        }.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        project = Project.create(self.source, scan_mod(self.source))
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.addCleanup(self.close_window)
        self.identity = 'Keyed:Keyed:Greeting'
        self.window.japanese.setPlainText('中止後も保持する訳')
        self.window.mark_reviewed(approved=True)
        self.before = copy.deepcopy(self.window.project)
        self.disk = self.saved.read_bytes()

    def close_window(self):
        if self.window.busy:
            self.window.cancel_scan()
            self.wait_until(lambda: not self.window.busy)
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def wait_until(self, predicate):
        limit = time.monotonic() + 2
        while not predicate() and time.monotonic() < limit:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def assert_pending_work_saved_by_idle_timer(self):
        self.assertEqual(self.window.project, self.before)
        self.assertEqual(self.saved.read_bytes(), self.disk)
        self.assertTrue(self.window.dirty)
        self.window.autosave.setInterval(20)
        self.wait_until(lambda: not self.window.dirty)
        restored = Project.load(self.saved)
        self.assertEqual(restored.get_translation(self.identity), '中止後も保持する訳')
        self.assertTrue(restored.entry_index()[self.identity].approved)
        self.assertEqual(restored.version_profiles, {})

    def test_cancelled_real_worker_restores_pending_autosave(self):
        self.window.start_scan(self.source)
        self.window.auto_save()
        self.assertEqual(self.saved.read_bytes(), self.disk)
        self.window.cancel_scan()
        self.wait_until(lambda: not self.window.busy)
        self.assert_pending_work_saved_by_idle_timer()

    def test_scan_error_restores_pending_autosave(self):
        self.window.autosave.stop()
        with patch.object(self.window, 'error'):
            self.window.scan_finished(self.source, None, None, 'unavailable source')
        self.assert_pending_work_saved_by_idle_timer()

    def test_rejected_other_version_restores_pending_autosave(self):
        result = scan_mod(self.source, game_version='1.10')
        self.window.autosave.stop()
        with patch.object(self.window, 'error'):
            self.window.scan_finished(self.source, None, result, '')
        self.assert_pending_work_saved_by_idle_timer()

    def test_clean_project_stays_clean_after_cancel_error_and_rejected_result(self):
        self.window.save(export=False)
        before = copy.deepcopy(self.window.project)
        disk = self.saved.read_bytes()
        result = scan_mod(self.source, game_version='1.10')
        with patch.object(self.window, 'error'):
            for scan, error in ((None, 'cancelled'), (None, 'unavailable source'), (result, '')):
                with self.subTest(error=error):
                    self.window.scan_finished(self.source, None, scan, error)
                    self.assertFalse(self.window.dirty)
                    self.assertFalse(self.window.autosave.isActive())
                    self.assertEqual(self.window.project, before)
                    self.assertEqual(self.saved.read_bytes(), disk)

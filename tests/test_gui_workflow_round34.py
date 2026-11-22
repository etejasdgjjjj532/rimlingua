"""Adding declared versions must preserve existing extraction and translation state."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import DeclaredVersionScanner, Window
from rimworld_translator.multiversion import scan_declared_versions


class DeclaredVersionGuiRound34Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        for relative, content in {
            'About/About.xml': '<ModMetaData><packageId>test.declaredgui</packageId>'
                '<supportedVersions><li>1.6</li><li>1.9</li><li>1.10</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
        }.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        project = Project.create(self.source, scan_mod(self.source, active_mods=['test.context']))
        self.identity = 'Keyed:Keyed:Greeting'
        project.set_translation(self.identity, '保持する訳')
        project.mark_reviewed(self.identity, approved=True)
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        # The declared-version scan reads a matching installed game; tests must not depend on the developer's own.
        discovery = patch('rimworld_translator.platforms.discover_installations', return_value=[])
        discovery.start()
        self.addCleanup(discovery.stop)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.addCleanup(self.close_window)

    def close_window(self):
        if self.window.busy:
            self.window.cancel_scan()
            self.wait_scan()
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def wait_scan(self):
        limit = time.monotonic() + 10
        while self.window.busy and time.monotonic() < limit:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(self.window.busy)

    def test_button_adds_missing_versions_without_overwriting_existing_context_or_approval(self):
        button = self.window.findChild(QPushButton, 'scanDeclaredVersions')
        self.assertIsNotNone(button, 'Missing declared versions need an editor scan entry point')
        self.window.japanese.setPlainText('未保存の編集')
        self.window.mark_reviewed(approved=True)
        self.window.project._stash_version()
        before = copy.deepcopy(self.window.project.version_profiles['1.6'])
        QTimer.singleShot(0, lambda: self.window.findChild(QMessageBox).button(QMessageBox.Yes).click())
        button.click()
        self.assertTrue(self.window.busy)
        self.assertFalse(button.isEnabled())
        self.wait_scan()
        restored = Project.load(self.saved)
        self.assertEqual(restored.game_version, '1.6')
        self.assertEqual(restored.version_profiles['1.6'], before)
        self.assertEqual(restored.get_translation(self.identity), '未保存の編集')
        self.assertTrue(restored.entry_index()[self.identity].approved)
        for version in ('1.9', '1.10'):
            restored.switch_version(version)
            self.assertEqual(restored.get_translation(self.identity), '')
            self.assertFalse(restored.active_mods_known)
            self.assertFalse(restored.version_profiles[version]['coverage']['source_verified'])
        # Keep refresh available: About.xml can declare new versions later.
        self.assertTrue(button.isEnabled())
        self.assertFalse((self.saved.parent / 'mod').exists())

    def test_cancel_and_partial_failure_preserve_dirty_project_and_disk(self):
        self.assertTrue(hasattr(self.window, 'declared_scan_finished'), 'Transactional completion is required')
        self.window.japanese.setPlainText('未保存')
        before = copy.deepcopy(self.window.project)
        disk = self.saved.read_bytes()
        self.window.declared_scan_finished(None, 'cancelled')
        self.assertEqual(self.window.project, before)
        result = scan_declared_versions(self.source)
        result.failures['1.10'] = 'OSError: unavailable source'
        result.scans.pop('1.10')
        with patch.object(self.window, 'error') as error:
            self.window.declared_scan_finished(result, '')
            self.assertTrue(error.called)
        self.assertEqual(self.window.project, before)
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.saved.read_bytes(), disk)

    def test_save_failure_keeps_added_versions_in_memory_dirty_and_existing_disk(self):
        self.assertTrue(hasattr(self.window, 'declared_scan_finished'), 'Transactional completion is required')
        disk = self.saved.read_bytes()
        result = scan_declared_versions(self.source)
        with patch.object(Project, 'save', side_effect=OSError('read-only test destination')):
            with patch.object(self.window, 'error'):
                self.window.declared_scan_finished(result, '')
        self.assertEqual(set(self.window.project.version_profiles), {'1.6', '1.9', '1.10'})
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.saved.read_bytes(), disk)

    def test_declined_dialog_does_not_start_scanning_or_modify_work(self):
        button = self.window.findChild(QPushButton, 'scanDeclaredVersions')
        self.assertIsNotNone(button)
        self.window.japanese.setPlainText('保持する未保存編集')
        before = copy.deepcopy(self.window.project)
        disk = self.saved.read_bytes()
        QTimer.singleShot(0, lambda: self.window.findChild(QMessageBox).button(QMessageBox.No).click())
        button.click()
        self.assertFalse(self.window.busy)
        self.assertEqual(self.window.project, before)
        self.assertEqual(self.saved.read_bytes(), disk)
        self.assertTrue(self.window.dirty)

    def test_real_worker_cancellation_does_not_return_partial_scans(self):
        worker = DeclaredVersionScanner(self.source)
        results = []
        worker.finished.connect(lambda result, error: results.append((result, error)))
        worker.progress.connect(lambda *_: worker.cancel.set())
        worker.run()
        self.assertEqual(results, [(None, 'cancelled')])

    def test_invalid_late_version_is_atomic_before_committing_any_profile(self):
        result = scan_declared_versions(self.source)
        result.scans['1.10'].package_id = 'test.other'
        before = copy.deepcopy(self.window.project)
        disk = self.saved.read_bytes()
        with patch.object(self.window, 'error') as error:
            self.window.declared_scan_finished(result, '')
            self.assertTrue(error.called)
        self.assertEqual(self.window.project, before)
        self.assertEqual(self.saved.read_bytes(), disk)

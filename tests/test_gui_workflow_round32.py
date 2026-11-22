"""Switch scanned game versions without transferring edits or approvals."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QComboBox
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window


class GuiWorkflowRound32Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        for relative, content in {
            'About/About.xml': '<ModMetaData><packageId>test.versiongui</packageId>'
                '<supportedVersions><li>1.6</li><li>1.9</li><li>1.10</li></supportedVersions></ModMetaData>',
            'LoadFolders.xml': '<loadFolders><v1.6><li>1.6</li></v1.6>'
                '<v1.10><li>1.10</li></v1.10></loadFolders>',
            '1.6/Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
            '1.10/Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello newer</Greeting></LanguageData>',
        }.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self.window = Window(settings_path=self.root / 'settings.json')
        self.addCleanup(self.close_window)
        self.saved = self.root / 'workspace/project.json'
        self.identity = 'Keyed:Keyed:Greeting'

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def selector(self):
        selector = self.window.findChild(QComboBox, 'editingVersion')
        self.assertIsNotNone(selector, 'The editor must offer scanned game versions')
        return selector

    def test_version_selection_keeps_unsaved_text_and_approval_separate_after_save(self):
        project = Project.create_versions(self.source, {
            version: scan_mod(self.source, game_version=version)
            for version in ('1.6', '1.10')})
        project.save(self.saved)
        self.window.load_project(self.saved)
        selector = self.selector()
        self.assertEqual([selector.itemData(i) for i in range(selector.count())], ['1.6', '1.10'])
        self.window.japanese.setPlainText('編集中の挨拶')
        self.window.mark_reviewed(approved=True)
        self.window.undo_batches[:] = [object()]
        self.window.redo_batches[:] = [object()]
        self.window.search.setText('Greeting')
        disk_before = self.saved.read_bytes()

        selector.setCurrentIndex(selector.findData('1.10'))

        self.assertEqual(self.window.project.game_version, '1.10')
        self.assertEqual(self.window.current.english, 'Hello newer')
        self.assertEqual(self.window.japanese.toPlainText(), '')
        self.assertFalse(self.window.current.approved)
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window.search.text(), 'Greeting')
        self.assertEqual(self.window.undo_batches, [])
        self.assertEqual(self.window.redo_batches, [])
        self.assertEqual(self.saved.read_bytes(), disk_before)
        self.window.japanese.setPlainText('新版の挨拶')
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.saved)
        self.assertEqual(restored.game_version, '1.10')
        self.assertEqual(restored.get_translation(self.identity), '新版の挨拶')
        self.assertFalse(restored.entry_index()[self.identity].approved)
        restored.switch_version('1.6')
        self.assertEqual(restored.get_translation(self.identity), '編集中の挨拶')
        self.assertTrue(restored.entry_index()[self.identity].approved)
        selector.setCurrentIndex(selector.findData('1.6'))
        self.assertEqual(self.window.japanese.toPlainText(), '編集中の挨拶')

    def test_legacy_single_version_does_not_offer_unscanned_declarations(self):
        project = Project.create(self.source, scan_mod(self.source, game_version='1.6'))
        project.save(self.saved)
        self.window.load_project(self.saved)
        selector = self.selector()
        self.assertEqual([selector.itemData(i) for i in range(selector.count())], ['1.6'])
        self.assertFalse(selector.isEnabled())
        self.assertFalse(self.window.dirty)

    def test_scan_disables_version_switch_and_restores_it_after_cancel(self):
        project = Project.create_versions(self.source, {
            version: scan_mod(self.source, game_version=version)
            for version in ('1.6', '1.10')})
        project.save(self.saved)
        self.window.load_project(self.saved)
        selector = self.selector()
        self.assertTrue(selector.isEnabled())
        self.window.busy = True
        self.window.set_project_controls(False)
        self.assertFalse(selector.isEnabled())
        self.window.scan_finished(self.source, None, None, 'cancelled')
        self.assertTrue(selector.isEnabled())
        self.assertEqual(self.window.project.game_version, '1.6')
        self.assertFalse(self.window.dirty)


if __name__ == '__main__':
    unittest.main()

"""Widget and background-worker integration tests (offscreen or Wayland)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication
from rimworld_translator.gui import Window
from rimworld_translator.core import Project, scan_mod


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        (self.source / 'Defs').mkdir(parents=True)
        (self.source / 'Defs/Items.xml').write_text('<Defs><ThingDef><defName>Gun</defName><label>gun</label><description>long text</description></ThingDef></Defs>')
        self.project_path = self.root / 'workspace/project.json'
        self.window = Window(settings_path=self.root/'ui-settings.json')
        self.window.settings.data['inspect_metadata'] = False
        self.window.error = lambda message: self.fail(str(message))
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.close_window)
    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()
    def wait_scan(self):
        deadline = time.monotonic() + 10
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertFalse(self.window.busy)
        self.app.processEvents()
    def test_detail_pane_does_not_overlap_on_a_1366x768_screen(self):
        self.window.resize(1366, 720)
        self.window.start_scan(self.source, self.project_path)
        self.wait_scan()
        self.window.table.setCurrentIndex(self.window.proxy.index(0, 0))
        self.app.processEvents()
        detail = self.window.notice.parentWidget()
        self.assertFalse(self.window.editor_eyebrow.isVisible())
        for editor in (self.window.english, self.window.japanese):
            self.assertLessEqual(editor.geometry().bottom(), self.window.notice.geometry().top(),
                                 'notice box overlaps the editors')
        self.assertGreaterEqual(detail.height(), detail.minimumHeight())

    def test_worker_edit_save_filter_rescan_export(self):
        original = self.window.scan_finished
        def verified_receiver(*args):
            self.assertEqual(QThread.currentThread(), self.app.thread())
            original(*args)
        self.window.scan_finished = verified_receiver
        self.window.start_scan(self.source, self.project_path)
        self.wait_scan()
        self.assertEqual(self.window.model.rowCount(), 2)
        self.assertTrue((self.project_path.parent / 'mod/About/About.xml').exists())
        self.window.table.setCurrentIndex(self.window.proxy.index(0, 0))
        self.window.japanese.setPlainText('銃')
        self.assertEqual(self.window.model.entries[0].japanese, '銃')
        self.assertTrue(self.window.dirty)
        self.assertTrue(self.window.save())
        self.assertEqual(Project.load(self.project_path).entries[0].japanese, '銃')
        self.assertTrue(self.window.generate())
        root = ET.parse(self.project_path.parent / 'mod/Languages/Japanese/DefInjected/ThingDef/Translations.xml').getroot()
        self.assertEqual(root.findtext('Gun.label'), '銃')
        self.window.search.setText('銃')
        self.assertEqual(self.window.proxy.rowCount(), 1)
        self.window.search.clear()
        (self.source / 'Defs/Items.xml').write_text('<Defs><ThingDef><defName>Gun</defName><label>updated gun</label></ThingDef></Defs>')
        self.window.rescan()
        self.wait_scan()
        entry = next(e for e in self.window.project.entries if e.key == 'Gun.label')
        self.assertEqual(entry.japanese, '銃')
        self.assertEqual(entry.status, 'changed')
        self.window.table.setCurrentIndex(self.window.proxy.index(0, 0))
        self.window.mark_reviewed()
        self.assertEqual(entry.status, 'translated')
        self.window.auto_save()
        self.assertFalse(self.window.dirty)
    def test_rescan_reports_keys_moved_to_handle_names(self):
        self.window.start_scan(self.source, self.project_path)
        self.wait_scan()
        old = next(e for e in self.window.project.entries if e.key == 'Gun.label')
        self.window.project.set_translation(old.id, '銃')
        result = scan_mod(self.source)
        renamed = next(e for e in result.entries if e.key == 'Gun.label')
        renamed.legacy_keys = [renamed.id]
        renamed.key, renamed.id = 'Gun.stages.Gun.label', 'DefInjected:ThingDef:Gun.stages.Gun.label'
        self.window.scan_finished(self.source, None, result, '')
        message = self.window.statusBar().currentMessage()
        self.assertTrue('名前方式' in message or 'handle names' in message, message)
        self.assertEqual(self.window.project.get_translation(renamed.id), '銃')
    def test_onboarding_progress_and_primary_action(self):
        self.assertIs(self.window.views.currentWidget(), self.window.welcome_page)
        self.assertFalse(self.window.export_button.isEnabled())
        self.assertTrue(self.window.new_button.isEnabled())
        Project.create(self.source, scan_mod(self.source)).save(self.project_path)
        self.window.load_project(self.project_path)
        self.assertIs(self.window.views.currentWidget(), self.window.editor_page)
        self.assertTrue(self.window.export_button.isEnabled())
        self.assertEqual(self.window.progress.value(), 0)
        self.assertIn('0 / 2', self.window.progress_text.text())
        self.assertTrue(self.window.model.setData(self.window.model.index(0, 3), '日本語', Qt.EditRole))
        from PySide6.QtTest import QTest
        # the bar slides to its value while the window is shown
        deadline = time.monotonic() + 3
        while self.window.progress.value() != 50 and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertEqual(self.window.progress.value(), 50)
        self.assertIn('1 / 2', self.window.progress_text.text())
        self.window.next_untranslated.click()
        self.assertEqual(self.window.status_filter.currentData(), 'untranslated')
        self.assertEqual(self.window.proxy.rowCount(), 1)
        self.assertTrue(self.window.generate())
        self.assertTrue((self.project_path.parent / 'mod/About/About.xml').is_file())
        self.assertIn('生成しました', self.window.guidance.text())

    def test_language_management_preserves_earlier_translation(self):
        from unittest.mock import patch
        Project.create(self.source, scan_mod(self.source)).save(self.project_path)
        self.window.load_project(self.project_path)
        self.assertEqual(self.window.language_selector.count(), 1)
        self.assertTrue(self.window.manage_languages.isEnabled())
        with patch("rimworld_translator.gui.select_languages", return_value=["Japanese", "French"]):
            self.window.manage_languages_dialog()
        self.assertEqual(self.window.language_selector.count(), 2)
        self.window.table.setCurrentIndex(self.window.proxy.index(0, 0))
        self.window.japanese.setPlainText("日本語訳テスト")
        self.window.language_selector.setCurrentIndex(1)
        self.window.table.setCurrentIndex(self.window.proxy.index(0, 0))
        self.window.japanese.setPlainText("Traduction test")
        self.window.language_selector.setCurrentIndex(0)
        self.assertEqual(self.window.japanese.toPlainText(), "日本語訳テスト")
        self.assertTrue(self.window.generate())
        self.assertEqual(Project.load(self.project_path).languages, ["Japanese", "French"])
        self.assertTrue((self.project_path.parent / "mod/Languages/French/DefInjected/ThingDef/Translations.xml").exists())

    def test_model_inline_edit_and_open(self):
        Project.create(self.source, scan_mod(self.source)).save(self.project_path)
        self.window.load_project(self.project_path)
        index = self.window.model.index(0, 3)
        self.assertTrue(self.window.model.setData(index, 'テスト', Qt.EditRole))
        self.assertEqual(self.window.japanese.toPlainText(), 'テスト')
        self.window.status_filter.setCurrentIndex(2)
        self.assertEqual(self.window.proxy.rowCount(), 1)
        self.assertTrue(self.window.save())

if __name__ == '__main__': unittest.main()

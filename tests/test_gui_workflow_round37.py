"""JSON-only saves must accurately distinguish persisted edits from game XML."""
import hashlib
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Project, export_versions_test, scan_mod
from rimworld_translator.gui import Window


class SaveStatusRound37Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source'
        for relative, content in {
            'About/About.xml': '<ModMetaData><packageId>test.savestatus</packageId>'
                '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
        }.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        project = Project.create_versions(source, {
            version: scan_mod(source, game_version=version) for version in ('1.6', '1.10')})
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.addCleanup(self.close_window)
        self.identity = 'Keyed:Keyed:Greeting'
        self.output = self.saved.parent / 'mod'

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def output_hashes(self):
        return {str(path.relative_to(self.output)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.output.rglob('*') if path.is_file()}

    def test_json_only_save_does_not_claim_xml_exists_in_either_ui_language(self):
        for language, message in (
            ('ja', '作業データは保存済み。ゲーム用 XML は更新していません。'),
            ('en', 'Project saved. Game XML was not updated.'),
        ):
            with self.subTest(language=language):
                self.window.set_gui_language(language)
                self.window.japanese.setPlainText('保存する訳 ' + language)
                self.assertTrue(self.window.save(export=False))
                self.assertFalse(self.output.exists())
                self.assertFalse(self.window.dirty)
                self.assertEqual(Project.load(self.saved).get_translation(self.identity), '保存する訳 ' + language)
                self.assertEqual(self.window.guidance.text(), message)

    def test_json_only_save_after_version_switch_preserves_old_xml_and_other_version(self):
        self.window.japanese.setPlainText('旧版の訳')
        self.window.mark_reviewed(approved=True)
        export_versions_test(self.window.project, self.output)
        hashes = self.output_hashes()
        self.assertTrue(hashes)
        self.window.version_selector.setCurrentIndex(self.window.version_selector.findData('1.10'))
        self.window.japanese.setPlainText('新版の編集中の訳')
        self.assertTrue(self.window.save(export=False))
        self.assertEqual(self.output_hashes(), hashes)
        restored = Project.load(self.saved)
        self.assertEqual(restored.game_version, '1.10')
        self.assertEqual(restored.get_translation(self.identity), '新版の編集中の訳')
        self.assertFalse(restored.entry_index()[self.identity].approved)
        restored.switch_version('1.6')
        self.assertEqual(restored.get_translation(self.identity), '旧版の訳')
        self.assertTrue(restored.entry_index()[self.identity].approved)
        self.assertEqual(self.window.guidance.text(), '作業データは保存済み。ゲーム用 XML は更新していません。')

    def test_normal_single_version_save_updates_xml_and_reports_it(self):
        source = Path(self.window.project.source)
        Project.create(source, scan_mod(source)).save(self.saved)
        self.window.load_project(self.saved)
        self.window.japanese.setPlainText('版別XMLの訳')
        self.assertTrue(self.window.save())
        self.assertIn('版別XMLの訳', (self.output / 'Languages/Japanese/Keyed/Keyed.xml').read_text())
        self.assertEqual(self.window.guidance.text(), '保存済み。ゲーム用 XML も更新しました。')

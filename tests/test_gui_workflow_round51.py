"""Version context and unverified coverage remain visible while editing."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QLabel
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window


class VersionContextDisplayRound51Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        for relative, content in {
            'About/About.xml': '<ModMetaData><packageId>test.contextdisplay</packageId>'
                '<supportedVersions><li>1.6</li><li>1.9</li><li>1.10</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
        }.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.original = {p.relative_to(self.source): p.read_bytes()
                         for p in self.source.rglob('*') if p.is_file()}
        project = Project.create_versions(self.source, {
            version: scan_mod(self.source, game_version=version, active_mods=active)
            for version, active in [('1.6', ['test.context']), ('1.9', []), ('1.10', None)]})
        self.identity = 'Keyed:Keyed:Greeting'
        project.set_translation(self.identity, '元版だけの訳')
        project.mark_reviewed(self.identity, approved=True)
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def status_label(self):
        label = self.window.findChild(QLabel, 'versionContextStatus')
        self.assertIsNotNone(label, 'Version-specific context and coverage need a persistent editor label')
        self.assertFalse(label.isHidden())
        return label

    def assert_unverified(self, label, version):
        self.assertIn(version, label.text())
        self.assertIn('原文未検証', label.text())
        self.assertIn('ゲーム未検証', label.text())

    def test_switch_displays_unknown_empty_and_explicit_context_without_sharing_translation(self):
        label = self.status_label()
        self.assert_unverified(label, '1.6')
        self.assertIn('前提構成: 1件', label.text())
        self.assertIn('test.context', label.toolTip())
        for version, context in [('1.9', '前提構成: 0件'), ('1.10', '前提構成: 未指定')]:
            self.window.version_selector.setCurrentIndex(self.window.version_selector.findData(version))
            self.assert_unverified(label, version)
            self.assertIn(context, label.text())
            self.assertNotIn('test.context', label.toolTip())
            self.assertEqual(self.window.project.get_translation(self.identity), '')
            self.assertFalse(self.window.project.entry_index()[self.identity].approved)
        self.window.version_selector.setCurrentIndex(self.window.version_selector.findData('1.6'))
        self.assertEqual(self.window.project.get_translation(self.identity), '元版だけの訳')
        self.assertTrue(self.window.project.entry_index()[self.identity].approved)

    def test_future_version_unverified_context_survives_save_and_reload(self):
        self.window.version_selector.setCurrentIndex(self.window.version_selector.findData('1.10'))
        self.assertTrue(self.window.save(export=False))
        disk = self.saved.read_bytes()
        self.window.load_project(self.saved)
        label = self.status_label()
        self.assert_unverified(label, '1.10')
        self.assertIn('前提構成: 未指定', label.text())
        self.assertEqual(self.saved.read_bytes(), disk)
        self.assertFalse(self.window.dirty)
        self.assertFalse((self.saved.parent / 'mod').exists())
        self.assertEqual({p.relative_to(self.source): p.read_bytes()
                          for p in self.source.rglob('*') if p.is_file()}, self.original)

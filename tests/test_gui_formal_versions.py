"""GUI formal multi-version export: ready versions only, held versions reported (Q17 A)."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PySide6.QtWidgets import QApplication, QPlainTextEdit
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window


class FormalVersionGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        files = {
            'About/About.xml': '<ModMetaData><packageId>test.guiformal</packageId><supportedVersions>'
                '<li>1.4</li><li>1.5</li><li>1.6</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
        }
        for relative, content in files.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self.original = self.tree(self.source)
        project = Project.create_versions(self.source, {
            version: scan_mod(self.source, game_version=version) for version in ('1.4', '1.5', '1.6')})
        for version in ('1.5', '1.6'):  # 1.4 stays untranslated -> held
            project.switch_version(version)
            project.set_translation('Keyed:Keyed:Greeting', f'挨拶{version}')
            project.mark_reviewed('Keyed:Keyed:Greeting', approved=True)
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.addCleanup(self.close_window)
        self.output = self.saved.parent / 'mod'

    def close_window(self):
        self.window.close_trial_output_report()
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def tree(self, root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_export_button_writes_ready_versions_and_reports_held(self):
        self.assertTrue(self.window.generate())
        about = ET.parse(self.output / 'About/About.xml')
        self.assertEqual([node.text for node in about.findall('supportedVersions/li')], ['1.5', '1.6'])
        for version in ('1.4', '1.5', '1.6'):
            self.assertFalse((self.output / version).exists())
        self.assertFalse((self.output / 'LoadFolders.xml').exists())
        # One set for every version: the newest ready version's text wins where the versions differ.
        keyed = ET.parse(self.output / 'Languages/Japanese/Keyed/Keyed.xml')
        self.assertEqual(keyed.findtext('Greeting'), '挨拶1.6')
        marker = json.loads((self.output / '.rimworld-translator.json').read_text(encoding='utf-8'))
        self.assertTrue(marker['formal'])
        self.assertTrue(marker['shared'])
        self.assertEqual(list(marker['held_versions']), ['1.4'])
        report = self.window.trial_output_report.findChild(QPlainTextEdit, 'trialOutputNotices').toPlainText()
        for token in ('1.5, 1.6', '1.4', '保留', str(self.output)):
            self.assertIn(token, report)
        self.assertIn('1.4', self.window.guidance.text())
        self.assertEqual(self.tree(self.source), self.original)

    def test_nothing_ready_reports_error_and_writes_nothing(self):
        for version in ('1.5', '1.6'):
            self.window.project.switch_version(version)
            self.window.project.set_translation('Keyed:Keyed:Greeting', '')
        seen = []
        self.window.error = seen.append
        self.assertFalse(self.window.generate())
        self.assertFalse(self.output.exists())
        self.assertIn('No version is ready', str(seen[0]))


if __name__ == '__main__':
    unittest.main()

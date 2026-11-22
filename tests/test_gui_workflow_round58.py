"""Explicit GUI trial output preserves the formal release boundary and saved work."""
import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from rimworld_translator.core import Project, export_mod, scan_mod
from rimworld_translator.gui import Window


class DeclaredTrialOutputRound58Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        files = {
            'About/About.xml': '<ModMetaData><packageId>test.guitrial</packageId><supportedVersions>'
                '<li>1.10</li><li>1.5</li><li>1.9</li><li>1.6</li></supportedVersions></ModMetaData>',
            'Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
            'Defs/Things.xml': '<Defs><ThingDef><defName>Widget</defName><label>widget</label></ThingDef></Defs>',
            'Languages/English/Strings/Names/Audit.txt': 'Alpha\nBeta\n',
        }
        for relative, content in files.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self.original = self.bytes_tree(self.source)
        self.versions = ('1.5', '1.6', '1.9', '1.10')
        project = Project.create_versions(self.source, {
            version: scan_mod(self.source, game_version=version) for version in self.versions})
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.addCleanup(self.close_window)
        self.output = self.saved.parent / 'mod-test'
        self.formal = self.saved.parent / 'mod'
        legacy = Project.create(self.source, scan_mod(self.source))
        legacy.package_id = project.package_id
        export_mod(legacy, self.formal)
        self.formal_before = self.bytes_tree(self.formal)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def bytes_tree(self, root):
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob('*') if path.is_file()}

    def button(self):
        button = getattr(self.window, 'test_export_button', None)
        self.assertIsNotNone(button, 'A separate, explicitly unverified trial-output action is required')
        return button

    def click_trial(self, answer=QMessageBox.Yes):
        button = self.button()
        seen = []
        def reply():
            box = QApplication.activeModalWidget()
            if isinstance(box, QMessageBox):
                seen.append(box.text())
                box.button(answer).click()
        QTimer.singleShot(0, reply)
        button.click()
        self.assertEqual(len(seen), 1, 'Trial output requires its own confirmation')
        for token in ('Q17', '正式', '未検証', str(self.output)):
            self.assertIn(token, seen[0])

    def edit_keyed(self, translation):
        row = self.window.model.row_for_id['Keyed:Keyed:Greeting']
        self.window.table.setCurrentIndex(self.window.proxy.mapFromSource(self.window.model.index(row, 0)))
        self.window.japanese.setPlainText(translation)
        self.window.mark_reviewed(approved=True)

    def test_confirmation_cancel_and_busy_or_legacy_cannot_publish(self):
        self.edit_keyed('保存しない訳')
        self.assertIn('試験出力', self.window.guidance.text())
        self.assertNotIn('XML も自動更新', self.window.guidance.text())
        before = self.saved.read_bytes()
        self.click_trial(QMessageBox.No)
        self.assertEqual(self.saved.read_bytes(), before)
        self.assertTrue(self.window.dirty)
        self.assertFalse(self.output.exists())
        self.window.busy = True
        self.window.set_project_controls(False)
        self.assertFalse(self.button().isEnabled())
        self.window.busy = False
        self.window.set_project_controls(True)
        self.assertTrue(self.button().isEnabled())
        self.window.dirty = False
        Project.create(self.source, scan_mod(self.source)).save(self.saved)
        self.window.load_project(self.saved)
        self.assertFalse(self.button().isEnabled())
        self.assertFalse(self.output.exists())

    def test_four_versions_export_independent_xml_txt_and_open_trial_folder(self):
        for version in self.versions:
            self.window.version_selector.setCurrentIndex(self.window.version_selector.findData(version))
            for entry in list(self.window.project.entries):
                row = self.window.model.row_for_id[entry.id]
                self.window.model.setData(self.window.model.index(row, 3), f'訳{version} {entry.key}')
            self.edit_keyed(f'挨拶{version}')
        self.click_trial()
        self.assertFalse(self.window.dirty)
        manifest = json.loads((self.output / '.rimworld-translator.json').read_text())
        self.assertTrue(manifest['test_only'])
        self.assertEqual(manifest['unverified_versions'], list(self.versions))
        self.assertEqual(set(manifest['files']), set(self.bytes_tree(self.output)) - {'.rimworld-translator.json'})
        self.assertEqual(len(manifest['files']), 15)
        self.assertEqual([node.text for node in ET.parse(self.output / 'About/About.xml').findall('supportedVersions/li')], list(self.versions))
        restored = Project.load(self.saved)
        for version in self.versions:
            restored.switch_version(version)
            self.assertEqual(restored.get_translation('Keyed:Keyed:Greeting'), f'挨拶{version}')
            self.assertTrue(restored.entry_index()['Keyed:Keyed:Greeting'].approved)
            keyed = ET.parse(self.output / version / 'Languages/Japanese/Keyed/Keyed.xml')
            self.assertEqual(keyed.findtext('Greeting'), f'挨拶{version}')
            defs = ET.parse(self.output / version / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml')
            self.assertEqual(defs.findtext('Widget.label'), f'訳{version} Widget.label')
            txt = (self.output / version / 'Languages/Japanese/Strings/Names/Audit.txt').read_bytes()
            self.assertEqual(txt, f'訳{version} line_0\n訳{version} line_1\n'.encode())
        with self.assertRaisesRegex(ValueError, 'formal multi-version'):
            export_mod(restored, self.formal)
        self.assertIn(str(self.output), self.window.location.text())
        self.assertIn('試験', self.window.guidance.text())
        with patch('rimworld_translator.gui.QDesktopServices.openUrl', return_value=True) as opened:
            self.window.open_export_folder()
        self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), self.output)  # QUrl uses '/' on Windows too
        self.assertEqual(self.bytes_tree(self.formal), self.formal_before)
        self.assertEqual(self.bytes_tree(self.source), self.original)

    def test_json_failure_stops_trial_output_then_explicit_retry_saves(self):
        self.edit_keyed('保存失敗後も保持する訳')
        before = copy.deepcopy(self.window.project)
        before._stash_version()
        backup = self.saved.with_name('previous.json')
        self.saved.rename(backup)
        self.saved.mkdir()
        errors = []
        with patch.object(self.window, 'error', side_effect=lambda error: errors.append(str(error))):
            self.click_trial()
            self.assertTrue(errors)
            self.assertTrue(self.window.dirty)
            self.assertEqual(self.window.project, before)
            self.assertFalse(self.output.exists())
            self.saved.rmdir()
            backup.rename(self.saved)
            self.click_trial()
        self.assertFalse(self.window.dirty)
        self.assertEqual(Project.load(self.saved).get_translation('Keyed:Keyed:Greeting'), '保存失敗後も保持する訳')
        self.assertTrue((self.output / '.rimworld-translator.json').is_file())

    def test_foreign_output_conflict_preserves_bytes_and_retries_without_losing_edits(self):
        self.edit_keyed('障害後の再試行')
        self.output.mkdir()
        foreign = self.output / 'user-note.bin'
        foreign.write_bytes(b'user data')
        errors = []
        with patch.object(self.window, 'error', side_effect=lambda error: errors.append(str(error))):
            self.click_trial()
            self.assertTrue(errors)
            self.assertFalse(self.window.dirty)
            self.assertEqual(self.bytes_tree(self.output), {'user-note.bin': b'user data'})
            self.assertIn('保存済み', self.window.guidance.text())
            self.assertIn('再試行', self.window.guidance.text())
            self.assertEqual(Project.load(self.saved).get_translation('Keyed:Keyed:Greeting'), '障害後の再試行')
            foreign.rename(self.saved.parent / 'preserved-user-note.bin')
            self.click_trial()
        self.assertEqual((self.saved.parent / 'preserved-user-note.bin').read_bytes(), b'user data')
        self.assertIn('障害後の再試行', (self.output / '1.5/Languages/Japanese/Keyed/Keyed.xml').read_text())
        self.assertEqual(self.bytes_tree(self.formal), self.formal_before)
        self.assertEqual(self.bytes_tree(self.source), self.original)

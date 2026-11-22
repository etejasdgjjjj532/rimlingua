"""Incremental GUI imports retain old work and require deliberate selection."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QListWidget
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window
from rimworld_translator.multiversion import scan_declared_versions


class IncrementalVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.about = self.source / 'About/About.xml'
        self.about.parent.mkdir(parents=True)
        self.declare(['1.6', '1.7'])
        keyed = self.source / 'Languages/English/Keyed/a.xml'
        keyed.parent.mkdir(parents=True)
        keyed.write_text('<LanguageData><Greeting>Hello</Greeting></LanguageData>')
        project = Project.create(self.source, scan_mod(self.source, game_version='1.6'))
        project.set_translation('Keyed:Keyed:Greeting', '保持する訳')
        project.mark_reviewed('Keyed:Keyed:Greeting', approved=True)
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def declare(self, versions):
        self.about.write_text('<ModMetaData><packageId>test.incremental</packageId>'
                              '<supportedVersions>' + ''.join(f'<li>{v}</li>' for v in versions)
                              + '</supportedVersions></ModMetaData>')

    def result(self, versions=('1.6', '1.7', '1.8')):
        self.declare(versions)
        return scan_declared_versions(self.source)

    def assert_old_work(self):
        restored = Project.load(self.saved)
        self.assertEqual(restored.game_version, '1.6')
        self.assertEqual(restored.get_translation('Keyed:Keyed:Greeting'), '保持する訳')
        self.assertTrue(restored.entry_index()['Keyed:Keyed:Greeting'].approved)
        return restored

    def test_explicit_new_version_import_preserves_existing_approval(self):
        result = self.result()
        self.window.declared_scan_finished(result, '', selected_versions=['1.8'])
        self.assertEqual(self.errors, [])
        restored = self.assert_old_work()
        self.assertEqual(restored.versions, ['1.6', '1.7', '1.8'])
        self.assertEqual(set(restored.version_profiles), {'1.6', '1.8'})
        restored.switch_version('1.8')
        self.assertEqual(restored.get_translation('Keyed:Keyed:Greeting'), '')
        self.assertFalse(restored.entry_index()['Keyed:Keyed:Greeting'].approved)

    def test_failed_existing_version_does_not_discard_selected_success(self):
        result = self.result(('1.6', '1.7'))
        result.scans.pop('1.6')
        result.failures['1.6'] = 'unavailable old input'
        self.window.declared_scan_finished(result, '', selected_versions=['1.7'])
        self.assertEqual(self.errors, [])
        self.assertEqual(set(self.assert_old_work().version_profiles), {'1.6', '1.7'})

    def test_success_can_be_added_while_new_declaration_remains_unscanned(self):
        result = self.result()
        result.scans.pop('1.8')
        result.failures['1.8'] = 'missing version data'
        self.window.declared_scan_finished(result, '', selected_versions=['1.7'])
        self.assertEqual(self.errors, [])
        restored = self.assert_old_work()
        self.assertEqual(restored.versions, ['1.6', '1.7', '1.8'])
        self.assertNotIn('1.8', restored.version_profiles)

    def test_cancelled_selection_preserves_unsaved_work_and_disk(self):
        result = self.result()
        self.window.japanese.setPlainText('未保存の訳')
        before = copy.deepcopy(self.window.project)
        disk = self.saved.read_bytes()
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
        self.window.declared_scan_finished(result, '', review=True)
        self.assertEqual(self.window.project, before)
        self.assertEqual(self.saved.read_bytes(), disk)
        self.assertTrue(self.window.dirty)
        self.assertTrue(self.window.autosave.isActive())

    def test_real_dialog_imports_only_checked_successful_version(self):
        result = self.result()
        observed = []
        def select():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, QDialog)
            choices = dialog.findChild(QListWidget, 'declaredVersionChoices')
            self.assertIsNotNone(choices)
            observed.extend(choices.item(i).data(Qt.UserRole) for i in range(choices.count()))
            for i in range(choices.count()):
                item = choices.item(i)
                item.setCheckState(Qt.Checked if item.data(Qt.UserRole) == '1.8' else Qt.Unchecked)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        QTimer.singleShot(0, select)
        self.window.declared_scan_finished(result, '', review=True)
        self.assertEqual(observed, ['1.7', '1.8'])
        self.assertEqual(self.errors, [])
        self.assertEqual(set(self.assert_old_work().version_profiles), {'1.6', '1.8'})

    def test_invalid_selection_and_removed_declaration_preserve_data(self):
        for versions, selected in [(('1.6',), ['1.6']), (('1.6', '1.7'), ['1.8'])]:
            with self.subTest(versions=versions):
                before = copy.deepcopy(self.window.project)
                disk = self.saved.read_bytes()
                self.window.declared_scan_finished(self.result(versions), '', selected_versions=selected)
                self.assertTrue(self.errors)
                self.assertEqual(self.window.project, before)
                self.assertEqual(self.saved.read_bytes(), disk)

    def test_mismatched_source_result_is_rejected_before_any_addition(self):
        result = self.result()
        result.scans['1.8'].package_id = 'other.mod'
        before = copy.deepcopy(self.window.project)
        self.window.declared_scan_finished(result, '', selected_versions=['1.7'])
        self.assertTrue(self.errors)
        self.assertEqual(self.window.project, before)

    def test_version_profile_save_does_not_report_fixable_export_error(self):
        project = Project.create_versions(self.source, scan_declared_versions(self.source).scans)
        project.save(self.saved)
        self.window.load_project(self.saved)
        self.window.japanese.setPlainText('保存した訳')
        self.assertTrue(self.window.save())
        self.assertEqual(self.window.last_export_error, '')
        self.assertFalse(self.window.dirty)
        self.assertIn('試験出力', self.window.guidance.text())
        self.assertFalse((self.saved.parent / 'mod').exists())
        self.assertEqual(Project.load(self.saved).get_translation('Keyed:Keyed:Greeting'), '保存した訳')

    def test_fully_scanned_project_can_check_for_future_declarations(self):
        Project.create_versions(self.source, scan_declared_versions(self.source).scans).save(self.saved)
        self.window.load_project(self.saved)
        self.assertTrue(self.window.scan_declared_button.isEnabled())

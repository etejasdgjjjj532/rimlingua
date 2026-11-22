"""Preferences tabs, folder settings in the workflow, autosave, protection and the Qt dialog language."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog, QInputDialog
from rimworld_translator import core
from rimworld_translator.core import Entry, Project, Scan, export_mod
from rimworld_translator.dialogs import PreferencesDialog
from rimworld_translator.gui import Window
from rimworld_translator.i18n import install_qt_translator
from rimworld_translator.platforms import clear_app_cache, mod_roots


def make_mod(folder, package='a.b'):
    (Path(folder) / 'About').mkdir(parents=True)
    (Path(folder) / 'About/About.xml').write_text(f'<ModMetaData><packageId>{package}</packageId><name>{package}</name></ModMetaData>')
    return Path(folder)


class PreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = make_mod(self.root / 'source')
        scan = Scan([Entry('Keyed:Keyed:A', 'Keyed', 'Keyed', 'A', 'a', 'Keyed/A.xml')], [], 'Src', 'a.b', ['1.6'])
        self.project = Project.create(self.source, scan)
        self.path = self.root / 'work/project.json'
        self.project.save(self.path)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.settings.data['ui_language'] = 'en'
        self.window.ui_language = 'en'
        self.errors = []
        self.window.error = self.errors.append
        self.addCleanup(self.close)

    def close(self):
        core.set_protected_folders(())
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    # tabs and fields
    def test_dialog_has_the_four_tabs(self):
        dialog = PreferencesDialog(self.window)
        titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        self.assertEqual(titles, ['General', 'Folders', 'Extraction', 'Output'])

    def test_folder_fields_start_empty_with_the_detected_folder_as_placeholder(self):
        workshop = self.root / 'detected-workshop'
        workshop.mkdir()
        with patch('rimworld_translator.dialogs.detected_workshop', return_value=[workshop]):
            dialog = PreferencesDialog(self.window)
        self.assertEqual(dialog.workshop_edit.text(), '')
        self.assertEqual(dialog.workshop_edit.placeholderText(), str(workshop))
        self.assertTrue(dialog.cache_edit.placeholderText())

    def test_collect_returns_the_edited_values(self):
        dialog = PreferencesDialog(self.window)
        dialog.workshop_edit.setText(' /w ')
        dialog.mods_edit.setText('/m')
        dialog.external_edit.setPlainText('/e1\n\n /e2 ')
        dialog.mods_config_edit.setText('/c.xml')
        dialog.translator_edit.setText('Name')
        dialog.license_edit.setText('CC0')
        dialog.autosave_spin.setValue(120)
        dialog.cache_edit.setText('/cache')
        data = dialog.collect()
        self.assertEqual(data['workshop_folder'], '/w')
        self.assertEqual(data['external_mod_folders'], ['/e1', '/e2'])
        self.assertEqual((data['default_translator'], data['default_license']), ('Name', 'CC0'))
        self.assertEqual((data['autosave_seconds'], data['cache_directory'], data['mods_config_path']), (120, '/cache', '/c.xml'))

    def test_autosave_off_and_short_values(self):
        dialog = PreferencesDialog(self.window)
        dialog.autosave_spin.setValue(0)
        self.assertEqual(dialog.collect()['autosave_seconds'], 0)
        dialog.autosave_spin.setValue(3)
        self.assertEqual(dialog.collect()['autosave_seconds'], 10)

    def test_applying_changes_the_autosave_timer_and_protection(self):
        ext = self.root / 'ext'
        ext.mkdir()
        self.window.apply_preferences({'autosave_seconds': 20, 'external_mod_folders': [str(ext)]})
        self.assertEqual(self.window.autosave.interval(), 20000)
        with self.assertRaises(ValueError):
            core.writable_destination(ext / 'new', self.source)
        self.window.apply_preferences({'autosave_seconds': 0})
        self.window.autosave.stop()
        self.window.start_autosave()
        self.assertFalse(self.window.autosave.isActive())

    def test_import_and_export_buttons_move_settings(self):
        self.window.settings.data['default_translator'] = 'Me'
        target = self.root / 'exported.json'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
            self.window.export_settings_file()
        self.assertTrue(target.is_file())
        self.window.settings.data['default_translator'] = ''
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(target), '')):
            self.window.import_settings_file()
        self.assertEqual(self.window.settings.data['default_translator'], 'Me')

    # translator name
    def test_empty_translator_does_not_invent_an_author(self):
        project = Project.load(self.path)
        export_mod(project, self.root / 'out')
        about = ET.parse(self.root / 'out/About/About.xml').getroot()
        self.assertIsNone(about.find('author'))
        project.metadata['author'] = 'Real Name'
        export_mod(project, self.root / 'out2')
        self.assertEqual(ET.parse(self.root / 'out2/About/About.xml').getroot().findtext('author'), 'Real Name')

    def test_default_translator_and_license_are_taken_by_new_projects(self):
        self.window.settings.data.update(default_translator='Me', default_license='CC0')
        self.window.project = Project.create(self.source, Scan([], [], 'Src', 'a.b', ['1.6']))
        self.window.apply_project_defaults(self.window.project)
        self.assertEqual(self.window.project.metadata['author'], 'Me')
        self.assertEqual(self.window.project.metadata['license'], 'CC0')

    # folders in the workflow
    def test_user_folders_are_source_choices(self):
        library = self.root / 'lib'
        library.mkdir()
        self.window.settings.data['external_mod_folders'] = [str(library)]
        self.assertIn(library, self.window.user_mod_roots().external)

    def test_non_mod_folder_is_refused_with_a_message(self):
        empty = self.root / 'photos'
        empty.mkdir()
        self.assertFalse(self.window.accept_source_folder(empty))
        self.assertIn('MOD', str(self.errors[-1]))
        self.assertTrue(self.window.accept_source_folder(self.source))

    def test_folder_of_mods_gets_a_hint(self):
        library = self.root / 'lib'
        make_mod(library / 'one', 'x.one')
        self.assertFalse(self.window.accept_source_folder(library))
        self.assertIn('one', str(self.errors[-1]))

    def test_new_project_stops_before_scanning_a_non_mod(self):
        empty = self.root / 'photos'
        empty.mkdir()
        scanned = []
        self.window.start_scan = lambda *a, **k: scanned.append(a)
        with patch.object(QInputDialog, 'getItem', return_value=('PC', True)), \
                patch.object(QFileDialog, 'getExistingDirectory', return_value=str(empty)):
            self.window.new_project()
        self.assertEqual(scanned, [])
        self.assertTrue(self.errors)

    def test_workspace_inside_a_user_folder_is_refused(self):
        ext = self.root / 'ext'
        ext.mkdir()
        self.window.apply_preferences({'external_mod_folders': [str(ext)]})
        with self.assertRaises(ValueError):
            core.writable_destination(ext / 'project', self.source)
        core.writable_destination(self.root / 'elsewhere', self.source)

    # per-project output folder
    def test_output_folder_can_be_set_and_reset_from_the_ui(self):
        self.window.load_project(self.path)
        chosen = self.root / 'exports/Mine'
        self.assertTrue(self.window.set_output_folder(str(chosen)))
        self.assertEqual(Project.load(self.path).output_folder, str(chosen))
        self.assertIn(str(chosen), self.window.location.text())
        self.assertTrue(self.window.set_output_folder(''))
        self.assertEqual(Project.load(self.path).output_folder, '')

    def test_overlapping_output_folder_is_refused(self):
        self.window.load_project(self.path)
        self.assertFalse(self.window.set_output_folder(str(self.source / 'mine')))
        self.assertEqual(Project.load(self.path).output_folder, '')
        self.assertTrue(self.errors)

    # problem report
    def test_diagnostic_text_carries_a_masked_settings_summary(self):
        self.window.settings.data.update(workshop_folder='/secret/home/workshop', default_translator='Private Name')
        report = self.window.diagnostic_text()
        self.assertIn('workshop_folder: set', report)
        self.assertNotIn('/secret', report)
        self.assertNotIn('Private Name', report)

    # Qt's own strings
    def test_qt_standard_buttons_follow_the_ui_language(self):
        install_qt_translator(self.app, 'ja')
        try:
            box = QDialogButtonBox(QDialogButtonBox.Cancel)
            self.assertTrue(box.button(QDialogButtonBox.Cancel).text().startswith('キャンセル'))
        finally:
            install_qt_translator(self.app, 'en')
        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.assertEqual(box.button(QDialogButtonBox.Cancel).text().replace('&', ''), 'Cancel')

    # cache
    def test_clear_cache_removes_only_what_the_editor_made(self):
        cache = self.root / 'cache'
        (cache / 'game-table').mkdir(parents=True)
        (cache / 'game-table/x.json').write_text('{}')
        from rimworld_translator.platforms import mark_cache_folder
        mark_cache_folder(cache / 'game-table')
        (cache / 'precious.txt').write_text('keep')
        removed = clear_app_cache(cache)
        self.assertEqual(removed, 1)
        self.assertFalse((cache / 'game-table').exists())
        self.assertTrue((cache / 'precious.txt').exists())


if __name__ == '__main__':
    unittest.main()

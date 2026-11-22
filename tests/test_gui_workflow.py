"""End-user workflows connected to the real Qt editor."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window
from rimworld_translator.workflow import preview_import, preview_replace


class GuiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        (self.source/'Defs').mkdir(parents=True)
        (self.source/'Defs/a.xml').write_text('<Defs><ThingDef><defName>Gun</defName><label>gun</label><description>A gun</description></ThingDef></Defs>')
        self.path = self.root/'work/project.json'
        p = Project.create(self.source,scan_mod(self.source),['Japanese','French'])
        p.save(self.path)
        self.settings_path = self.root/'ui-settings.json'
        self.old_settings = os.environ.get('RW_TRANSLATOR_SETTINGS')
        os.environ['RW_TRANSLATOR_SETTINGS'] = str(self.settings_path)
        self.addCleanup(self.restore_env)
        self.window = Window()
        self.window.error = lambda text:self.fail(str(text))
        self.window.load_project(self.path)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.close_window)

    def restore_env(self):
        if self.old_settings is None:
            os.environ.pop('RW_TRANSLATOR_SETTINGS',None)
        else:
            os.environ['RW_TRANSLATOR_SETTINGS'] = self.old_settings

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_save_updates_installable_output_without_an_extra_export_click(self):
        self.window.model.setData(self.window.model.index(0,3),'保存と同時に出力')
        self.window.save_button.click()
        file = self.path.parent/'mod/Languages/Japanese/DefInjected/ThingDef/Translations.xml'
        self.assertTrue(file.is_file(),'Save must update game XML automatically')
        self.assertEqual(ET.parse(file).getroot().findtext('Gun.label'),'保存と同時に出力')

    def test_small_window_stacks_editors_and_large_window_restores_columns(self):
        from PySide6.QtWidgets import QBoxLayout
        self.window.resize(480,350)
        self.app.processEvents()
        self.assertTrue(hasattr(self.window,'editor_pair_layout'))
        self.assertEqual(self.window.editor_pair_layout.direction(),QBoxLayout.TopToBottom)
        for widget in (self.window.english,self.window.japanese):
            self.window.editor_scroll.ensureWidgetVisible(widget)
            self.app.processEvents()
            center = widget.mapTo(self.window.editor_scroll.viewport(),widget.rect().center())
            self.assertTrue(self.window.editor_scroll.viewport().rect().contains(center))
        self.window.resize(1240,730)
        self.app.processEvents()
        self.assertEqual(self.window.editor_pair_layout.direction(),QBoxLayout.LeftToRight)

    def test_import_preview_batch_undo_and_redo(self):
        self.assertTrue(hasattr(self.window,'apply_preview'),'Import preview action is not connected to the GUI')
        incoming = self.root/'incoming.xml'
        incoming.write_text('<LanguageData><Gun.label>銃</Gun.label></LanguageData>')
        preview = preview_import(self.window.project,incoming)
        self.window.apply_preview(preview)
        self.assertEqual(self.window.project.entries[0].japanese,'銃')
        self.window.undo_batch()
        self.assertEqual(self.window.project.entries[0].japanese,'')
        self.window.redo_batch()
        self.assertEqual(self.window.project.entries[0].japanese,'銃')
        self.window.apply_preview(preview_replace(self.window.project,'銃','鉄砲'))
        self.assertEqual(self.window.japanese.toPlainText(),'鉄砲')

    def test_diff_file_import_uses_read_only_base_for_overwrite_preview_and_undo(self):
        import difflib
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        base = self.root/'translated-mod'
        relative = 'Languages/Japanese/DefInjected/ThingDef/Translations.xml'
        xml = base/relative
        xml.parent.mkdir(parents=True)
        before = '<LanguageData>\n<Gun.label>元の訳</Gun.label>\n</LanguageData>\n'
        after = before.replace('元の訳','差分の訳')
        xml.write_text(before)
        file = self.root/'translations.diff'
        file.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+relative,tofile='b/'+relative)))
        self.window.model.setData(self.window.model.index(0,3),'作業中の訳')
        def pick(*args,**kwargs):
            return args[3][0],True
        with patch('rimworld_translator.gui_tools.QInputDialog.getItem',side_effect=pick),patch('rimworld_translator.gui_tools.QFileDialog.getOpenFileName',return_value=(str(file),'')),patch('rimworld_translator.gui_tools.QFileDialog.getExistingDirectory',return_value=str(base)),patch.object(QMessageBox,'question',return_value=QMessageBox.Yes),patch.object(self.window,'confirm_preview',return_value=True):
            self.window.import_translations()
        self.assertEqual(self.window.project.entries[0].japanese,'差分の訳')
        self.assertEqual(xml.read_text(),before)
        self.window.undo_batch()
        self.assertEqual(self.window.project.entries[0].japanese,'作業中の訳')

    def test_filters_review_and_exclusion_are_per_language(self):
        self.assertTrue(hasattr(self.window,'exclude_current'),'False-positive exclusion action is missing')
        self.window.model.setData(self.window.model.index(0,3),'銃')
        self.window.mark_reviewed()
        self.assertTrue(self.window.project.entries[0].reviewed)
        self.window.status_filter.setCurrentIndex(self.window.status_filter.findData('reviewed'))
        self.assertEqual(self.window.proxy.rowCount(),1)
        self.window.language_selector.setCurrentIndex(1)
        self.assertEqual(self.window.proxy.rowCount(),0)
        self.window.status_filter.setCurrentIndex(0)
        self.window.table.setCurrentIndex(self.window.proxy.index(0,0))
        self.window.exclude_current()
        self.assertTrue(self.window.project.entries[0].excluded)
        self.window.source_filter.setText('missing.xml')
        self.assertEqual(self.window.proxy.rowCount(),0)

    def test_diagnostic_navigation_clears_filters_and_selects_offending_key(self):
        self.assertTrue(hasattr(self.window,'navigate_entry'),'Diagnostics cannot navigate to an entry')
        self.window.search.setText('no-match')
        identity = self.window.project.entries[1].id
        self.window.navigate_entry(identity)
        self.assertEqual(self.window.current.id,identity)
        self.assertTrue(self.window.table.currentIndex().isValid())

    def test_english_controls_font_preferences_and_tutorial_skip_persist(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.assertTrue(hasattr(self.window,'set_gui_language'),'English menu localization is missing')
        self.window.set_gui_language('en')
        self.assertEqual(self.window.export_button.text(),'Export translation mod')
        self.window.set_editor_font(14)
        self.assertEqual(self.window.settings.data['font_size'],14)
        self.window.skip_tutorial()
        self.assertTrue(self.window.settings.data['tutorial_dismissed'])
        self.assertTrue(self.settings_path.is_file())
        for language in ('ja','en','ja','en'):
            self.window.set_gui_language(language)
        self.window.model.setData(self.window.model.index(0,3),'英語メニューで保存')
        QTest.keyClick(self.window,Qt.Key_S,Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(Project.load(self.path).entries[0].japanese,'英語メニューで保存')

    def test_scan_cancel_retains_existing_project_and_controls(self):
        self.assertTrue(hasattr(self.window,'cancel_scan'),'Background scan cancellation is missing')
        original = self.window.project
        self.window.start_scan(self.source)
        self.window.cancel_scan()
        deadline = time.monotonic()+10
        while self.window.busy and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertFalse(self.window.busy)
        self.assertIs(self.window.project,original)
        self.assertTrue(self.window.export_button.isEnabled())

    def test_new_project_cannot_replay_a_previous_project_batch(self):
        incoming = self.root/'incoming.xml'
        incoming.write_text('<LanguageData><Gun.label>銃</Gun.label></LanguageData>')
        self.window.apply_preview(preview_import(self.window.project,incoming))
        self.window.undo_batch()
        self.assertTrue(self.window.redo_batches)
        self.window.scan_finished(self.source,self.root/'another/project.json',scan_mod(self.source),'')
        self.assertFalse(self.window.undo_batches)
        self.assertFalse(self.window.redo_batches)
        self.window.redo_batch()
        self.assertEqual(self.window.project.entries[0].japanese,'')

    def test_created_project_is_saved_in_recent_projects_without_reopening(self):
        from PySide6.QtWidgets import QMenu
        new_path = self.root/'created/project.json'
        self.window.scan_finished(self.source,new_path,scan_mod(self.source),'')
        from rimworld_translator.settings import SettingsStore
        self.assertEqual(SettingsStore(self.settings_path).data['recent_projects'][0],str(new_path.resolve()))
        menus = [menu for menu in self.window.menuBar().findChildren(QMenu) if menu.title()=='最近のプロジェクト']
        self.assertTrue(any(action.toolTip()==str(new_path) for menu in menus for action in menu.actions()))

    def test_busy_scan_disables_language_changes_and_restores_selection(self):
        self.window.settings.data['inspect_metadata'] = False
        self.window.start_scan(self.source)
        self.assertFalse(self.window.language_selector.isEnabled())
        self.window.cancel_scan()
        deadline = time.monotonic()+10
        while self.window.busy and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertFalse(self.window.busy)
        self.assertTrue(self.window.language_selector.isEnabled())
        self.assertEqual(self.window.language_selector.currentData(),self.window.project.language)

    def test_completed_review_and_exclusion_refresh_state_filters(self):
        self.window.project.entries[0].review = True
        self.window.status_filter.setCurrentIndex(self.window.status_filter.findData('needs-review'))
        self.assertEqual(self.window.proxy.rowCount(),1)
        self.window.table.setCurrentIndex(self.window.proxy.index(0,0))
        self.window.model.setData(self.window.model.index(0,3),'銃')
        self.window.mark_reviewed()
        self.assertEqual(self.window.proxy.rowCount(),0)
        self.window.status_filter.setCurrentIndex(0)
        self.window.table.setCurrentIndex(self.window.proxy.index(0,0))
        self.window.exclude_current()
        self.window.status_filter.setCurrentIndex(self.window.status_filter.findData('excluded'))
        self.assertEqual(self.window.proxy.rowCount(),1)
        self.window.table.setCurrentIndex(self.window.proxy.index(0,0))
        self.window.exclude_current()
        self.assertEqual(self.window.proxy.rowCount(),0)

    def test_next_untranslated_refreshes_without_interrupting_typing(self):
        self.window.next_untranslated.click()
        self.assertEqual(self.window.proxy.rowCount(),2)
        self.window.japanese.setPlainText('銃')
        self.app.processEvents()
        self.assertEqual(self.window.proxy.rowCount(),2,'The editing row should stay until a completed action')
        self.window.next_untranslated.click()
        self.assertEqual(self.window.proxy.rowCount(),1)
        self.assertEqual(self.window.current.key,'Gun.description')

    def test_gui_scan_context_controls_conditional_folders_and_survives_reopen(self):
        self.assertTrue(hasattr(self.window,'extraction_context_dialog'))
        from unittest.mock import patch
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QComboBox, QDialog, QCheckBox, QListWidget
        (self.source/'LoadFolders.xml').write_text('<loadFolders><v1.5><li>/</li></v1.5><v1.6><li>/</li><li IfModActive="sample.extra">Extra</li></v1.6></loadFolders>')
        extra = self.source/'Extra/Defs/a.xml'
        extra.parent.mkdir(parents=True)
        extra.write_text('<Defs><ThingDef><defName>Extra</defName><label>extra</label></ThingDef></Defs>')
        self.window.project.active_mods = ['sample.extra']
        self.window.settings.data['inspect_metadata'] = False
        def choose(dialog):
            version = dialog.findChild(QComboBox,'scanVersion')
            version.setCurrentText('1.6')
            dialog.findChild(QCheckBox,'unknownActiveMods').setChecked(False)
            listing = dialog.findChild(QListWidget,'activeModList')
            item = next(listing.item(i) for i in range(listing.count()) if listing.item(i).data(Qt.UserRole)=='sample.extra')
            item.setCheckState(Qt.Checked)
            return QDialog.Accepted
        with patch.object(QDialog,'exec',new=choose):
            self.window.extraction_context_dialog()
        deadline = time.monotonic()+10
        while self.window.busy and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertFalse(self.window.busy)
        self.assertIn('Extra.label',[e.key for e in self.window.project.entries])
        restored = Project.load(self.path)
        self.assertEqual(restored.game_version,'1.6')
        self.assertIn('sample.extra',restored.active_mods)
        self.assertTrue(restored.active_mods_known)

    def test_cancelled_context_scan_keeps_previous_extraction_settings(self):
        self.window.settings.data['inspect_metadata'] = False
        original = self.window.project
        self.window.start_scan(self.source,context={'game_version':'1.5','active_mods':[]})
        self.window.cancel_scan()
        deadline = time.monotonic()+10
        while self.window.busy and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertIs(self.window.project,original)
        self.assertEqual(self.window.project.game_version,'1.6')

    def test_malformed_optional_game_profile_does_not_prevent_context_dialog(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QCheckBox,QDialog
        profile = self.root/'profile'
        (profile/'Config').mkdir(parents=True)
        file = profile/'Config/ModsConfig.xml'
        called = []
        def choose(dialog):
            called.append(True)
            self.assertTrue(dialog.findChild(QCheckBox,'unknownActiveMods').isChecked())
            return QDialog.Accepted
        self.window.project = None
        for contents in ('<ModsConfigData><broken>','<ModsConfigData><activeMods><li>invalid/id</li></activeMods></ModsConfigData>'):
            with self.subTest(contents=contents):
                file.write_text(contents)
                with patch('rimworld_translator.scan_context.user_data_directory',return_value=profile),patch.object(QDialog,'exec',new=choose):
                    context = self.window.choose_scan_context(self.source)
                self.assertIsNone(context['active_mods'])
                self.assertEqual(file.read_text(),contents)
        self.assertTrue(called)
        self.assertIsNone(context['active_mods'])

    def test_compact_window_fits_a_small_logical_hidpi_screen(self):
        self.window.resize(660,350)
        self.app.processEvents()
        self.assertLessEqual(self.window.width(),660)
        self.assertLessEqual(self.window.height(),350)
        self.assertTrue(hasattr(self.window,'editor_scroll'),'Compact content must remain reachable by scrolling')
        self.window.editor_scroll.ensureWidgetVisible(self.window.japanese)
        self.app.processEvents()
        self.assertTrue(self.window.japanese.isVisible())


if __name__=='__main__':
    unittest.main()

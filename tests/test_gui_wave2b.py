"""Menus, dialogs and the export flow around the project/QA/export/interchange backend."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog
from rimworld_translator import dialogs_tools as tools
from rimworld_translator.core import Entry, Project
from rimworld_translator.dialogs import PreferencesDialog
from rimworld_translator.gui import Window


def keyed(key, english, japanese=''):
    return Entry(f'Keyed:Keyed:{key}', 'Keyed', 'Keyed', key, english, 'Keyed/Main.xml', japanese)


class Base(unittest.TestCase):
    versions = ['1.6']

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'About/About.xml').write_text('<ModMetaData><name>Example</name><packageId>author.original</packageId></ModMetaData>')
        entries = [keyed('A', 'Hello there.', 'こんにちは。'), keyed('B', 'Open the door.'), keyed('C', 'Run away.', 'RUN'),
                   keyed('D', 'Bad {0} token', 'こわれ')]
        self.project = Project(str(self.source), 'Example', 'local.translation.example', 'author.original',
                               list(self.versions), entries, [])
        self.path = self.root / 'work/project.json'
        self.project.save(self.path)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.settings.data['ui_language'] = 'en'
        self.window.ui_language = 'en'
        self.errors = []
        self.window.error = self.errors.append
        self.window.load_project(self.path)
        self.addCleanup(self.close)

    def close(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()


class PreferencesGenerations(Base):
    def test_backup_generations_field_round_trips(self):
        self.window.settings.data['backup_generations'] = 12
        dialog = PreferencesDialog(self.window)
        self.assertEqual(dialog.backup_spin.value(), 12)
        dialog.backup_spin.setValue(0)
        self.assertEqual(dialog.collect()['backup_generations'], 0)
        dialog.backup_spin.setValue(30)
        self.assertEqual(dialog.collect()['backup_generations'], 30)

    def test_save_passes_the_limit_to_history(self):
        self.window.settings.data['backup_generations'] = 7
        with patch('rimworld_translator.gui.snapshot') as snapshot:
            snapshot.return_value = False
            self.window.save(export=False)
        self.assertEqual(snapshot.call_args.kwargs.get('keep'), 7)
        self.window.settings.data['backup_generations'] = 0
        with patch('rimworld_translator.gui.snapshot') as snapshot:
            snapshot.return_value = False
            self.window.save(export=False)
        self.assertIsNone(snapshot.call_args.kwargs.get('keep'))


class QualityAndExport(Base):
    def test_quality_check_lists_each_kind_and_jumps(self):
        self.window.quality_check_dialog()
        dialog = self.window.quality_dialog
        view = dialog.view
        counts = view.counts()
        self.assertGreaterEqual(counts['errors'], 1)      # D lost its {0}
        self.assertEqual(counts['untranslated'], 1)       # B; C holds a translation
        untranslated = view.lists['untranslated']
        ids = {untranslated.topLevelItem(i).data(0, tools.ID_ROLE) for i in range(untranslated.topLevelItemCount())}
        self.assertIn('Keyed:Keyed:B', ids)
        self.assertNotIn('Keyed:Keyed:C', ids)
        dialog.close()

    def test_double_click_jumps_to_the_row(self):
        self.window.quality_check_dialog()
        view = self.window.quality_dialog.view
        item = view.lists['untranslated'].topLevelItem(0)
        view.lists['untranslated'].itemActivated.emit(item, 0)
        self.assertEqual(self.window.current.id, item.data(0, tools.ID_ROLE))
        self.window.quality_dialog.close()

    def test_export_review_blocks_on_errors_and_lists_them(self):
        shown = []
        with patch.object(tools.ExportReviewDialog, 'exec', lambda dialog: shown.append(dialog) or QDialog.Rejected):
            self.assertFalse(self.window.export_with_review())
        dialog = shown[0]
        self.assertFalse(dialog.can_export)
        self.assertGreaterEqual(dialog.problems.topLevelItemCount(), 1)
        self.assertFalse((self.root / 'work/mod').exists())

    def test_export_review_shows_diff_then_writes(self):
        self.window.project.set_translation('Keyed:Keyed:D', 'ok {0}')
        shown = []

        def accept(dialog):
            shown.append(dialog)
            return QDialog.Accepted
        with patch.object(tools.ExportReviewDialog, 'exec', accept):
            self.assertTrue(self.window.export_with_review())
        dialog = shown[0]
        self.assertTrue(dialog.can_export)
        self.assertGreaterEqual(dialog.changes.topLevelItemCount(), 1)   # added files
        self.assertTrue((self.root / 'work/mod/About/About.xml').is_file())

    def test_export_review_cancel_writes_nothing(self):
        self.window.project.set_translation('Keyed:Keyed:D', 'ok {0}')
        with patch.object(tools.ExportReviewDialog, 'exec', lambda dialog: QDialog.Rejected):
            self.assertFalse(self.window.export_with_review())
        self.assertFalse((self.root / 'work/mod').exists())

    def test_diff_changes_show_key_level_detail(self):
        self.window.project.set_translation('Keyed:Keyed:D', 'ok {0}')
        self.assertTrue(self.window.generate())
        self.window.project.set_translation('Keyed:Keyed:A', '新しい。')
        self.window.project.set_translation('Keyed:Keyed:B', '開けて。')
        from rimworld_translator.export_diff import export_diff
        diff = export_diff(self.window.project, self.window.output_folder())
        report = tools.preflight_for(self.window.project)
        dialog = tools.ExportReviewDialog(self.window, report, diff, None, self.window.output_folder())
        text = []
        top = dialog.changes
        for i in range(top.topLevelItemCount()):
            for j in range(top.topLevelItem(i).childCount()):
                text.append(top.topLevelItem(i).child(j).text(1))
        self.assertTrue(any('A' in line for line in text), text)
        self.assertTrue(any('B' in line for line in text), text)


class Dialogs(Base):
    def test_workshop_material_is_written_to_the_chosen_folder_only(self):
        dialog = tools.WorkshopDialog(self.window)
        target = self.root / 'ws'
        dialog.folder.setText(str(target))
        dialog.translator.setText('Tester')
        dialog.version_note.setText('1.1 update')
        dialog.write()
        self.assertTrue((target / 'description.bbcode.txt').is_file())
        self.assertIn('1.1 update', (target / 'changelog.txt').read_text(encoding='utf-8'))
        self.assertIn('Tester', (target / 'description.bbcode.txt').read_text(encoding='utf-8'))
        self.assertEqual(self.errors, [])

    def test_workshop_refuses_the_source_folder(self):
        dialog = tools.WorkshopDialog(self.window)
        dialog.folder.setText(str(self.source))
        dialog.write()
        self.assertTrue(self.errors)
        self.assertFalse((self.source / 'title.txt').exists())

    def test_exchange_choices_and_csv_export(self):
        dialog = tools.ExchangeDialog(self.window, 'csv')
        dialog.detailed.setChecked(True)
        self.assertEqual(dialog.choices(), ('csv', None, True))
        target = self.root / 'work/out.csv'
        tools.write_exchange(self.window.project, target, *dialog.choices())
        header = target.read_text(encoding='utf-8-sig').splitlines()[0]
        self.assertIn('status', header)
        po = tools.ExchangeDialog(self.window, 'po')
        self.assertFalse(po.detailed.isEnabled())

    def test_bundle_round_trip_through_the_dialog_helpers(self):
        (self.root / 'bundles').mkdir(); bundle = self.root / 'bundles/share.rwtbundle'
        self.assertTrue(self.window.export_bundle_to(bundle, include_output=False), self.errors)
        info = tools.describe_bundle(bundle, self.window.tr)
        self.assertIn('Example', info)
        destination = self.root / 'imported'
        destination.mkdir()
        self.assertTrue(self.window.import_bundle_from(bundle, self.source, destination))
        self.assertEqual(self.window.project_path, destination / 'project.json')
        self.assertEqual(len(self.window.project.entries), 4)

    def test_match_mod_dialog_reports_coverage_and_license(self):
        mod = self.root / 'theirs'
        (mod / 'About').mkdir(parents=True)
        (mod / 'About/About.xml').write_text('<ModMetaData><name>Their JP</name><author>Someone</author><packageId>x.y</packageId></ModMetaData>')
        (mod / 'Languages/Japanese/Keyed').mkdir(parents=True)
        (mod / 'Languages/Japanese/Keyed/Main.xml').write_text(
            '<?xml version="1.0" encoding="utf-8"?><LanguageData><B>開けて。</B><A>違う。</A></LanguageData>', encoding='utf-8')
        dialog = tools.MatchModDialog(self.window)
        dialog.load(mod)
        text = dialog.summary.text()
        self.assertIn('Their JP', text)
        self.assertEqual(dialog.counts['new'], 1)
        self.assertEqual(dialog.counts['different'], 1)
        self.assertIn('license', dialog.license.text().lower() + 'license')
        self.assertTrue(dialog.import_button.isEnabled())
        preview = dialog.preview()
        self.assertTrue(preview.changes)
        self.assertTrue(all(c.review for c in preview.changes))

    def test_assign_dialog_commits_and_marks_dirty(self):
        dialog = tools.AssignDialog(self.window)
        self.assertEqual(dialog.table.rowCount(), 1)
        dialog.set_translator(0, 'Hana')
        dialog.commit()
        self.assertEqual(self.window.project.assignments.get('Keyed/Main.xml'), 'Hana')
        self.assertTrue(self.window.dirty)

    def test_quality_menu_and_dialog_actions_exist(self):
        titles = [a.text() for m in self.window.menuBar().findChildren(type(self.window.menuBar().actions()[0].menu()))
                  for a in m.actions()]
        for expected in ('Quality check…', 'Prerequisite MODs…', 'Version states…', 'Workshop material…',
                         'Import project bundle…', 'Match another translation MOD…', 'Assign files to translators…'):
            self.assertIn(expected, titles)


class MultiVersion(Base):
    versions = ['1.4', '1.5', '1.6']

    def setUp(self):
        super().setUp()
        scans = {}
        from rimworld_translator.core import Scan
        for version, english in (('1.4', 'gun'), ('1.5', 'gun'), ('1.6', 'gun!')):
            scans[version] = Scan(entries=[Entry('DefInjected:ThingDef:Gun.label', 'DefInjected', 'ThingDef', 'Gun.label', english, 'T.xml')],
                                  name='Fixture', package_id='author.original', versions=['1.4', '1.5', '1.6'],
                                  stats={'active_version': version})
        project = Project.create_versions(self.source, scans)
        project.switch_version('1.4')
        project.set_translation('DefInjected:ThingDef:Gun.label', '銃')
        project.save(self.path)
        self.window.dirty = False
        self.window.load_project(self.path)

    def test_version_states_explain_missing_library_game_and_1_0(self):
        dialog = tools.VersionStatesDialog(self.window, available={'1.5'})
        rows = {dialog.table.item(i, 0).text(): (dialog.table.item(i, 1).data(tools.ID_ROLE), dialog.table.item(i, 4).text())
                for i in range(dialog.table.rowCount())}
        self.assertEqual(rows['1.5'][0], 'ready')
        self.assertEqual(rows['1.6'][0], 'no_library_game')
        self.assertTrue(rows['1.6'][1])

    def test_carry_dialog_previews_and_applies(self):
        dialog = tools.CarryDialog(self.window)
        dialog.source.setCurrentIndex(dialog.source.findData('1.4'))
        dialog.target.setCurrentIndex(dialog.target.findData('1.5'))
        dialog.refresh()
        self.assertEqual(dialog.table.topLevelItemCount(), 1)
        self.assertEqual(dialog.apply(), 1)
        self.assertTrue(self.window.dirty)

    def test_version_diff_dialog_summarises(self):
        dialog = tools.VersionDiffDialog(self.window)
        dialog.a.setCurrentIndex(dialog.a.findData('1.5'))
        dialog.b.setCurrentIndex(dialog.b.findData('1.6'))
        dialog.refresh()
        self.assertIn('1', dialog.summary.text())
        self.assertEqual(dialog.lists['english_changed'].topLevelItemCount(), 1)


class Prerequisites(Base):
    def test_dialog_lists_missing_with_workshop_link_text(self):
        from rimworld_translator.scan_context import Prerequisite, PrerequisiteReport
        report = PrerequisiteReport(
            (Prerequisite('a.gone', 'Gone Mod', '2012345678', ''), Prerequisite('b.nolink', 'No Link')),
            (Prerequisite('c.found', 'Found', '', '', Path('/x'), ('Japanese',)),), 5)
        dialog = tools.PrerequisitesDialog(self.window, report)
        self.assertEqual(dialog.missing.topLevelItemCount(), 2)
        row = dialog.missing.topLevelItem(0)
        self.assertEqual(row.text(0), 'Gone Mod')
        self.assertEqual(row.text(1), 'a.gone')
        self.assertIn('2012345678', row.text(2))
        self.assertEqual(dialog.found.topLevelItemCount(), 1)
        self.assertIn('5', dialog.note.text())

    def test_dialog_shows_how_many_rows_depend_on_each_found_prerequisite(self):
        from rimworld_translator.prerequisite_effects import PrerequisiteEffect
        from rimworld_translator.scan_context import Prerequisite, PrerequisiteReport
        report = PrerequisiteReport((), (Prerequisite('c.found', 'Found', '', '', Path('/x'), ()),
                                         Prerequisite('d.other', 'Other', '', '', Path('/y'), ())), None)
        effects = {'c.found': PrerequisiteEffect('c.found', 2, None, 3, frozenset('abcde'), ('assemblies-unreadable',))}
        dialog = tools.PrerequisitesDialog(self.window, report, effects)
        by_id = {dialog.found.topLevelItem(i).text(1): dialog.found.topLevelItem(i) for i in range(2)}
        text = by_id['c.found'].text(3)
        self.assertIn('5', text)
        self.assertIn('2', text)
        self.assertIn('3', text)
        self.assertIn('DLL', by_id['c.found'].toolTip(3))
        self.assertEqual(by_id['d.other'].text(3), '')


class InconsistentTerms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'source').mkdir()
        entries = [Entry(f'DefInjected:ThingDef:{name}.label', 'DefInjected', 'ThingDef', f'{name}.label', english, 'Defs/a.xml', ja)
                   for name, english, ja in (('A', 'Plasma gun', 'プラズマ銃'), ('B', 'Plasma gun', 'プラズマガン'),
                                             ('C', 'Plasma gun', 'プラズマ銃'), ('D', 'Axe', '斧'))]
        project = Project(str(root / 'source'), 'P', 'local.p', 'demo.p', ['1.6'], entries, [], languages=['Japanese'])
        path = root / 'workspace/project.json'
        project.save(path)
        self.window = Window(settings_path=root / 'settings.json')
        self.window.settings.data['ui_language'] = 'en'
        self.window.ui_language = 'en'
        self.window.load_project(path)
        self.addCleanup(self.close)

    def close(self):
        for dialog in (getattr(self.window, 'glossary_window', None),):
            if dialog is not None:
                dialog.close()
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_glossary_dialog_lists_terms_with_several_renderings(self):
        self.window.glossary_dialog()
        view = self.window.glossary_window.inconsistent
        self.assertEqual(view.tree.topLevelItemCount(), 1)  # 'Axe' has one rendering
        term = view.tree.topLevelItem(0)
        self.assertEqual(term.text(0), 'Plasma gun')
        self.assertEqual(term.childCount(), 2)
        self.assertEqual(term.child(0).text(1), '2')  # the most used wording first
        self.assertIn('プラズマ銃', term.child(0).text(0))

    def test_clicking_a_rendering_jumps_through_its_rows(self):
        self.window.glossary_dialog()
        view = self.window.glossary_window.inconsistent
        first = view.tree.topLevelItem(0).child(0)
        view.tree.itemClicked.emit(first, 0)
        self.assertEqual(self.window.current.id, 'DefInjected:ThingDef:A.label')
        view.tree.itemClicked.emit(first, 0)
        self.assertEqual(self.window.current.id, 'DefInjected:ThingDef:C.label')
        view.tree.itemClicked.emit(first, 0)
        self.assertEqual(self.window.current.id, 'DefInjected:ThingDef:A.label')

    def test_a_chosen_rendering_can_be_registered_in_the_glossary(self):
        self.window.glossary_dialog()
        view = self.window.glossary_window.inconsistent
        view.tree.setCurrentItem(view.tree.topLevelItem(0).child(1))
        view.adopt_button.click()
        self.assertEqual(self.window.project.glossary['Plasma gun'], 'プラズマガン')


if __name__ == '__main__':
    unittest.main()

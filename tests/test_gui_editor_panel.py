"""The main translation screen: filters, progress, row editor helpers, suggestions, notes and keyboard flow."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from rimworld_translator.core import Entry, Project
from rimworld_translator.gui import Window
from rimworld_translator.translation_memory import TranslationMemory


def entry(kind, group, key, english, japanese='', file='Defs/A.xml', **extra):
    return Entry(f'{kind}:{group}:{key}', kind, group, key, english, file, japanese, **extra)


class PanelCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    entries = ()

    def build(self, entries, memory=None, glossary=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'source').mkdir()
        project = Project(str(root / 'source'), 'Panel', 'local.panel', 'demo.panel', ['1.6'], list(entries), [],
                          languages=['Japanese'])
        if glossary:
            project.glossary.update(glossary)
        path = root / 'workspace/project.json'
        project.save(path)
        if memory:
            tm = TranslationMemory(root / 'translation-memory.json')
            for english, japanese in memory:
                tm.add(english, 'Japanese', japanese, 'other.mod')
            tm.save()
        self.window = Window(settings_path=root / 'settings.json')
        self.window.load_project(path)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.close_window)
        return self.window

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def select(self, entry_id):
        window = self.window
        row = window.model.row_for_id[entry_id]
        window.table.setCurrentIndex(window.proxy.mapFromSource(window.model.index(row, 0)))
        self.app.processEvents()


class FilterTests(PanelCase):
    def setUp(self):
        self.window = self.build([
            entry('DefInjected', 'ThingDef', 'Gun.label', 'Gun', '銃', 'Defs/Guns.xml'),
            entry('DefInjected', 'ThingDef', 'Gun.description', 'A big gun.', '', 'Defs/Guns.xml'),
            entry('DefInjected', 'HediffDef', 'Scar.label', 'Scar', '', 'Defs/Health.xml'),
            entry('Keyed', 'Keyed', 'Hello', 'Hello {0}', '[0]こんにちは', 'Keyed/K.xml'),
        ])

    def test_def_type_file_and_flag_filters_narrow_the_table(self):
        window = self.window
        self.assertEqual(window.proxy.rowCount(), 4)
        window.def_type_filter.setCurrentIndex(window.def_type_filter.findData('ThingDef'))
        self.assertEqual(window.proxy.rowCount(), 2)
        window.def_type_filter.setCurrentIndex(0)
        window.file_filter.setCurrentIndex(window.file_filter.findData('Defs/Health.xml'))
        self.assertEqual(window.proxy.rowCount(), 1)
        window.clear_filters()
        self.assertEqual(window.proxy.rowCount(), 4)
        self.assertEqual(window.def_type_filter.currentIndex(), 0)
        self.assertEqual(window.file_filter.currentIndex(), 0)

    def test_flag_filter_and_qa_error_status(self):
        window = self.window
        self.select('DefInjected:HediffDef:Scar.label')
        window.flag_combo.setCurrentIndex(window.flag_combo.findData('later'))
        window.flag_filter.setCurrentIndex(window.flag_filter.findData('later'))
        self.assertEqual([e.key for e in (window.model.entries[i.row()] for i in
                                          (window.proxy.mapToSource(window.proxy.index(r, 0)) for r in range(window.proxy.rowCount())))],
                         ['Scar.label'])
        window.clear_filters()
        # 'Hello {0}' translated without the placeholder is a QA error.
        window.status_filter.setCurrentIndex(window.status_filter.findData('qa-error'))
        self.assertEqual(window.proxy.rowCount(), 1)


class ProgressTests(PanelCase):
    def test_sidebar_shows_p0_rate(self):
        window = self.build([
            entry('DefInjected', 'ThingDef', 'Gun.label', 'Gun', '銃'),
            entry('DefInjected', 'ThingDef', 'Gun.description', 'A big gun.', ''),
            entry('Keyed', 'Keyed', 'Hello', 'Hello', 'やあ'),
        ])
        self.assertIn('1 / 2', window.p0_text.text())
        self.assertEqual(window.p0_bar.value(), 50)
        self.assertIn('2 / 3', window.progress_text.text())


class EditorHelperTests(PanelCase):
    def setUp(self):
        self.window = self.build([
            entry('Keyed', 'Keyed', 'Greet', '<b>Hi</b> {0}, \\n bye', ''),
            entry('DefInjected', 'ThingDef', 'Gun.label', 'Gun', ''),
            entry('Keyed', 'Keyed', 'Long', 'A longer sentence that ends here.', ''),
        ])

    def test_palette_inserts_missing_tokens_at_the_cursor(self):
        window = self.window
        self.select('Keyed:Keyed:Greet')
        labels = [b.text() for b in window.token_buttons]
        self.assertIn('{0}', labels)
        window.japanese.setPlainText('こんにちは。')
        cursor = window.japanese.textCursor()
        cursor.setPosition(2)
        window.japanese.setTextCursor(cursor)
        next(b for b in window.token_buttons if b.text() == '{0}').click()
        self.assertEqual(window.japanese.toPlainText(), 'こん{0}にちは。')
        self.assertEqual(window.japanese.textCursor().position(), 5)
        self.assertEqual(window.current.japanese, 'こん{0}にちは。')
        # The inserted token is no longer missing.
        self.assertFalse(next(b for b in window.token_buttons if b.text() == '{0}').property('missing'))

    def test_length_hint_warns_for_wide_short_fields(self):
        window = self.window
        self.select('DefInjected:ThingDef:Gun.label')
        window.japanese.setPlainText('銃')
        self.assertTrue(window.hint_label.text())
        self.assertFalse(window.hint_label.property('over'))
        window.japanese.setPlainText('とても長い名前の銃とても長い名前の銃とても長い名前の銃')
        self.assertTrue(window.hint_label.property('over'))
        self.select('Keyed:Keyed:Long')
        self.assertNotIn('目安', window.hint_label.text())

    def test_preview_renders_line_breaks_and_colour(self):
        window = self.window
        self.select('Keyed:Keyed:Long')
        window.japanese.setPlainText('一行目\\n<color=#ff0000>赤</color>')
        html = window.preview_view.toHtml()
        self.assertIn('赤', html)
        self.assertIn('ff0000', html.lower())
        self.assertGreaterEqual(window.preview_view.document().blockCount() + html.count('<br'), 2)

    def test_advisory_warnings_come_from_qa_extra(self):
        window = self.window
        self.select('Keyed:Keyed:Long')
        window.japanese.setPlainText('ﾃｽﾄ')
        self.assertIn('半角カナ', window.advice_label.text())


class SuggestionTests(PanelCase):
    def setUp(self):
        self.window = self.build([
            entry('DefInjected', 'ThingDef', 'Gun.label', 'Gun', ''),
            entry('DefInjected', 'ThingDef', 'Rifle.label', 'Gun', ''),
            entry('DefInjected', 'ThingDef', 'Pistol.label', 'Gun', ''),
            entry('Keyed', 'Keyed', 'Use', 'Use the Plasma core', ''),
        ], memory=[('Use the Plasma core', '過去のプラズマ核を使う')], glossary={'Plasma': 'プラズマ'})

    def test_memory_and_glossary_are_listed_and_insertable(self):
        window = self.window
        self.select('Keyed:Keyed:Use')
        kinds = [window.suggest_list.item(i).data(Qt.UserRole)[0] for i in range(window.suggest_list.count())]
        self.assertIn('memory', kinds)
        self.assertIn('glossary', kinds)
        memory_row = kinds.index('memory')
        window.suggest_list.setCurrentRow(memory_row)
        window.insert_selected_suggestion()
        self.assertEqual(window.japanese.toPlainText(), '過去のプラズマ核を使う')
        glossary_row = kinds.index('glossary')
        window.japanese.clear()
        window.suggest_list.setCurrentRow(glossary_row)
        window.insert_selected_suggestion()
        self.assertEqual(window.japanese.toPlainText(), 'プラズマ')

    def test_prerequisite_translations_are_listed_with_the_mod_name_and_insertable(self):
        from rimworld_translator.prerequisite_translations import PrerequisiteTranslations
        window = self.window
        index = PrerequisiteTranslations()
        index.add('Sample Lib', 'DefInjected', 'ThingDef', 'Gun.label', '銃')
        index.add('Sample Lib', 'DefInjected', 'ThingDef', 'Gun.description', '強い銃')
        window._prerequisite_translations = (window.prerequisite_token(), index)
        window._force_suggestions = True
        self.select('DefInjected:ThingDef:Gun.label')
        window.refresh_suggestions()
        rows = [window.suggest_list.item(i) for i in range(window.suggest_list.count())]
        found = [item for item in rows if item.data(Qt.UserRole)[0] == 'prerequisite']
        self.assertEqual(len(found), 2)  # the same key, and another field of the same Def
        self.assertIn('Sample Lib', found[0].text())
        self.assertIn('銃', found[0].text())
        window.suggest_list.setCurrentItem(found[0])
        window.insert_selected_suggestion()
        self.assertEqual(window.japanese.toPlainText(), '銃')
        self.select('Keyed:Keyed:Use')
        kinds = [window.suggest_list.item(i).data(Qt.UserRole)[0] for i in range(window.suggest_list.count())]
        self.assertNotIn('prerequisite', kinds)

    def test_prerequisite_lookup_runs_in_the_background_and_refreshes_the_list(self):
        import time
        from rimworld_translator.prerequisite_translations import PrerequisiteTranslations
        window = self.window
        source = Path(window.project.source)
        (source / 'About').mkdir()
        (source / 'About/About.xml').write_text('<ModMetaData><name>S</name><packageId>demo.panel</packageId>'
                                                '<modDependencies><li><packageId>sample.lib</packageId><displayName>Lib</displayName></li>'
                                                '</modDependencies></ModMetaData>')
        index = PrerequisiteTranslations()
        index.add('Sample Lib', 'DefInjected', 'ThingDef', 'Gun.label', '銃')
        from rimworld_translator.scan_context import DependencyContext
        context = DependencyContext((source,), ('sample.lib',), (), (), (), (), (), 'demo.panel')
        with patch('rimworld_translator.scan_context.dependency_context', return_value=context), \
                patch('rimworld_translator.prerequisite_translations.read_prerequisite_translations', return_value=index):
            window._prerequisite_translations = None
            window._force_suggestions = True
            window.refresh_suggestions()
            deadline = time.time() + 10
            while time.time() < deadline and not any(window.suggest_list.item(i).data(Qt.UserRole)[0] == 'prerequisite'
                                                     for i in range(window.suggest_list.count())):
                self.app.processEvents()
                time.sleep(0.02)
        kinds = [window.suggest_list.item(i).data(Qt.UserRole)[0] for i in range(window.suggest_list.count())]
        self.assertIn('prerequisite', kinds)

    def test_apply_to_identical_english(self):
        window = self.window
        self.select('DefInjected:ThingDef:Gun.label')
        window.japanese.setPlainText('銃')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            window.apply_identical_button.click()
        index = window.project.entry_index()
        self.assertEqual(index['DefInjected:ThingDef:Rifle.label'].japanese, '銃')
        self.assertEqual(index['DefInjected:ThingDef:Pistol.label'].japanese, '銃')
        self.assertTrue(window.undo_batches)

    def test_apply_identical_is_disabled_without_a_translation(self):
        window = self.window
        self.select('DefInjected:ThingDef:Gun.label')
        self.assertFalse(window.apply_identical_button.isEnabled())
        self.select('Keyed:Keyed:Use')
        self.assertFalse(window.apply_identical_button.isEnabled())


class NoteTests(PanelCase):
    def setUp(self):
        self.window = self.build([
            entry('Keyed', 'Keyed', 'A', 'Alpha', ''),
            entry('Keyed', 'Keyed', 'B', 'Beta', ''),
        ])

    def test_note_and_flag_are_stored_and_shown_in_the_table(self):
        window = self.window
        self.select('Keyed:Keyed:A')
        window.flag_combo.setCurrentIndex(window.flag_combo.findData('later'))
        window.note_edit.setPlainText('文脈を確認')
        self.assertEqual(window.project.notes['Keyed:Keyed:A'], {'text': '文脈を確認', 'flag': 'later'})
        index = window.model.index(window.model.row_for_id['Keyed:Keyed:A'], 4)
        self.assertTrue(window.model.data(index))
        self.assertIn('文脈を確認', window.model.data(index, Qt.ToolTipRole))
        self.assertTrue(window.dirty)
        self.select('Keyed:Keyed:B')
        self.assertEqual(window.note_edit.toPlainText(), '')
        self.assertEqual(window.flag_combo.currentData(), '')
        self.assertFalse(window.model.data(window.model.index(1, 4)))

    def test_clearing_flag_and_text_removes_the_note(self):
        window = self.window
        self.select('Keyed:Keyed:A')
        window.flag_combo.setCurrentIndex(window.flag_combo.findData('later'))
        window.flag_combo.setCurrentIndex(0)
        self.assertNotIn('Keyed:Keyed:A', window.project.notes)

    def test_toggle_later_flag_shortcut_action(self):
        window = self.window
        self.select('Keyed:Keyed:A')
        window.toggle_later_flag()
        self.assertEqual(window.project.notes['Keyed:Keyed:A']['flag'], 'later')
        window.toggle_later_flag()
        self.assertNotIn('Keyed:Keyed:A', window.project.notes)


class KeyboardFlowTests(PanelCase):
    def setUp(self):
        self.window = self.build([
            entry('Keyed', 'Keyed', 'A', 'Alpha', 'あ'),
            entry('Keyed', 'Keyed', 'B', 'Beta', ''),
            entry('Keyed', 'Keyed', 'C', 'Gamma', 'が', review=True),
            entry('Keyed', 'Keyed', 'D', 'Delta', ''),
            entry('Keyed', 'Keyed', 'E', 'Eps', 'え'),
        ])

    def test_jump_to_next_untranslated_and_needs_review_wraps(self):
        window = self.window
        self.select('Keyed:Keyed:A')
        window.jump_to_next('untranslated')
        self.assertEqual(window.current.key, 'B')
        window.jump_to_next('untranslated')
        self.assertEqual(window.current.key, 'D')
        window.jump_to_next('untranslated')
        self.assertEqual(window.current.key, 'B')
        window.jump_to_next('needs-review')
        self.assertEqual(window.current.key, 'C')
        self.assertEqual(window.proxy.rowCount(), 5, 'jumping must not change the filters')

    def test_jump_with_nothing_left_says_so(self):
        window = self.window
        self.select('Keyed:Keyed:A')
        for key in ('B', 'D'):
            window.project.entry_index()[f'Keyed:Keyed:{key}'].japanese = 'x'
        window.jump_to_next('untranslated')
        self.assertEqual(window.current.key, 'A')
        self.assertIn('未訳', window.statusBar().currentMessage())

    def test_confirm_and_next_reviews_then_moves_to_the_next_row_needing_work(self):
        window = self.window
        self.select('Keyed:Keyed:C')
        window.confirm_and_next()
        self.assertTrue(window.project.entry_index()['Keyed:Keyed:C'].reviewed)
        self.assertEqual(window.current.key, 'D')

    def test_shortcuts_are_registered(self):
        keys = {s.key().toString() for s in window_shortcuts(self.window)}
        for expected in ('Ctrl+J', 'Ctrl+Shift+J', 'Ctrl+Shift+Return', 'Ctrl+K'):
            self.assertIn(expected, keys)


def window_shortcuts(window):
    return window._shortcuts


class ReviewErrorTests(PanelCase):
    def test_review_with_a_qa_error_shows_the_reason_and_does_not_mark(self):
        window = self.build([entry('Keyed', 'Keyed', 'H', 'Hello {0}', 'こんにちは')])
        self.select('Keyed:Keyed:H')
        errors = []
        window.error = errors.append
        window.mark_reviewed()
        self.assertFalse(window.current.reviewed)
        self.assertEqual(len(errors), 1)
        self.assertIn('QAエラー', str(errors[0]))
        self.assertIn('QAエラー', window.review_message.text())
        self.assertFalse(window.review_message.isHidden())
        # Fixing the text clears the message.
        window.japanese.setPlainText('こんにちは {0}')
        self.assertTrue(window.review_message.isHidden())


class LayoutTests(PanelCase):
    def test_long_output_path_is_elided_and_table_keeps_rows(self):
        window = self.build([entry('Keyed', 'Keyed', f'K{i}', f'text {i}', '') for i in range(40)])
        window.project_path = window.project_path.parent / ('x' * 80) / ('y' * 80) / 'project.json'
        window.location.setText('Panel  ·  出力先: ' + '/very/long/path/' * 12)
        window.setFixedSize(1280, 800)
        self.app.processEvents()
        self.app.processEvents()
        self.assertLessEqual(window.location.height(), window.location.fontMetrics().height() * 2)
        rows = window.table.viewport().height() // window.table.verticalHeader().defaultSectionSize()
        self.assertGreaterEqual(rows, 5)

    def test_diagnostics_in_the_detail_pane_are_plain_japanese_with_details_folded(self):
        window = self.build([entry('Keyed', 'Keyed', 'A', 'Alpha', '', confidence='schema', evidence=['CLR Verse.Foo: string field'])])
        self.select('Keyed:Keyed:A')
        text = window.notice.toPlainText()
        self.assertNotIn('Extraction confidence', text)
        self.assertNotIn('CLR', text)
        self.assertTrue(window.notice_details.isHidden())
        window.notice_toggle.click()
        self.assertFalse(window.notice_details.isHidden())
        self.assertIn('CLR', window.notice_details.toPlainText())


if __name__ == '__main__':
    unittest.main()

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import date
from pathlib import Path
import tempfile
import time
import unittest

from PySide6.QtWidgets import QApplication

from rimworld_translator.gui import Window
from rimworld_translator.navigator import group_stats, in_scope
from rimworld_translator.settings import SettingsStore


class Entry:
    def __init__(self, kind, group, key, japanese='', **flags):
        self.kind, self.group, self.key, self.japanese = kind, group, key, japanese
        self.blocked = self.stale = self.excluded = False
        self.evidence = ()
        self.__dict__.update(flags)


class NavigatorTests(unittest.TestCase):
    def test_scope_matching(self):
        entry = Entry('DefInjected', 'ThingDef', 'Gun.label')
        self.assertTrue(in_scope(entry, ()))
        self.assertTrue(in_scope(entry, ('DefInjected',)))
        self.assertTrue(in_scope(entry, ('DefInjected', 'ThingDef')))
        self.assertTrue(in_scope(entry, ('DefInjected', 'ThingDef', 'Gun')))
        self.assertFalse(in_scope(entry, ('DefInjected', 'ThingDef', 'Rifle')))
        self.assertFalse(in_scope(entry, ('Keyed',)))

    def test_group_stats_count_only_translatable_entries(self):
        entries = [Entry('DefInjected', 'ThingDef', 'A.label', '訳'), Entry('DefInjected', 'ThingDef', 'B.label'),
                   Entry('DefInjected', 'ThingDef', 'C.label', excluded=True), Entry('Keyed', 'Main', 'Hello')]
        rows, remaining, total = group_stats(entries)
        self.assertEqual((remaining, total), (2, 3))
        self.assertEqual(rows[0][:2], ('DefInjected', 'ThingDef'))
        self.assertEqual(rows[0][2:], (1, 2))


class SettingsTests(unittest.TestCase):
    def test_daily_counts_and_tree_flag_are_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 's.json'
            path.write_text('{"daily_counts": {"2026-01-01": "many"}, "show_tree": "yes"}')
            data = SettingsStore(path).data
            self.assertEqual(data['daily_counts'], {})
            self.assertIs(data['show_tree'], True)


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'source'
        (self.source / 'Defs').mkdir(parents=True)
        (self.source / 'Defs/Items.xml').write_text(
            '<Defs><ThingDef><defName>Gun</defName><label>gun</label><description>long text</description></ThingDef>'
            '<ThingDef><defName>Rifle</defName><label>rifle</label><description>another text</description></ThingDef></Defs>')
        self.window = Window(settings_path=root / 's.json')
        # Keep suggestions independent of the game's official packs installed on this machine.
        from rimworld_translator.official_translations import OfficialIndex
        self.window._official = ('Japanese', OfficialIndex())
        self.window.settings.data['inspect_metadata'] = False
        self.window.error = lambda message: self.fail(str(message))
        self.window.show()
        self.app.processEvents()
        def close():
            self.window.dirty = False
            self.window.close()
            self.app.processEvents()
        self.addCleanup(close)
        self.window.start_scan(self.source, root / 'ws/project.json')
        deadline = time.monotonic() + 10
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()

    def test_tabs_are_disabled_until_a_project_is_open_then_switch_pages(self):
        w = self.window
        self.assertTrue(w.workspace_tabs.isEnabled())
        for index, (translate, progress, export) in enumerate(((True, False, False), (True, False, False),
                                                                (False, True, False), (False, False, True))):
            w.workspace_tabs.setCurrentIndex(index)
            self.app.processEvents()
            self.assertEqual((w.translate_page.isVisible(), w.progress_page.isVisible(), w.export_page.isVisible()),
                             (translate, progress, export), index)

    def test_review_tab_shows_only_entries_needing_attention(self):
        w = self.window
        total = w.proxy.rowCount()
        w.model.entries[0].review = True
        w.workspace_tabs.setCurrentIndex(1)
        self.assertLessEqual(w.proxy.rowCount(), total)
        self.assertTrue(all(w.model.entries[w.proxy.mapToSource(w.proxy.index(r, 0)).row()].status in ('changed', 'needs-review')
                            for r in range(w.proxy.rowCount())))
        w.workspace_tabs.setCurrentIndex(0)
        self.assertEqual(w.proxy.rowCount(), total)

    def test_tree_selection_narrows_the_table(self):
        w = self.window
        total = w.proxy.rowCount()
        w.entry_tree.setCurrentItem(w.entry_tree.topLevelItem(0).child(0).child(0))
        self.app.processEvents()
        self.assertLessEqual(w.proxy.rowCount(), total)
        self.assertTrue(w.proxy.scope)
        w.entry_tree.setCurrentItem(w.entry_tree.topLevelItem(0))
        self.app.processEvents()
        self.assertEqual(w.proxy.rowCount(), total)

    def test_translating_counts_today_and_updates_progress(self):
        w = self.window
        before = w.settings.data['daily_counts'].get(date.today().isoformat(), 0)
        w.model.setData(w.model.index(0, 3), '訳')
        w.model.setData(w.model.index(0, 3), '訳2')   # editing an already translated entry is not a new one
        self.assertEqual(w.settings.data['daily_counts'][date.today().isoformat()], before + 1)
        w.workspace_tabs.setCurrentIndex(2)
        self.assertIn('1 /', w.progress_summary.text())
        self.assertIn('1', w.progress_today.text())

    def test_focus_mode_hides_the_list_and_restores_the_filter(self):
        w = self.window
        w.set_focus_mode(True)
        self.app.processEvents()
        self.assertTrue(w.focus_mode)
        self.assertFalse(w.table.isVisible())
        self.assertTrue(w.focus_bar.isVisible())
        self.assertEqual(w.status_filter.currentData(), 'untranslated')
        w.set_focus_mode(False)
        self.app.processEvents()
        self.assertFalse(w.focus_mode)
        self.assertTrue(w.table.isVisible())
        self.assertEqual(w.status_filter.currentData() or '', '')

    def test_confirming_in_focus_mode_moves_to_the_next_untranslated_entry(self):
        w = self.window
        w.set_focus_mode(True)
        first = w.current.id
        w.japanese.setPlainText('訳')
        w.mark_reviewed()
        self.app.processEvents()
        self.assertNotEqual(w.current.id, first)
        self.assertEqual(w.current.japanese, '')

    def test_keyboard_shortcuts_switch_tabs_and_step_entries(self):
        from PySide6.QtGui import QShortcut
        w = self.window
        keys = {shortcut.key().toString() for shortcut in w.findChildren(QShortcut)}
        for expected in ('Ctrl+1', 'Ctrl+4', 'Alt+Down', 'Alt+Up', 'Ctrl+L', 'F3', 'F1'):
            self.assertIn(expected, keys)
        w.table.setCurrentIndex(w.proxy.index(0, 0))
        first = w.current.id
        w.step_entry(1)
        self.assertNotEqual(w.current.id, first)
        w.step_entry(-1)
        self.assertEqual(w.current.id, first)
        w.step_entry(-1)   # already at the top: stays put instead of failing
        self.assertEqual(w.current.id, first)

    def test_shortcut_help_lists_the_main_keys(self):
        w = self.window
        shown = []
        w.info_dialog = lambda title, body: shown.append(body)
        w.shortcut_help()
        for key in ('Ctrl+S', 'Alt+', 'F3', 'Ctrl+Shift+F'):
            self.assertIn(key, shown[0])

    def test_tree_uses_plain_names_and_keeps_technical_names_in_tooltips(self):
        w = self.window
        kind = w.entry_tree.topLevelItem(0).child(0)
        self.assertIn('定義の文章', kind.text(0))
        self.assertEqual(kind.toolTip(0), 'DefInjected')

    def test_progress_page_points_at_the_group_closest_to_done(self):
        w = self.window
        w.model.setData(w.model.index(0, 3), '訳')
        w.workspace_tabs.setCurrentIndex(2)
        self.assertIn('完了', w.progress_today.text())

    def test_status_column_is_coloured_by_theme_and_keeps_its_text(self):
        from PySide6.QtCore import Qt
        w = self.window
        w.set_theme_mode('dark', persist=False)
        dark = w.model.data(w.model.index(0, 0), Qt.ForegroundRole).color().name()
        w.set_theme_mode('light', persist=False)
        light = w.model.data(w.model.index(0, 0), Qt.ForegroundRole).color().name()
        self.assertNotEqual(dark, light)
        self.assertTrue(w.model.data(w.model.index(0, 0), Qt.DisplayRole))
        self.assertIsNone(w.model.data(w.model.index(0, 1), Qt.ForegroundRole))

    def test_empty_table_explains_why_and_offers_to_clear_filters(self):
        w = self.window
        self.assertFalse(w.empty_state.isVisible())
        w.search.setText('zzz-no-such-text')
        self.app.processEvents()
        self.assertTrue(w.empty_state.isVisible())
        self.assertIn('条件に合う', w.empty_title.text())
        self.assertTrue(w.empty_action.isVisible())
        w.empty_action.click()
        self.app.processEvents()
        self.assertFalse(w.empty_state.isVisible())
        self.assertGreater(w.proxy.rowCount(), 0)

    def test_review_tab_with_nothing_to_review_says_so(self):
        w = self.window
        for entry in w.model.entries:
            entry.review = False
        w.workspace_tabs.setCurrentIndex(1)
        self.app.processEvents()
        if w.proxy.rowCount() == 0:
            self.assertIn('確認が必要な項目はありません', w.empty_title.text())
            self.assertFalse(w.empty_action.isVisible())

    def test_same_source_translation_is_offered_and_inserted_with_one_key(self):
        w = self.window
        # Two entries sharing the same English: translating one offers its translation for the other.
        a, b = w.model.entries[0], w.model.entries[1]
        b.english = a.english
        w.model.setData(w.model.index(0, 3), '共通の訳')
        w.table.setCurrentIndex(w.proxy.index(1, 0))
        self.app.processEvents()
        self.assertEqual(w.suggestions, ['共通の訳'])
        self.assertIn('共通の訳', w.japanese.placeholderText())
        w.insert_suggestion(0)
        self.assertEqual(w.model.entries[1].japanese, '共通の訳')

    def test_official_translation_is_offered_after_own_translations(self):
        from rimworld_translator.official_translations import OfficialIndex
        w = self.window
        entry = w.model.entries[1]
        index = OfficialIndex()
        index.add(entry.kind, entry.group, entry.key, entry.english, '公式の訳')
        w._official = (w.project.language, index)
        w.table.setCurrentIndex(w.proxy.index(1, 0))
        self.app.processEvents()
        self.assertEqual(w.suggestions, ['公式の訳'])
        self.assertIn('公式訳: [1] 公式の訳', w.japanese.placeholderText())

    def test_version_actions_live_in_one_menu_and_keep_the_old_buttons_working(self):
        w = self.window
        self.assertFalse(w.scan_declared_button.isVisible())
        self.assertTrue(w.version_menu_button.isVisible())
        self.assertEqual(len(w.version_menu.actions()), 3)
        calls = []
        w.scan_declared_versions_dialog = lambda: calls.append(1)
        w.scan_declared_button.clicked.disconnect()
        w.scan_declared_button.clicked.connect(w.scan_declared_versions_dialog)
        w.scan_declared_button.setEnabled(True)
        w.version_menu.actions()[1].trigger()
        self.assertEqual(calls, [1])

    def test_export_page_summarises_qa(self):
        w = self.window
        w.workspace_tabs.setCurrentIndex(3)
        self.assertIn('QA', w.export_summary.text())


if __name__ == '__main__':
    unittest.main()

"""The main table stays cheap to open and filter on large projects (see tools/benchmark_table.py)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Entry, Project
from rimworld_translator.gui import Window


def make_project(root, count):
    (root / 'source').mkdir()
    entries = [Entry(f'DefInjected:ThingDef:Item{i}.label', 'DefInjected', 'ThingDef', f'Item{i}.label',
                     f'Sample item {i}', f'Defs/f{i % 3}.xml') for i in range(count)]
    project = Project(str(root / 'source'), 'Big', 'local.big', 'demo.big', ['1.6'], entries, [], languages=['Japanese'])
    path = root / 'workspace/project.json'
    project.save(path)
    return path


class LargeTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = make_project(self.root, 40)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_opening_a_project_refilters_the_table_once(self):
        calls = []
        original = self.window.proxy.invalidate
        self.window.proxy.invalidate = lambda: (calls.append(1), original())[1]
        self.window.load_project(self.path)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.window.proxy.rowCount(), 40)

    def test_search_sees_a_translation_typed_after_opening(self):
        self.window.load_project(self.path)
        self.window.search.setText('ねこ')
        self.assertEqual(self.window.proxy.rowCount(), 0)
        row = self.window.model.row_for_id['DefInjected:ThingDef:Item7.label']
        self.window.model.setData(self.window.model.index(row, 3), 'ねこ')
        self.window.search.setText('ねこ ')
        self.window.search.setText('ねこ')
        self.assertEqual(self.window.proxy.rowCount(), 1)
        # Editing it away again is seen as well.
        self.window.model.setData(self.window.model.index(row, 3), 'いぬ')
        self.window.search.setText('ねこ ')
        self.window.search.setText('ねこ')
        self.assertEqual(self.window.proxy.rowCount(), 0)

    def test_search_after_replacing_the_entries_uses_the_new_rows(self):
        self.window.load_project(self.path)
        self.window.search.setText('item 3')
        first = self.window.proxy.rowCount()
        self.assertGreater(first, 0)
        other = make_project(self.root / 'second', 5) if (self.root / 'second').mkdir() is None else None
        self.window.load_project(other)
        self.window.search.setText('item 3')
        self.assertEqual(self.window.proxy.rowCount(), 1)

    def test_typing_in_a_large_project_filters_once_after_a_pause(self):
        self.window.load_project(self.path)
        self.window.LARGE_PROJECT_ROWS = 10
        calls = []
        original = self.window.proxy.invalidate
        self.window.proxy.invalidate = lambda: (calls.append(1), original())[1]
        for text in ('i', 'it', 'ite', 'item 3'):
            self.window.search.setText(text)
        self.assertEqual(calls, [])  # nothing filtered while typing
        self.assertTrue(self.window._search_timer.isActive())
        self.window._search_timer.timeout.emit()
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.window.proxy.query, 'item 3')
        self.assertIn('/ 全 40', self.window.counts.text())

    def test_small_projects_filter_on_every_keystroke(self):
        self.window.load_project(self.path)
        self.window.search.setText('item 39')
        self.assertEqual(self.window.proxy.rowCount(), 1)

    def test_navigate_entry_finds_the_row_through_filters(self):
        self.window.load_project(self.path)
        self.window.search.setText('item 1')
        self.window.navigate_entry('DefInjected:ThingDef:Item39.label')
        self.assertEqual(self.window.current.id, 'DefInjected:ThingDef:Item39.label')


if __name__ == '__main__':
    unittest.main()

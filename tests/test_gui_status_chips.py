"""Status chips filter the list and stay in sync with the status dropdown."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Entry, Project
from rimworld_translator.gui import Window


class StatusChipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'source').mkdir()
        entries = [Entry(f'Keyed:Keyed:K{i}', 'Keyed', 'Keyed', f'K{i}', f'text {i}', 'Keys.xml', ja)
                   for i, ja in enumerate(('訳', '', ''))]
        project = Project(str(root / 'source'), 'Chips', 'local.chips', 'demo.chips', ['1.6'], entries, [],
                          languages=['Japanese'])
        path = root / 'workspace/project.json'
        project.save(path)
        self.window = Window(settings_path=root / 'settings.json')
        self.window.load_project(path)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_chips_show_counts_filter_and_follow_the_dropdown(self):
        chips = self.window.status_chips
        self.assertTrue(chips[''].isChecked())
        self.assertTrue(chips[''].text().endswith('3'))
        self.assertTrue(chips['untranslated'].text().endswith('2'))
        self.assertTrue(chips['translated'].text().endswith('1'))
        chips['untranslated'].click()
        self.assertEqual(self.window.status_filter.currentData(), 'untranslated')
        self.assertEqual(self.window.proxy.rowCount(), 2)
        self.assertEqual([key for key, chip in chips.items() if chip.isChecked()], ['untranslated'])
        # The dropdown owns the state: changing it moves the checked chip.
        self.window.status_filter.setCurrentIndex(self.window.status_filter.findData('translated'))
        self.assertEqual([key for key, chip in chips.items() if chip.isChecked()], ['translated'])
        self.assertEqual(self.window.proxy.rowCount(), 1)
        chips[''].click()
        self.assertEqual(self.window.proxy.rowCount(), 3)

    def test_clear_button_appears_only_while_filtered_and_resets_everything(self):
        clear = self.window.clear_filters_button
        self.assertTrue(clear.isHidden())
        self.window.search.setText('text 1')
        self.assertFalse(clear.isHidden())
        self.assertEqual(self.window.proxy.rowCount(), 1)
        clear.click()
        self.assertTrue(clear.isHidden())
        self.assertEqual(self.window.search.text(), '')
        self.assertEqual(self.window.proxy.rowCount(), 3)
        self.window.status_chips['untranslated'].click()
        self.assertFalse(clear.isHidden())

    def test_status_column_has_a_colour_dot(self):
        index = self.window.model.index(0, 0)
        self.assertIsNotNone(self.window.model.data(index, Qt.DecorationRole))
        self.assertIsNone(self.window.model.data(self.window.model.index(0, 1), Qt.DecorationRole))


if __name__ == '__main__':
    unittest.main()

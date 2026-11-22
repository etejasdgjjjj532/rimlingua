"""Small encouragements: milestone and daily messages, and how the window shows them."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QApplication
from rimworld_translator.cheer import daily_cheer, progress_cheer, today_line
from rimworld_translator.core import Entry, Project
from rimworld_translator.gui import Window


class CheerMessageTests(unittest.TestCase):
    def test_progress_cheer_names_the_highest_milestone_crossed_upwards(self):
        self.assertEqual(progress_cheer(10, 24), '')
        self.assertIn('4分の1', progress_cheer(24, 25))
        self.assertIn('半分', progress_cheer(49, 50))
        self.assertIn('半分', progress_cheer(20, 55))  # a bulk change skips 25: only the highest is named
        self.assertIn('書き出', progress_cheer(99, 100))

    def test_progress_cheer_is_silent_without_progress(self):
        self.assertEqual(progress_cheer(50, 50), '')
        self.assertEqual(progress_cheer(60, 40), '')  # going back (undo, new entries) is not celebrated

    def test_progress_cheer_has_an_english_form(self):
        self.assertIn('Halfway', progress_cheer(49, 50, english=True))

    def test_daily_cheer_only_at_round_numbers(self):
        self.assertIn('1件目', daily_cheer(1))
        self.assertEqual(daily_cheer(2), '')
        self.assertIn('10件', daily_cheer(10))
        self.assertIn('100件', daily_cheer(100))
        self.assertIn('First', daily_cheer(1, english=True))

    def test_today_line_grows_with_the_count_and_always_shows_it(self):
        for count in (0, 1, 9, 10, 49, 50, 99, 100, 250):
            self.assertIn(str(count), today_line(count))
        self.assertNotEqual(today_line(0), today_line(10))
        self.assertNotEqual(today_line(10), today_line(100))


class CheerWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'source').mkdir()
        path = self.make_project('workspace', 10)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(path)
        self.addCleanup(self.close_window)

    def make_project(self, folder, size):
        entries = [Entry(f'Keyed:Keyed:K{i}', 'Keyed', 'Keyed', f'K{i}', f'text {i}', 'Keys.xml', '')
                   for i in range(size)]
        project = Project(str(self.root / 'source'), 'Cheer', 'local.cheer', 'demo.cheer', ['1.6'], entries, [],
                          languages=['Japanese'])
        path = self.root / folder / 'project.json'
        project.save(path)
        return path

    def wait_for_progress(self, value):
        import time
        from PySide6.QtTest import QTest
        deadline = time.monotonic() + 3
        while self.window.progress.value() != value and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertEqual(self.window.progress.value(), value)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def translate(self, row, text='訳'):
        self.assertTrue(self.window.model.setData(self.window.model.index(row, 3), text))

    def test_first_translation_of_the_day_is_acknowledged(self):
        self.assertEqual(self.window.cheer_label.text(), '')
        self.translate(0)
        self.assertIn('1件目', self.window.cheer_label.text())

    def test_crossing_half_way_is_acknowledged_and_replaces_the_daily_note(self):
        for row in range(5):  # 5 of 10 translated = 50%
            self.translate(row)
        self.assertIn('半分', self.window.cheer_label.text())

    def test_completing_every_entry_points_at_export(self):
        for row in range(10):
            self.translate(row)
        self.assertIn('書き出', self.window.cheer_label.text())

    def test_filter_changes_and_rescans_do_not_cheer(self):
        self.window.cheer_label.setText('')
        self.window.refresh_counts()
        self.assertEqual(self.window.cheer_label.text(), '')

    def test_progress_bar_slides_to_the_new_value_when_shown(self):
        self.window.show()
        self.app.processEvents()
        for row in range(3):  # 30%
            self.translate(row)
        self.assertLess(self.window.progress.value(), 30)  # still on its way: the bar did not jump
        self.wait_for_progress(30)

    def test_one_entry_left_is_not_reported_as_complete(self):
        self.window.load_project(self.make_project('large', 200))
        for row in range(199):
            self.translate(row)
        self.assertEqual(self.window.progress.value(), 99)  # round(99.5) would claim 100
        self.assertNotIn('書き出', self.window.cheer_label.text())
        self.translate(199)
        self.assertEqual(self.window.progress.value(), 100)
        self.assertIn('書き出', self.window.cheer_label.text())

    def test_opening_another_project_clears_the_note_and_sets_the_bar_directly(self):
        self.window.show()
        self.app.processEvents()
        for row in range(5):
            self.translate(row)
        self.wait_for_progress(50)
        self.window.load_project(self.make_project('other', 10))
        self.assertEqual(self.window.cheer_label.text(), '')
        self.assertEqual(self.window.progress.value(), 0)

    def test_progress_bar_jumps_at_once_while_hidden(self):
        for row in range(3):
            self.translate(row)
        self.assertEqual(self.window.progress.value(), 30)

    def test_reduce_motion_makes_the_bar_jump_even_when_shown(self):
        self.window.show()
        self.app.processEvents()
        self.window.reduce_motion_action.trigger()
        self.assertTrue(self.window.settings.data['reduce_motion'])
        for row in range(3):
            self.translate(row)
        self.assertEqual(self.window.progress.value(), 30)

    def test_cheer_fades_after_its_timer(self):
        self.translate(0)
        self.assertTrue(self.window.cheer_label.text())
        self.window.cheer_timer.timeout.emit()
        self.assertEqual(self.window.cheer_label.text(), '')
        self.assertFalse(self.window.cheer_label.isVisibleTo(self.window))


if __name__ == '__main__':
    unittest.main()

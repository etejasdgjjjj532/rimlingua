"""The game library location is set in Preferences and opening it never creates the folder."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton
from rimworld_translator.gui import Window


class PreferencesLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def run_dialog(self, act):
        def exec_dialog(dialog):
            act(dialog)
            return QDialog.Accepted
        with patch.object(QDialog, 'exec', exec_dialog):
            self.window.preferences_dialog()

    def library_field(self, dialog):
        return next(field for field in dialog.findChildren(QLineEdit) if 'games' in field.placeholderText())

    def test_library_location_is_saved(self):
        chosen = str(self.root / 'my games')
        self.run_dialog(lambda dialog: self.library_field(dialog).setText(chosen))
        self.assertEqual(self.window.settings.data['game_library'], chosen)

    def test_open_library_never_creates_the_folder(self):
        missing = self.root / 'not yet'
        shown = []
        def act(dialog):
            self.library_field(dialog).setText(str(missing))
            button = next(b for b in dialog.findChildren(QPushButton) if b.text() in ('ライブラリを開く', 'Open library'))
            with patch.object(self.window, 'info_dialog', lambda title, value: shown.append(value)):
                button.click()
        self.run_dialog(act)
        self.assertFalse(missing.exists())
        self.assertTrue(shown and str(missing) in shown[0])

    def test_open_failure_on_an_existing_folder_says_it_could_not_open(self):
        existing = self.root / 'games'
        existing.mkdir()
        shown = []
        def act(dialog):
            self.library_field(dialog).setText(str(existing))
            button = next(b for b in dialog.findChildren(QPushButton) if b.text() in ('ライブラリを開く', 'Open library'))
            with patch.object(self.window, 'info_dialog', lambda title, value: shown.append(value)), \
                    patch('PySide6.QtGui.QDesktopServices.openUrl', return_value=False):
                button.click()
        self.run_dialog(act)
        self.assertTrue(shown)
        self.assertNotIn('ありません', shown[0])
        self.assertNotIn('does not exist', shown[0])


if __name__ == '__main__':
    unittest.main()

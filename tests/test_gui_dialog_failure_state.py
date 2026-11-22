"""Dialog failure paths: stale match state, empty error text and one row-key helper."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from rimworld_translator import dialogs_tools as tools
from rimworld_translator.core import Entry, Project
from rimworld_translator.gui import Window


def keyed(key, english, japanese=''):
    return Entry(f'Keyed:Keyed:{key}', 'Keyed', 'Keyed', key, english, 'Keyed/Main.xml', japanese)


class DialogFailureState(unittest.TestCase):
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
        project = Project(str(self.source), 'Example', 'local.translation.example', 'author.original', ['1.6'],
                          [keyed('A', 'Hello there.', 'こんにちは。'), keyed('B', 'Open the door.')], [])
        self.path = self.root / 'work/project.json'
        project.save(self.path)
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

    def good_mod(self):
        mod = self.root / 'theirs'
        (mod / 'About').mkdir(parents=True)
        (mod / 'About/About.xml').write_text('<ModMetaData><name>Their JP</name></ModMetaData>')
        (mod / 'Languages/Japanese/Keyed').mkdir(parents=True)
        (mod / 'Languages/Japanese/Keyed/Main.xml').write_text(
            '<?xml version="1.0" encoding="utf-8"?><LanguageData><B>開けて。</B></LanguageData>', encoding='utf-8')
        return mod

    def test_failed_read_clears_previous_match_and_keeps_import_disabled(self):
        dialog = tools.MatchModDialog(self.window)
        dialog.load(self.good_mod())
        dialog.overwrite.setChecked(False)
        self.assertTrue(dialog.import_button.isEnabled())
        self.assertIsNone(dialog.load(self.root / 'does-not-exist'))
        self.assertIsNone(dialog.match)
        self.assertIsNone(dialog.mod)
        dialog.overwrite.setChecked(True)
        dialog.overwrite.setChecked(False)
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertEqual(dialog.lists['new'].topLevelItemCount(), 0)

    def test_workshop_diff_note_survives_an_error_with_no_text(self):
        dialog = tools.WorkshopDialog(self.window)
        dialog.include_diff.setChecked(True)
        with patch('rimworld_translator.export_diff.export_diff', side_effect=ValueError('')):
            options = dialog._options()
        self.assertIn('Output changes left out', dialog._diff_note)
        self.assertIsNone(options['diff'])

    def test_row_key_helper_is_shared(self):
        self.assertEqual(tools.row_key('Keyed:Keyed:Some:Key'), 'Some:Key')
        self.assertEqual(tools.row_key('Keyed:Keyed:Plain'), 'Plain')
        self.assertEqual(tools.row_key('NoColons'), 'NoColons')


if __name__ == '__main__':
    unittest.main()

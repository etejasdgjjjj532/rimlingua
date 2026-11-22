"""History restore regenerates into the resolved (possibly custom) output folder and reports notices."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rimworld_translator import history
from rimworld_translator.core import Entry, Project, export_mod
from rimworld_translator.history import list_snapshots, snapshot

REL = 'Languages/Japanese/DefInjected/ThingDef/Translations.xml'


class CustomOutputRestoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'source').mkdir()
        self.entry = 'DefInjected:ThingDef:Gun.label'
        self.project = Project(str(self.root / 'source'), 'Example', 'local.translation.hist', 'author.original', ['1.6'],
                               [Entry(self.entry, 'DefInjected', 'ThingDef', 'Gun.label', 'gun', 'Things.xml')], [])
        self.path = self.root / 'workspace/project.json'
        self.custom = self.root / 'release/my-mod'
        self.project.output_folder = str(self.custom)
        self.write('銃')

    def write(self, text):
        self.project.set_translation(self.entry, text)
        self.project.mark_reviewed(self.entry, approved=True)
        self.project.save(self.path)
        export_mod(self.project, self.custom)

    def test_restore_rewrites_the_custom_folder_not_the_default_one(self):
        with patch('rimworld_translator.history.shutil.which', return_value=None):
            self.assertTrue(snapshot(self.path, 'first'))
            first = list_snapshots(self.path)[0]
            self.write('ライフル')
            report = history.restore_snapshot_report(self.path, first.id)
        self.assertIn('銃', (self.custom / REL).read_text(encoding='utf-8'))
        self.assertFalse((self.path.parent / 'mod').exists())
        self.assertEqual(report.project.output_folder, str(self.custom))
        self.assertEqual(Project.load(self.path).output_folder, str(self.custom))

    def test_explicit_export_folder_is_used(self):
        with patch('rimworld_translator.history.shutil.which', return_value=None):
            self.assertTrue(snapshot(self.path, 'first'))
            first = list_snapshots(self.path)[0]
            self.write('ライフル')
            history.restore_snapshot_report(self.path, first.id, export_folder=self.custom)
        self.assertIn('銃', (self.custom / REL).read_text(encoding='utf-8'))

    def test_foreign_custom_folder_is_never_replaced(self):
        with patch('rimworld_translator.history.shutil.which', return_value=None):
            self.assertTrue(snapshot(self.path, 'first'))
            first = list_snapshots(self.path)[0]
            (self.custom / 'precious.txt').write_text('mine')
            with self.assertRaises(ValueError):
                history.restore_snapshot_report(self.path, first.id)
        self.assertTrue((self.custom / 'precious.txt').exists())


if __name__ == '__main__':
    unittest.main()

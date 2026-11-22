"""Restoring a multi-version project from history keeps (and regenerates) its formal output."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rimworld_translator.core import Entry, Project, Scan, export_shared
from rimworld_translator import history
from rimworld_translator.history import list_snapshots, restore_snapshot, snapshot

REL = 'Languages/Japanese/DefInjected/ThingDef/Translations.xml'


def thing():
    return Entry('DefInjected:ThingDef:Gun.label', 'DefInjected', 'ThingDef', 'Gun.label', 'gun', 'Things.xml')


class MultiVersionRestoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        scans = {v: Scan(entries=[thing()], name='Fixture', package_id='test.history', versions=['1.5', '1.6'],
                         stats={'active_version': v}) for v in ('1.5', '1.6')}
        self.project = Project.create_versions(self.source, scans)
        self.path = self.root / 'workspace/project.json'
        self.translate('銃')

    def translate(self, text):
        for version in ('1.5', '1.6'):
            self.project.switch_version(version)
            self.project.set_translation('DefInjected:ThingDef:Gun.label', text)
            self.project.mark_reviewed('DefInjected:ThingDef:Gun.label', approved=True)
        self.project.save(self.path)
        export_shared(self.project, self.path.parent / 'mod')

    def test_restore_regenerates_shared_output(self):
        with patch('rimworld_translator.history.shutil.which', return_value=None):
            self.assertTrue(snapshot(self.path, 'first'))
            first = list_snapshots(self.path)[0]
            self.translate('ライフル')
            restored = restore_snapshot(self.path, first.id)
        self.assertTrue(restored.version_profiles)
        self.assertIn('銃', (self.path.parent / 'mod' / REL).read_text(encoding='utf-8'))
        self.assertNotIn('ライフル', (self.path.parent / 'mod' / REL).read_text(encoding='utf-8'))

    def test_restore_keeps_current_output_when_nothing_is_ready(self):
        with patch('rimworld_translator.history.shutil.which', return_value=None):
            self.assertTrue(snapshot(self.path, 'translated'))
            empty = Project.load(self.path)
            for version in ('1.5', '1.6'):
                empty.switch_version(version)
                empty.set_translation('DefInjected:ThingDef:Gun.label', '')
            empty.save(self.path)
            self.assertTrue(snapshot(self.path, 'untranslated'))
            untranslated = list_snapshots(self.path)[0]
            self.project = Project.load(self.path)
            self.translate('銃')
            report = history.restore_snapshot_report(self.path, untranslated.id)
        self.assertFalse(report.output_updated)
        self.assertTrue(report.notices)
        self.assertEqual(Project.load(self.path).get_translation('DefInjected:ThingDef:Gun.label'), '')
        self.assertIn('銃', (self.path.parent / 'mod' / REL).read_text(encoding='utf-8'))


class PruneTests(unittest.TestCase):
    def make(self, root):
        (root / 'source').mkdir()
        project = Project(str(root / 'source'), 'Example', 'local.translation.prune', 'author.original', ['1.6'],
                          [Entry('Keyed:Keyed:Hello', 'Keyed', 'Keyed', 'Hello', 'Hello', 'Main.xml')], [])
        return project, root / 'workspace/project.json'

    def test_file_backend_keeps_newest_generations(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, path = self.make(Path(temporary))
            with patch('rimworld_translator.history.shutil.which', return_value=None):
                for number in range(5):
                    project.entries[0].japanese = f'訳{number}'
                    project.save(path)
                    snapshot(path, f'save {number}')
                removed = history.prune_snapshots(path, keep=2)
                remaining = list_snapshots(path)
            self.assertEqual(len(removed), 3)
            self.assertEqual([record.message for record in remaining], ['save 4', 'save 3'])
            self.assertEqual(len(list((path.parent / '.history/snapshots').iterdir())), 2)
            with self.assertRaises(ValueError):
                history.prune_snapshots(path, keep=0)

    def test_snapshot_prunes_when_keep_is_given(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, path = self.make(Path(temporary))
            with patch('rimworld_translator.history.shutil.which', return_value=None):
                for number in range(4):
                    project.entries[0].japanese = f'訳{number}'
                    project.save(path)
                    snapshot(path, f'save {number}', keep=3)
                self.assertEqual(len(list_snapshots(path)), 3)


if __name__ == '__main__':
    unittest.main()

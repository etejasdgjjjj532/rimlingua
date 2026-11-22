"""Opening a JSON file that is not a project must never move or rename it."""
import tempfile
import unittest
from pathlib import Path

from rimworld_translator.core import Entry, Project, ProjectFileError


class ProjectLoadSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_non_project_json_is_left_untouched(self):
        other = self.root / 'settings.json'
        other.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ProjectFileError) as raised:
            Project.load(other)
        self.assertIsNone(raised.exception.kept_at)
        self.assertEqual(other.read_text(encoding='utf-8'), '{broken')
        self.assertEqual([p.name for p in self.root.iterdir()], ['settings.json'])

    def test_non_object_json_in_other_file_is_left_untouched(self):
        other = self.root / 'list.json'
        other.write_text('[1, 2]', encoding='utf-8')
        with self.assertRaises(ValueError):
            Project.load(other)
        self.assertTrue(other.exists())

    def test_corrupt_project_json_is_still_kept_aside(self):
        target = self.root / 'project.json'
        target.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ProjectFileError) as raised:
            Project.load(target)
        self.assertIsNotNone(raised.exception.kept_at)
        self.assertFalse(target.exists())
        self.assertTrue(raised.exception.kept_at.exists())

    def test_a_renamed_project_that_loaded_before_is_kept_aside_when_corrupt(self):
        source = self.root / 'src'
        source.mkdir()
        project = Project(str(source), 'N', 'local.n', 'a.b', ['1.6'],
                          [Entry('Keyed:Keyed:A', 'Keyed', 'Keyed', 'A', 'Alpha', 'Keyed/Main.xml')], [])
        (self.root / 'out').mkdir()
        saved = self.root / 'out/mine.json'
        project.save(saved)
        Project.load(saved)
        saved.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ProjectFileError) as raised:
            Project.load(saved)
        self.assertIsNotNone(raised.exception.kept_at)


if __name__ == '__main__':
    unittest.main()

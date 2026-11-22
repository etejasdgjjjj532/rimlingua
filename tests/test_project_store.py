"""Project-file additions: per-row notes, per-file assignments and corrupt-file handling."""
import json
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import notes
from rimworld_translator.core import Entry, Project, ProjectFileError


def make_project(source='/nonexistent/source'):
    rows = [Entry('Keyed:Keyed:A', 'Keyed', 'Keyed', 'A', 'Alpha', 'Keyed/Main.xml'),
            Entry('Keyed:Keyed:B', 'Keyed', 'Keyed', 'B', 'Beta', 'Keyed/Other.xml')]
    return Project(source, 'Example', 'local.translation.store', 'author.original', ['1.6'], rows, [])


class NotesTests(unittest.TestCase):
    def test_notes_roundtrip_through_project_json(self):
        project = make_project()
        notes.set_note(project, 'Keyed:Keyed:A', 'ゲーム内で確認する', flag='later')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            project.save(path)
            loaded = Project.load(path)
        self.assertEqual(notes.get_note(loaded, 'Keyed:Keyed:A'), notes.Note('ゲーム内で確認する', 'later'))
        self.assertEqual([item[0] for item in notes.list_notes(loaded, flag='later')], ['Keyed:Keyed:A'])

    def test_empty_note_removes_it_and_unknown_rows_are_refused(self):
        project = make_project()
        notes.set_note(project, 'Keyed:Keyed:A', 'x')
        notes.set_note(project, 'Keyed:Keyed:A', '', flag='')
        self.assertEqual(project.notes, {})
        with self.assertRaises(ValueError):
            notes.set_note(project, 'Keyed:Keyed:Missing', 'x')
        with self.assertRaises(ValueError):
            notes.set_note(project, 'Keyed:Keyed:A', 'x', flag='bogus')

    def test_old_project_files_without_notes_still_load(self):
        project = make_project()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            project.save(path)
            data = json.loads(path.read_text(encoding='utf-8'))
            del data['notes'], data['assignments']
            path.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(Project.load(path).notes, {})

    def test_assignments_per_source_file(self):
        project = make_project()
        notes.assign_file(project, 'Keyed/Main.xml', 'Taro')
        self.assertEqual(notes.assignee(project, project.entries[0]), 'Taro')
        self.assertEqual(notes.assignee(project, project.entries[1]), '')
        self.assertEqual([e.id for e in notes.entries_for(project, 'Taro')], ['Keyed:Keyed:A'])
        notes.assign_file(project, 'Keyed/Main.xml', '')
        self.assertEqual(project.assignments, {})
        with self.assertRaises(ValueError):
            notes.assign_file(project, 'Nowhere.xml', 'Taro')


class CorruptProjectTests(unittest.TestCase):
    def test_corrupt_json_is_kept_aside_with_a_clear_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            path.write_text('{"schema": 1, "entries": [', encoding='utf-8')
            with self.assertRaises(ProjectFileError) as caught:
                Project.load(path)
            error = caught.exception
            self.assertFalse(path.exists())
            self.assertTrue(error.kept_at.is_file())
            self.assertIn('{"schema": 1', error.kept_at.read_text(encoding='utf-8'))
            self.assertIn(str(error.kept_at), str(error))
            self.assertIsInstance(error, ValueError)

    def test_a_readable_but_unsupported_project_is_left_in_place(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            path.write_text('{"schema": 99}', encoding='utf-8')
            with self.assertRaises(ValueError):
                Project.load(path)
            self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()

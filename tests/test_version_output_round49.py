"""Reject output names which alias on case-insensitive filesystems."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, Project, Scan, export_versions_test


class VersionOutputRound49Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.target = self.root / 'output'

    def project(self, resources):
        scans = {}
        for version in ('1.9', '1.10'):
            entries = [Entry(f'{kind}:{group}:{key}', kind, group, key, 'Hello', 'fixture')
                       for kind, group, key in resources]
            scans[version] = Scan(name='Aliases', package_id='test.aliases',
                                  versions=['1.9', '1.10'], entries=entries,
                                  stats={'active_version': version})
        project = Project.create_versions(self.source, scans)
        for version in project.versions:
            project.switch_version(version)
            for entry in project.entries:
                project.set_translation(entry.id, '訳文')
        return project

    @staticmethod
    def snapshot(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_keyed_case_aliases_rejected_before_new_tree_is_created(self):
        project = self.project([('Keyed', 'Main', 'First'), ('Keyed', 'main', 'Second')])
        with self.assertRaisesRegex(ValueError, 'case-insensitive'):
            export_versions_test(project, self.target)
        self.assertFalse(self.target.exists())

    def test_strings_aliases_preserve_previous_output_and_allow_retry(self):
        project = self.project([('Strings', 'Names/List.txt', 'line_0')])
        export_versions_test(project, self.target)
        before = self.snapshot(self.target)
        collision = self.project([('Strings', 'Names/List.txt', 'line_0'),
                                  ('Strings', 'Names/list.txt', 'line_0')])
        collision.package_id = project.package_id
        with self.assertRaisesRegex(ValueError, 'case-insensitive'):
            export_versions_test(collision, self.target)
        self.assertEqual(self.snapshot(self.target), before)
        export_versions_test(project, self.target)
        self.assertEqual(self.snapshot(self.target), before)

    def test_unowned_case_alias_is_preserved(self):
        project = self.project([('Strings', 'Names/List.txt', 'line_0')])
        export_versions_test(project, self.target)
        note = self.target / '1.10/Languages/Japanese/Strings/Names/Other.txt'
        note.write_bytes(b'user data')
        before = self.snapshot(self.target)
        collision = self.project([('Strings', 'Names/List.txt', 'line_0'),
                                  ('Strings', 'Names/other.txt', 'line_0')])
        collision.package_id = project.package_id
        with self.assertRaisesRegex(ValueError, 'case-insensitive'):
            export_versions_test(collision, self.target)
        self.assertEqual(self.snapshot(self.target), before)

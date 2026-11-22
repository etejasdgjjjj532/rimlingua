"""Chapter 5: before/after diff of an export, and the Workshop material template."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import export_diff, workshop
from rimworld_translator.core import Entry, Project, export_mod


def keyed(key, english, japanese=''):
    return Entry(f'Keyed:Keyed:{key}', 'Keyed', 'Keyed', key, english, 'Main.xml', japanese)


class Base(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'About/About.xml').write_text(
            '<ModMetaData><packageId>author.original</packageId><author>Orig Author</author></ModMetaData>')
        self.out = self.root / 'out'

    def project(self, entries):
        return Project(str(self.source), 'Example', 'local.translation.example', 'author.original', ['1.6'], entries, [])


class ExportDiffTests(Base):
    def test_first_export_adds_everything_and_writes_nothing(self):
        project = self.project([keyed('A', 'Alpha', 'あ')])
        diff = export_diff.export_diff(project, self.out)
        self.assertIn('Languages/Japanese/Keyed/Keyed.xml', [c.path for c in diff.added])
        self.assertEqual(diff.removed, [])
        self.assertFalse(self.out.exists())

    def test_changed_added_removed_keys_and_files(self):
        project = self.project([keyed('A', 'Alpha', 'あ'), keyed('B', 'Beta', 'べ')])
        export_mod(project, self.out)
        project.entries[0].japanese = 'あー'
        project.entries[1].japanese = ''
        project.entries.append(keyed('C', 'Gamma', 'が'))
        diff = export_diff.export_diff(project, self.out)
        change = next(c for c in diff.changed if c.path.endswith('Keyed/Keyed.xml'))
        self.assertEqual((change.keys_added, change.keys_removed, change.keys_changed), (['C'], ['B'], ['A']))
        self.assertEqual(diff.added, [])
        self.assertFalse(diff.empty)
        self.assertIn('1', diff.summary())

    def test_removed_file_and_unchanged_output(self):
        project = self.project([keyed('A', 'Alpha', 'あ')])
        export_mod(project, self.out)
        self.assertTrue(export_diff.export_diff(project, self.out).empty)
        project.entries[0].japanese = ''
        diff = export_diff.export_diff(project, self.out)
        self.assertEqual([c.path for c in diff.removed], ['Languages/Japanese/Keyed/Keyed.xml'])

    def test_blocked_export_raises_like_the_real_export(self):
        from rimworld_translator.core import ExportBlocked
        project = self.project([keyed('A', 'Hit {0}', '命中')])
        with self.assertRaises(ExportBlocked):
            export_diff.export_diff(project, self.out)

    def test_foreign_folder_is_refused(self):
        self.out.mkdir()
        (self.out / 'file.txt').write_text('x')
        with self.assertRaises(ValueError):
            export_diff.export_diff(self.project([keyed('A', 'Alpha', 'あ')]), self.out)


class WorkshopTests(Base):
    def test_material_mentions_original_languages_and_progress(self):
        project = self.project([keyed('A', 'Alpha', 'あ'), keyed('B', 'Beta')])
        (self.source / 'About/PublishedFileId.txt').write_text('1234567890')
        material = workshop.workshop_material(project, translator='Hanako')
        self.assertIn('Example', material.title)
        self.assertIn('https://steamcommunity.com/sharedfiles/filedetails/?id=1234567890', material.description)
        self.assertIn('Orig Author', material.description)
        self.assertIn('Hanako', material.description)
        self.assertIn('50', material.description)
        self.assertIn('Translation', material.tags)
        self.assertIn('Ludeon', material.description)

    def test_changelog_lists_diff_summary(self):
        project = self.project([keyed('A', 'Alpha', 'あ')])
        diff = export_diff.export_diff(project, self.out)
        material = workshop.workshop_material(project, diff=diff)
        self.assertIn('Languages/Japanese/Keyed/Keyed.xml', material.changelog)

    def test_write_material_creates_files_but_never_inside_the_source(self):
        project = self.project([keyed('A', 'Alpha', 'あ')])
        paths = workshop.write_workshop_material(project, self.root / 'workshop')
        self.assertTrue(all(p.is_file() for p in paths))
        self.assertEqual({p.name for p in paths}, {'title.txt', 'description.bbcode.txt', 'changelog.txt', 'checklist.txt'})
        with self.assertRaises(ValueError):
            workshop.write_workshop_material(project, self.source / 'workshop')


if __name__ == '__main__':
    unittest.main()

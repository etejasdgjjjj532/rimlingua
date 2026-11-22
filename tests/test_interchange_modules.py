"""Chapter 8: matching another translation MOD against the project, and the single-file project bundle."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from rimworld_translator import interchange, notes
from rimworld_translator.core import Entry, Project, export_mod


def keyed(key, english, japanese=''):
    return Entry(f'Keyed:Keyed:{key}', 'Keyed', 'Keyed', key, english, 'Keyed/Main.xml', japanese)


class Base(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'About/About.xml').write_text('<ModMetaData><packageId>author.original</packageId></ModMetaData>')
        (self.root / 'bundles').mkdir()

    def project(self, entries):
        return Project(str(self.source), 'Example', 'local.translation.example', 'author.original', ['1.6'], entries, [])


class OtherModTests(Base):
    def make_mod(self):
        mod = self.root / 'theirs'
        (mod / 'About').mkdir(parents=True, exist_ok=True)
        (mod / 'About/About.xml').write_text('<ModMetaData><name>Their JP</name><author>Someone</author>'
                                             '<packageId>someone.example.jp</packageId></ModMetaData>', encoding='utf-8')
        (mod / 'Languages/Japanese/Keyed').mkdir(parents=True, exist_ok=True)
        (mod / 'Languages/Japanese/Keyed/Main.xml').write_text(
            '<?xml version="1.0" encoding="utf-8"?><LanguageData><A>あ</A><B>べ違い</B><C>し</C><Gone>ご</Gone></LanguageData>',
            encoding='utf-8')
        return mod

    def test_match_classifies_rows(self):
        project = self.project([keyed('A', 'Alpha'), keyed('B', 'Beta', 'べ'), keyed('C', 'Gamma', 'し'), keyed('D', 'Delta')])
        match = interchange.match_translation_mod(project, self.make_mod())
        self.assertEqual(match.new, ['Keyed:Keyed:A'])
        self.assertEqual([item[0] for item in match.different], ['Keyed:Keyed:B'])
        self.assertEqual(match.same, ['Keyed:Keyed:C'])
        self.assertEqual(match.unknown, ['Keyed:Keyed:Gone'])
        self.assertEqual(match.missing, ['Keyed:Keyed:D'])
        self.assertEqual(match.about['name'], 'Their JP')
        self.assertEqual(match.about['author'], 'Someone')
        self.assertAlmostEqual(match.coverage, 3 / 4)
        self.assertIn('ライセンス', match.license_note)

    def test_import_marks_rows_for_review_and_credits_the_source(self):
        project = self.project([keyed('A', 'Alpha'), keyed('B', 'Beta', 'べ')])
        preview = interchange.preview_import_mod(project, self.make_mod())
        self.assertEqual([(c.id, c.review) for c in preview.changes], [('Keyed:Keyed:A', True)])
        self.assertEqual(len(preview.conflicts), 1)
        with_overwrite = interchange.preview_import_mod(project, self.make_mod(), overwrite=True)
        self.assertEqual({c.id for c in with_overwrite.changes}, {'Keyed:Keyed:A', 'Keyed:Keyed:B'})

    def test_a_folder_that_is_not_a_translation_mod_is_refused(self):
        empty = self.root / 'empty'
        empty.mkdir()
        with self.assertRaises(ValueError):
            interchange.match_translation_mod(self.project([keyed('A', 'Alpha')]), empty)


class BundleTests(Base):
    def test_round_trip_keeps_translations_notes_and_assignments(self):
        project = self.project([keyed('A', 'Alpha', 'あ'), keyed('B', 'Beta')])
        notes.set_note(project, 'Keyed:Keyed:B', 'あとで', 'later')
        notes.assign_file(project, 'Keyed/Main.xml', 'Hanako')
        bundle = self.root / 'bundles/share.rwtbundle'
        interchange.export_bundle(project, bundle)
        names = zipfile.ZipFile(bundle).namelist()
        self.assertEqual(sorted(names), ['bundle.json', 'project.json'])
        self.assertNotIn(str(self.source), zipfile.ZipFile(bundle).read('project.json').decode('utf-8'))
        destination = self.root / 'received'
        path = interchange.import_bundle(bundle, destination, self.source)
        loaded = Project.load(path)
        self.assertEqual(loaded.source, str(self.source.resolve()))
        self.assertEqual(loaded.entries[0].japanese, 'あ')
        self.assertEqual(loaded.notes['Keyed:Keyed:B']['flag'], 'later')
        self.assertEqual(loaded.assignments, {'Keyed/Main.xml': 'Hanako'})

    def test_inspect_reads_the_manifest(self):
        project = self.project([keyed('A', 'Alpha', 'あ')])
        bundle = self.root / 'bundles/share.rwtbundle'
        interchange.export_bundle(project, bundle)
        info = interchange.inspect_bundle(bundle)
        self.assertEqual((info.name, info.original_package_id, info.entries, info.translated), ('Example', 'author.original', 1, 1))

    def test_import_requires_the_matching_source_mod(self):
        project = self.project([keyed('A', 'Alpha')])
        bundle = self.root / 'bundles/share.rwtbundle'
        interchange.export_bundle(project, bundle)
        other = self.root / 'other'
        (other / 'About').mkdir(parents=True)
        (other / 'About/About.xml').write_text('<ModMetaData><packageId>someone.else</packageId></ModMetaData>')
        with self.assertRaisesRegex(ValueError, 'someone.else'):
            interchange.import_bundle(bundle, self.root / 'received', other)
        with self.assertRaises(ValueError):
            interchange.import_bundle(bundle, self.root / 'received', self.root / 'missing')

    def test_existing_project_is_not_overwritten(self):
        project = self.project([keyed('A', 'Alpha')])
        bundle = self.root / 'bundles/share.rwtbundle'
        interchange.export_bundle(project, bundle)
        interchange.import_bundle(bundle, self.root / 'received', self.source)
        with self.assertRaises(ValueError):
            interchange.import_bundle(bundle, self.root / 'received', self.source)
        interchange.import_bundle(bundle, self.root / 'received', self.source, overwrite=True)

    def test_include_output_and_unsafe_archives(self):
        project = self.project([keyed('A', 'Alpha', 'あ')])
        export_mod(project, self.root / 'mod')
        bundle = self.root / 'bundles/share.rwtbundle'
        interchange.export_bundle(project, bundle, output_folder=self.root / 'mod')
        self.assertIn('mod/About/About.xml', zipfile.ZipFile(bundle).namelist())
        path = interchange.import_bundle(bundle, self.root / 'received', self.source)
        self.assertTrue((path.parent / 'mod/About/About.xml').is_file())
        evil = self.root / 'bundles/evil.rwtbundle'
        with zipfile.ZipFile(evil, 'w') as archive:
            archive.writestr('bundle.json', '{"schema": 1}')
            archive.writestr('project.json', zipfile.ZipFile(bundle).read('project.json'))
            archive.writestr('mod/../../escape.txt', 'x')
        with self.assertRaises(ValueError):
            interchange.import_bundle(evil, self.root / 'received2', self.source)
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_not_a_bundle(self):
        junk = self.root / 'bundles/junk.rwtbundle'
        junk.write_text('not a zip')
        with self.assertRaisesRegex(ValueError, 'バンドル'):
            interchange.inspect_bundle(junk)


if __name__ == '__main__':
    unittest.main()

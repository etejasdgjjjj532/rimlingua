"""Keep XML output paths portable and preserve prior output on rejection."""
import json
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, Project, Scan, export_mod, export_versions_test


class VersionOutputRound50Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.target = self.root / 'output'

    def project(self, kind='Keyed', group='Messages'):
        scans = {version: Scan(name='Portable output', package_id='test.portable',
                 versions=['1.9', '1.10'], stats={'active_version': version},
                 entries=[Entry(f'{kind}:{group}:Greeting', kind, group, 'Greeting',
                                'Hello', 'fixture.xml')]) for version in ['1.9', '1.10']}
        project = Project.create_versions(self.source, scans)
        for version in project.versions:
            project.switch_version(version)
            project.set_translation(project.entries[0].id, '訳文 ' + version)
        return project

    def snapshot(self):
        return {str(p.relative_to(self.target)): p.read_bytes()
                for p in self.target.rglob('*') if p.is_file()}

    def test_reserved_keyed_filename_rejected_before_creating_output(self):
        for name in ('CON', 'aux', 'COM1', 'Lpt9.data'):
            with self.subTest(name=name):
                project = self.project(group=name)
                target = self.root / ('output-' + name)
                with self.assertRaisesRegex(ValueError, 'portable'):
                    export_versions_test(project, target)
                self.assertFalse(target.exists())

    def test_reserved_def_directory_preserves_existing_output_and_allows_retry(self):
        project = self.project()
        export_versions_test(project, self.target)
        note = self.target / 'user-note.txt'
        note.write_bytes(b'user data')
        before = self.snapshot()
        for group in ('NUL', 'COM1', 'ThingDef.'):
            with self.subTest(group=group):
                invalid = self.project(kind='DefInjected', group=group)
                invalid.package_id = project.package_id
                with self.assertRaisesRegex(ValueError, 'portable'):
                    export_versions_test(invalid, self.target)
                self.assertEqual(self.snapshot(), before)
        export_versions_test(project, self.target)
        self.assertEqual(self.snapshot(), before)

    def test_obsolete_reserved_path_is_preserved_before_manifest_cleanup(self):
        project = self.project()
        export_versions_test(project, self.target)
        # A stale manifest entry must also be rejected before cleanup starts.
        obsolete = '1.9/Languages/Japanese/DefInjected/CON/Translations.xml'
        marker = self.target / '.rimworld-translator.json'
        metadata = json.loads(marker.read_text())
        metadata['files'].append(obsolete)
        marker.write_text(json.dumps(metadata))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'portable'):
            export_versions_test(project, self.target)
        self.assertEqual(self.snapshot(), before)

    def test_similar_portable_names_work_for_legacy_and_version_output(self):
        project = self.project(group='CONsole')
        export_versions_test(project, self.target)
        self.assertTrue((self.target / '1.10/Languages/Japanese/Keyed/CONsole.xml').is_file())
        legacy = project._version_view('1.9')
        export_mod(legacy, self.root / 'legacy')
        self.assertTrue((self.root / 'legacy/Languages/Japanese/Keyed/CONsole.xml').is_file())

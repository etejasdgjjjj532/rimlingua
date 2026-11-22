"""Validate version provenance before migration and profile restoration."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, Project, Scan, scan_mod


GREETING = 'Keyed:Keyed:Greeting'


class VersionOutputRound17Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        about = self.source / 'About'
        about.mkdir()
        (about / 'About.xml').write_text(
            '<ModMetaData><name>Version provenance</name>'
            '<packageId>test.versionprovenance</packageId><supportedVersions>'
            '<li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>',
            encoding='utf-8')
        for version in ('1.3', '1.6', '1.10'):
            keyed = self.source / version / 'Languages/English/Keyed'
            keyed.mkdir(parents=True)
            (keyed / 'messages.xml').write_text(
                f'<LanguageData><Greeting>hello {version}</Greeting></LanguageData>',
                encoding='utf-8')
        self.saved = self.root / 'workspace/project.json'

    def scan(self, version, declared=('1.6', '1.10')):
        return Scan(name='Version provenance', package_id='test.versionprovenance',
                    versions=list(declared), stats={'active_version': version},
                    entries=[Entry(GREETING, 'Keyed', 'Keyed', 'Greeting',
                                   f'hello {version}', 'messages.xml')])

    def test_migration_rejects_undeclared_legacy_version_without_losing_saved_work(self):
        # A legacy selected branch can be outside About.xml's declarations.
        # It must remain recoverable, never become an undeclared schema-2 profile.
        legacy = Project.create(self.source, scan_mod(self.source, game_version='1.3'))
        legacy.set_translation(GREETING, '宣言外の旧版で保存した訳')
        legacy.mark_reviewed(GREETING, approved=True)
        legacy.save(self.saved)
        legacy = Project.load(self.saved)
        before = copy.deepcopy(legacy)
        saved_before = self.saved.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Current version is not declared'):
            legacy.add_version_scan('1.6', scan_mod(self.source, game_version='1.6'))
        self.assertEqual(legacy, before)
        self.assertEqual(self.saved.read_bytes(), saved_before)
        legacy.save(self.saved)
        restored = Project.load(self.saved)
        self.assertEqual(restored.get_translation(GREETING), '宣言外の旧版で保存した訳')
        self.assertTrue(restored.entry_index()[GREETING].approved)
        self.assertEqual(restored.schema, 1)

    def test_restore_rejects_profile_with_another_versions_scan_identity(self):
        project = Project.create_versions(self.source, {
            version: self.scan(version) for version in ('1.6', '1.10')})
        project.save(self.saved)
        original = json.loads(self.saved.read_text(encoding='utf-8'))
        for identity in ('1.6', None, 1.10):
            with self.subTest(identity=identity):
                data = copy.deepcopy(original)
                data['version_profiles']['1.10']['stats']['active_version'] = identity
                self.saved.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'profile scan version'):
                    Project.load(self.saved)


if __name__ == '__main__':
    unittest.main()

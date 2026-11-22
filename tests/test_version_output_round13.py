"""Extend declared version coverage without sharing or deleting previous work."""
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_versions_test, scan_mod
from rimworld_translator.multiversion import scan_declared_versions


class VersionOutputRound13Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.declare(('1.3', '1.6'))
        for version in ('1.3', '1.6', '1.9', '1.10'):
            self.write(f'{version}/Languages/English/Keyed/messages.xml',
                       f'<LanguageData><Greeting>hello {version}</Greeting>'
                       f'<Only{version.replace(".", "_")}>local {version}</Only{version.replace(".", "_")}>'
                       '</LanguageData>')
        scans = scan_declared_versions(self.source)
        self.project = Project.create_versions(self.source, scans.scans)
        for version in ('1.3', '1.6'):
            self.project.switch_version(version)
            self.project.set_translation('Keyed:Keyed:Greeting', f'独立訳 {version}')
            self.project.mark_reviewed('Keyed:Keyed:Greeting', approved=True)
        self.saved = self.root / 'workspace/project.json'
        self.project.save(self.saved)
        self.project = Project.load(self.saved)

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def declare(self, versions):
        self.write('About/About.xml', '<ModMetaData><name>Version extension</name>'
                   '<packageId>test.versionextension</packageId><supportedVersions>'
                   + ''.join(f'<li>{version}</li>' for version in reversed(versions))
                   + '</supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders>'
                   + ''.join(f'<v{version}><li>{version}</li></v{version}>' for version in versions)
                   + '</loadFolders>')

    @staticmethod
    def files(root):
        return {str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    def test_explicit_extension_keeps_existing_history_and_requires_each_new_scan(self):
        self.declare(('1.3', '1.6', '1.9', '1.10'))
        source_before = self.files(self.source)
        scan = scan_mod(self.source, game_version='1.10')
        previous_profiles = copy.deepcopy(self.project.version_profiles)
        self.project.add_version_scan('1.10', scan, extend_declared_versions=True)
        self.assertEqual(self.project.versions, ['1.3', '1.6', '1.9', '1.10'])
        for version in ('1.3', '1.6'):
            self.assertEqual(self.project.version_profiles[version], previous_profiles[version])
        self.assertEqual(self.project.get_translation('Keyed:Keyed:Greeting'), '')
        self.assertFalse(self.project.entry_index()['Keyed:Keyed:Greeting'].approved)
        self.assertNotIn('1.9', self.project.version_profiles)
        target = self.root / 'output'
        # An unscanned declared version is held with a notice, like the formal exporter (2026-11-20).
        partial = self.root / 'partial-output'
        held = export_versions_test(self.project, partial)
        self.assertTrue(any('1.9' in warning and '保留' in warning for warning in held))
        self.assertFalse((partial / '1.9').exists())
        self.assertFalse(target.exists())
        self.project.add_version_scan('1.9', scan_mod(self.source, game_version='1.9'))
        for version in ('1.9', '1.10'):
            self.project.switch_version(version)
            self.project.set_translation('Keyed:Keyed:Greeting', f'新規訳 {version}')
        self.project.save(self.saved)
        restored = Project.load(self.saved)
        warnings = export_versions_test(restored, target)
        self.assertTrue(any('未検証' in warning for warning in warnings))
        for version, expected in (('1.3', '独立訳 1.3'), ('1.6', '独立訳 1.6'),
                                  ('1.9', '新規訳 1.9'), ('1.10', '新規訳 1.10')):
            restored.switch_version(version)
            self.assertEqual(restored.get_translation('Keyed:Keyed:Greeting'), expected)
            self.assertEqual(restored.entry_index()['Keyed:Keyed:Greeting'].approved,
                             version in ('1.3', '1.6'))
            self.assertEqual(restored.entry_index()['Keyed:Keyed:Greeting'].english, f'hello {version}')
            xml = ET.parse(target / version / 'Languages/Japanese/Keyed/Keyed.xml').getroot()
            self.assertEqual({node.tag: node.text for node in xml}, {'Greeting': expected})
            self.assertEqual(restored.version_profiles[version]['coverage'], {
                'extracted': True, 'source_verified': False, 'game_tested': False})
        self.assertEqual([node.text for node in ET.parse(target / 'About/About.xml')
                          .getroot().findall('supportedVersions/li')], ['1.3', '1.6', '1.9', '1.10'])
        self.assertEqual([(node.tag, node.findtext('li')) for node in
                          ET.parse(target / 'LoadFolders.xml').getroot()],
                         [('v1.3', '1.3'), ('v1.6', '1.6'), ('v1.9', '1.9'), ('v1.10', '1.10')])
        self.assertEqual(self.files(self.source), source_before)

    def test_default_rejects_new_declarations_without_modifying_existing_project(self):
        self.declare(('1.3', '1.6', '1.10'))
        before = copy.deepcopy(self.project)
        with self.assertRaises(ValueError):
            self.project.add_version_scan('1.10', scan_mod(self.source, game_version='1.10'))
        self.assertEqual(self.project, before)

    def test_explicit_extension_rejects_removed_versions_or_wrong_source_without_mutation(self):
        for versions, wrong_source in ((('1.6', '1.10'), False),
                                       (('1.3', '1.6', '1.10'), True)):
            with self.subTest(versions=versions, wrong_source=wrong_source):
                self.declare(versions)
                scan = scan_mod(self.source, game_version='1.10')
                if wrong_source:
                    scan.package_id = 'test.differentmod'
                before = copy.deepcopy(self.project)
                with self.assertRaises(ValueError):
                    self.project.add_version_scan('1.10', scan, extend_declared_versions=True)
                self.assertEqual(self.project, before)

    def test_schema1_extension_preserves_old_work_and_migrates_on_save(self):
        self.declare(('1.6',))
        legacy = Project.create(self.source, scan_mod(self.source, game_version='1.6'))
        legacy.set_translation('Keyed:Keyed:Greeting', '従来版の承認訳')
        legacy.mark_reviewed('Keyed:Keyed:Greeting', approved=True)
        legacy.save(self.saved)
        legacy = Project.load(self.saved)
        self.assertEqual(legacy.schema, 1)
        self.assertEqual(legacy.version_profiles, {})
        self.declare(('1.6', '1.10'))
        legacy.add_version_scan('1.10', scan_mod(self.source, game_version='1.10'),
                                extend_declared_versions=True)
        self.assertEqual(legacy.get_translation('Keyed:Keyed:Greeting'), '')
        legacy.save(self.saved)
        restored = Project.load(self.saved)
        self.assertEqual(restored.schema, 2)
        restored.switch_version('1.6')
        self.assertEqual(restored.get_translation('Keyed:Keyed:Greeting'), '従来版の承認訳')
        self.assertTrue(restored.entry_index()['Keyed:Keyed:Greeting'].approved)
        target = self.root / 'migrated'
        export_versions_test(restored, target)
        self.assertEqual(ET.parse(target / '1.6/Languages/Japanese/Keyed/Keyed.xml')
                         .getroot().findtext('Greeting'), '従来版の承認訳')
        self.assertFalse((target / '1.10/Languages/Japanese/Keyed/Keyed.xml').exists())

    def test_extension_flag_requires_bool_and_cannot_refresh_an_existing_version(self):
        self.declare(('1.3', '1.6', '1.10'))
        scan = scan_mod(self.source, game_version='1.10')
        for flag in (1, 'true', None):
            with self.subTest(flag=flag):
                before = copy.deepcopy(self.project)
                with self.assertRaises(ValueError):
                    self.project.add_version_scan('1.10', scan, extend_declared_versions=flag)
                self.assertEqual(self.project, before)
        before = copy.deepcopy(self.project)
        with self.assertRaises(ValueError):
            self.project.add_version_scan('1.6', scan_mod(self.source, game_version='1.6'),
                                          extend_declared_versions=True)
        self.assertEqual(self.project, before)


if __name__ == '__main__':
    unittest.main()

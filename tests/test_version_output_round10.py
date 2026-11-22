"""Exercise persisted version history against exact, version-specific XML oracles."""
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_mod, export_versions_test, scan_mod
from rimworld_translator.multiversion import scan_declared_versions


VERSIONS = ('1.3', '1.4', '1.5', '1.6', '1.9', '1.10')
LABEL = 'DefInjected:ThingDef:Item.label'
DESCRIPTION = 'DefInjected:ThingDef:Item.description'
GREETING = 'Keyed:Keyed:Greeting'
RETIRED = 'Keyed:Keyed:Retired'
ADDED = 'Keyed:Keyed:Added'


class VersionOutputRound10Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Version history</name>'
                   '<packageId>test.versionhistory</packageId><supportedVersions>'
                   + ''.join(f'<li>{version}</li>' for version in reversed(VERSIONS))
                   + '</supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders>'
                   + ''.join(f'<v{version}><li>{version}</li></v{version}>' for version in VERSIONS)
                   + '</loadFolders>')
        for version in VERSIONS:
            self.write(f'{version}/Defs/items.xml', '<Defs>'
                       '<ThingDef Name="LocalParent" Abstract="True">'
                       f'<description>inherited {version}</description></ThingDef>'
                       '<ThingDef ParentName="LocalParent"><defName>Item</defName>'
                       f'<label>item {version}</label></ThingDef></Defs>')
            self.write_keyed(version)
        scans = scan_declared_versions(self.source)
        self.assertEqual(scans.failures, {})
        self.assertEqual(scans.declared_versions, list(VERSIONS))
        for version, scan in scans.scans.items():
            self.assertEqual({entry.id: entry.english for entry in scan.entries}, {
                LABEL: f'item {version}', DESCRIPTION: f'inherited {version}',
                GREETING: f'hello {version}', RETIRED: f'retired {version}'})
        self.project = Project.create_versions(self.source, scans.scans)
        for version in VERSIONS:
            self.project.switch_version(version)
            for entry_id in (LABEL, DESCRIPTION, GREETING, RETIRED):
                self.project.set_translation(entry_id, self.translation(version, entry_id))
                self.project.mark_reviewed(entry_id, approved=True)
        self.saved = self.root / 'workspace/project.json'
        self.project.save(self.saved)
        self.project = Project.load(self.saved)

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def write_keyed(self, version, refreshed=False):
        greeting = f'changed hello {version}' if refreshed else f'hello {version}'
        extra = (f'<Added>added {version}</Added>' if refreshed
                 else f'<Retired>retired {version}</Retired>')
        self.write(f'{version}/Languages/English/Keyed/messages.xml',
                   f'<LanguageData><Greeting>{greeting}</Greeting>{extra}</LanguageData>')

    @staticmethod
    def translation(version, entry_id):
        return f'独立訳 {version} {entry_id.rsplit(":", 1)[1]}'

    @staticmethod
    def files(root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    @staticmethod
    def xml_map(path):
        return {node.tag: node.text for node in ET.parse(path).getroot()}

    def test_refresh_one_inactive_version_retains_history_and_other_versions_approvals(self):
        self.project.switch_version('1.10')
        self.write_keyed('1.3', refreshed=True)
        source_before = self.files(self.source)
        refreshed = scan_mod(self.source, game_version='1.3')
        self.project.add_version_scan('1.3', refreshed)
        self.project.set_translation(ADDED, '旧版だけに追加した訳')
        self.project.switch_version('1.10')
        self.project.save(self.saved)
        restored = Project.load(self.saved)
        target = self.root / 'output'
        warnings = export_versions_test(restored, target)
        self.assertTrue(any('未検証' in warning for warning in warnings))
        self.assertTrue(any('1.3' in warning and 'Greeting' in warning for warning in warnings))
        self.assertEqual(restored.game_version, '1.10')
        for version in VERSIONS:
            restored.switch_version(version)
            index = restored.entry_index()
            self.assertEqual(index[GREETING].english,
                             'changed hello 1.3' if version == '1.3' else f'hello {version}')
            self.assertEqual(index[GREETING].japanese, self.translation(version, GREETING))
            self.assertEqual(index[GREETING].approved, version != '1.3')
            self.assertEqual(index[GREETING].changed, version == '1.3')
            self.assertEqual(index[GREETING].previous_english,
                             'hello 1.3' if version == '1.3' else '')
            self.assertEqual(index[RETIRED].japanese, self.translation(version, RETIRED))
            self.assertEqual(index[RETIRED].stale, version == '1.3')
            self.assertEqual(ADDED in index, version == '1.3')
            expected_keyed = {'Greeting': self.translation(version, GREETING)}
            expected_keyed.update({'Added': '旧版だけに追加した訳'} if version == '1.3'
                                  else {'Retired': self.translation(version, RETIRED)})
            self.assertEqual(self.xml_map(target / version / 'Languages/Japanese/Keyed/Keyed.xml'),
                             expected_keyed)
            self.assertEqual(self.xml_map(target / version /
                                         'Languages/Japanese/DefInjected/ThingDef/Translations.xml'), {
                'Item.label': self.translation(version, LABEL),
                'Item.description': self.translation(version, DESCRIPTION)})
            self.assertEqual(restored.version_profiles[version]['coverage'], {
                'extracted': True, 'source_verified': False, 'game_tested': False})
        self.assertEqual(self.files(self.source), source_before)
        self.assertEqual([node.text for node in ET.parse(target / 'About/About.xml')
                          .getroot().findall('supportedVersions/li')], list(VERSIONS))
        self.assertEqual([(node.tag, node.findtext('li')) for node in
                          ET.parse(target / 'LoadFolders.xml').getroot()],
                         [(f'v{version}', version) for version in VERSIONS])
        marker = json.loads((target / '.rimworld-translator.json').read_text())
        self.assertTrue(marker['test_only'])
        self.assertEqual(marker['unverified_versions'], list(VERSIONS))

    def test_clearing_one_persisted_version_removes_only_its_owned_keyed_file(self):
        target = self.root / 'output'
        export_versions_test(self.project, target)
        before = self.files(target)
        custom = target / '1.3/Languages/Japanese/Keyed/user-notes.txt'
        custom.write_bytes(b'preserve user notes')
        self.project.switch_version('1.3')
        for entry_id in (GREETING, RETIRED):
            self.project.set_translation(entry_id, '')
        self.project.switch_version('1.10')
        self.project.save(self.saved)
        restored = Project.load(self.saved)
        export_versions_test(restored, target)
        removed = '1.3/Languages/Japanese/Keyed/Keyed.xml'
        after = self.files(target)
        self.assertNotIn(removed, after)
        for relative, data in before.items():
            if relative not in {removed, '.rimworld-translator.json'}:
                self.assertEqual(after[relative], data, relative)
        self.assertEqual(custom.read_bytes(), b'preserve user notes')
        restored.switch_version('1.3')
        self.assertEqual(restored.get_translation(GREETING), '')
        self.assertFalse(restored.entry_index()[GREETING].approved)
        restored.switch_version('1.4')
        self.assertEqual(restored.get_translation(GREETING), self.translation('1.4', GREETING))
        self.assertTrue(restored.entry_index()[GREETING].approved)
        manifest = json.loads((target / '.rimworld-translator.json').read_text())
        self.assertNotIn(removed, manifest['files'])
        self.assertNotIn(custom.relative_to(target).as_posix(), manifest['files'])

    def test_legacy_schema1_keeps_only_its_scanned_version_in_output(self):
        legacy = Project.create(self.source, scan_mod(self.source, game_version='1.4'))
        legacy.set_translation(GREETING, '従来の単一版訳')
        legacy.mark_reviewed(GREETING, approved=True)
        legacy.save(self.saved)
        restored = Project.load(self.saved)
        self.assertEqual(restored.schema, 1)
        self.assertEqual(restored.version_profiles, {})
        self.assertEqual(restored.get_translation(GREETING), '従来の単一版訳')
        self.assertTrue(restored.entry_index()[GREETING].approved)
        target = self.root / 'legacy'
        export_mod(restored, target)
        self.assertEqual(self.xml_map(target / 'Languages/Japanese/Keyed/Keyed.xml'),
                         {'Greeting': '従来の単一版訳'})
        about = ET.parse(target / 'About/About.xml').getroot()
        self.assertEqual([node.text for node in about.findall('supportedVersions/li')], ['1.4'])
        self.assertFalse((target / 'LoadFolders.xml').exists())
        self.assertFalse(any((target / version).exists() for version in VERSIONS))


if __name__ == '__main__':
    unittest.main()

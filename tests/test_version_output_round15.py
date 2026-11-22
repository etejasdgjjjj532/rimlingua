"""Independent six-version history and safe repeated test-output regressions."""
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_mod, export_versions_test, scan_mod
from rimworld_translator.multiversion import scan_declared_versions


VERSIONS = ('1.1', '1.2', '1.3', '1.4', '1.5', '1.6')
GREETING = 'Keyed:Keyed:Greeting'
LABEL = 'DefInjected:ThingDef:Item.label'


class VersionOutputRound15Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.declare(VERSIONS)
        for version in VERSIONS:
            self.write(f'{version}/Languages/English/Keyed/messages.xml',
                       f'<LanguageData><Greeting>hello {version} {{0}}</Greeting></LanguageData>')
            self.write(f'{version}/Defs/items.xml',
                       '<Defs><ThingDef><defName>Item</defName>'
                       f'<label>item {version}</label></ThingDef></Defs>')
        scans = scan_declared_versions(self.source)
        self.assertEqual(scans.failures, {})
        self.project = Project.create_versions(self.source, scans.scans)
        for version in VERSIONS:
            self.project.switch_version(version)
            self.project.set_translation(GREETING, f'挨拶 {version} {{0}}')
            self.project.mark_reviewed(GREETING, approved=True)
            self.project.set_translation(LABEL, f'品物 {version}')
            self.project.mark_reviewed(LABEL, approved=True)

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def declare(self, versions):
        self.write('About/About.xml', '<ModMetaData><name>Round 15 versions</name>'
                   '<packageId>test.round15versions</packageId><supportedVersions>'
                   + ''.join(f'<li>{version}</li>' for version in versions)
                   + '</supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders>'
                   + ''.join(f'<v{version}><li>{version}</li></v{version}>' for version in versions)
                   + '</loadFolders>')

    def restore(self):
        saved = self.root / 'workspace/project.json'
        self.project.save(saved)
        self.project = Project.load(saved)

    @staticmethod
    def files(root):
        return {str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    def test_removed_key_history_and_revival_remain_local_after_restore(self):
        self.write('1.3/Languages/English/Keyed/messages.xml', '<LanguageData/>')
        self.project.add_version_scan('1.3', scan_mod(self.source, game_version='1.3'))
        self.restore()
        output = self.root / 'removed-output'
        export_versions_test(self.project, output)
        for version in VERSIONS:
            self.project.switch_version(version)
            entry = self.project.entry_index()[GREETING]
            self.assertEqual(entry.japanese, f'挨拶 {version} {{0}}')
            self.assertEqual(entry.stale, version == '1.3')
            self.assertEqual((output / version / 'Languages/Japanese/Keyed/Keyed.xml').exists(),
                             version != '1.3')
        self.write('1.3/Languages/English/Keyed/messages.xml',
                   '<LanguageData><Greeting>revised old greeting {0}</Greeting></LanguageData>')
        self.project.add_version_scan('1.3', scan_mod(self.source, game_version='1.3'))
        self.restore()
        revived = self.project.entry_index()[GREETING]
        self.assertFalse(revived.stale)
        self.assertTrue(revived.changed)
        self.assertFalse(revived.approved)
        self.assertEqual(revived.japanese, '挨拶 1.3 {0}')
        warnings = export_versions_test(self.project, output)
        self.assertTrue(any('1.3' in warning and 'Review needed' in warning for warning in warnings))
        for version in VERSIONS:
            self.project.switch_version(version)
            self.assertEqual(self.project.entry_index()[GREETING].approved, version != '1.3')
            self.assertEqual(ET.parse(output / version / 'Languages/Japanese/Keyed/Keyed.xml')
                             .getroot().findtext('Greeting'), f'挨拶 {version} {{0}}')

    def test_safe_reexport_removes_newly_dangerous_branch_file_and_keeps_other_versions(self):
        output = self.root / 'repeat-output'
        export_versions_test(self.project, output)
        keep = output / 'user-notes.txt'
        keep.write_text('retain user content', encoding='utf-8')
        before = self.files(output)
        self.project.switch_version('1.4')
        self.project.set_translation(GREETING, '欠けたプレースホルダー')
        self.restore()
        source_before = self.files(self.source)
        warnings = export_versions_test(self.project, output)
        self.assertTrue(any('1.4' in warning and '危険な訳' in warning for warning in warnings))
        self.assertFalse((output / '1.4/Languages/Japanese/Keyed/Keyed.xml').exists())
        after = self.files(output)
        for relative, content in before.items():
            if relative not in {'.rimworld-translator.json',
                                 '1.4/Languages/Japanese/Keyed/Keyed.xml'}:
                self.assertEqual(after[relative], content, relative)
        self.assertEqual(self.files(self.source), source_before)
        with self.assertRaisesRegex(ValueError, 'formal multi-version output'):
            export_mod(self.project, output)
        self.assertEqual(self.files(output), after)

    def test_explicit_future_addition_after_six_versions_has_no_inherited_text_or_approval(self):
        self.restore()
        self.declare((*VERSIONS, '1.10'))
        self.write('1.10/Languages/English/Keyed/messages.xml',
                   '<LanguageData><Greeting>future greeting {0}</Greeting></LanguageData>')
        snapshots = copy.deepcopy(self.project.version_profiles)
        self.project.add_version_scan('1.10', scan_mod(self.source, game_version='1.10'),
                                      extend_declared_versions=True)
        self.assertEqual(self.project.get_translation(GREETING), '')
        self.assertFalse(self.project.entry_index()[GREETING].approved)
        for version in VERSIONS:
            self.assertEqual(self.project.version_profiles[version], snapshots[version])
        self.project.set_translation(GREETING, '将来版 {0}')
        self.restore()
        output = self.root / 'future-output'
        export_versions_test(self.project, output)
        for version in (*VERSIONS, '1.10'):
            self.project.switch_version(version)
            expected = '将来版 {0}' if version == '1.10' else f'挨拶 {version} {{0}}'
            self.assertEqual(self.project.get_translation(GREETING), expected)
            self.assertEqual(self.project.entry_index()[GREETING].approved, version != '1.10')
            self.assertEqual(ET.parse(output / version / 'Languages/Japanese/Keyed/Keyed.xml')
                             .getroot().findtext('Greeting'), expected)
        self.assertEqual([node.text for node in ET.parse(output / 'About/About.xml')
                          .getroot().findall('supportedVersions/li')], [*VERSIONS, '1.10'])


if __name__ == '__main__':
    unittest.main()

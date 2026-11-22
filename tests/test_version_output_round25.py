"""Keep unknown-field evidence and reappearing Strings review state version-local."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_versions_test, scan_mod
from rimworld_translator.schema import FieldSpec, TypeSpec, TranslationSchema


GREETING = 'Keyed:Keyed:Greeting'


class VersionOutputRound25Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Version isolation</name>'
                   '<packageId>test.versionisolation</packageId><supportedVersions>'
                   '<li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6>'
                   '<v1.10><li>1.10</li></v1.10></loadFolders>')
        self.write('1.6/Languages/English/Keyed/messages.xml',
                   '<LanguageData><Greeting>Old greeting</Greeting></LanguageData>')
        self.write('1.10/Languages/English/Keyed/messages.xml',
                   '<LanguageData><Greeting>Future greeting</Greeting></LanguageData>')
        self.project = Project.create(self.source, scan_mod(self.source, game_version='1.6'))
        self.project.set_translation(GREETING, '旧版の承認済み訳')
        self.project.mark_reviewed(GREETING, approved=True)

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_unknown_xml_evidence_stays_in_its_version_diagnostics_after_save_and_export(self):
        # Fixture schema confirms label only; tooltipText remains diagnostic-only.
        schema = TranslationSchema({'ThingDef': TypeSpec('ThingDef', fields={
            'defName': FieldSpec('System.String', attributes=('NoTranslateAttribute',)),
            'label': FieldSpec('System.String', attributes=('MustTranslateAttribute',))})})
        self.write('1.6/Defs/item.xml', '<Defs><ThingDef><defName>Item</defName>'
                   '<label>Known label</label><tooltipText>Move faster</tooltipText>'
                   '</ThingDef></Defs>')
        scans = {version: scan_mod(self.source, game_version=version, schema=schema)
                 for version in ('1.6', '1.10')}
        self.assertEqual({entry.key for entry in scans['1.6'].entries},
                         {'Greeting', 'Item.label'})
        unknown = [item for item in scans['1.6'].diagnostics if item['code'] == 'unknown-field']
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]['source_file'], '1.6/Defs/item.xml')
        self.assertIn('Item.tooltipText', unknown[0]['message'])
        self.assertEqual([item for item in scans['1.10'].diagnostics
                          if item['code'] == 'unknown-field'], [])
        project = Project.create_versions(self.source, scans)
        project.set_translation('DefInjected:ThingDef:Item.label', '確定ラベル')
        saved = self.root / 'workspace/project.json'
        project.save(saved)
        restored = Project.load(saved)
        self.assertEqual([item for item in restored.diagnostics
                          if item['code'] == 'unknown-field'], unknown)
        restored.switch_version('1.10')
        self.assertEqual([item for item in restored.diagnostics
                          if item['code'] == 'unknown-field'], [])
        output = self.root / 'diagnostic-output'
        export_versions_test(restored, output)
        self.assertEqual(ET.parse(output / '1.6/Languages/Japanese/DefInjected/ThingDef/Translations.xml')
                         .getroot().findtext('Item.label'), '確定ラベル')
        self.assertFalse((output / '1.10/Languages/Japanese/DefInjected').exists())
        for path in output.rglob('*.xml'):
            self.assertNotIn(b'tooltipText', path.read_bytes())

    def test_strings_reappearing_line_revokes_both_languages_only_in_affected_version(self):
        relative = 'Languages/English/Strings/WordLists/Names.txt'
        for version in ('1.6', '1.10'):
            self.write(f'{version}/{relative}', 'Alpha\nBeta\n')
        scans = {version: scan_mod(self.source, game_version=version)
                 for version in ('1.6', '1.10')}
        project = Project.create_versions(self.source, scans, ['Japanese', 'French'])
        identity = 'Strings:WordLists/Names.txt:line_1'
        for version in ('1.6', '1.10'):
            project.switch_version(version)
            for language, text in (('Japanese', '乙'), ('French', 'Bêta')):
                project.switch_language(language)
                project.set_translation(identity, text)
                project.mark_reviewed(identity, approved=True)
        project.switch_version('1.6')
        self.write(f'1.6/{relative}', 'Alpha\n')
        project.rescan(scan_mod(self.source, game_version='1.6'))
        self.assertTrue(project.entry_index()[identity].stale)
        self.write(f'1.6/{relative}', 'Alpha\nBeta\n')
        project.rescan(scan_mod(self.source, game_version='1.6'))
        saved = self.root / 'workspace/reappeared.json'
        project.save(saved)
        restored = Project.load(saved)
        for language, text in (('Japanese', '乙'), ('French', 'Bêta')):
            restored.switch_language(language)
            entry = restored.entry_index()[identity]
            self.assertEqual(entry.japanese, text)
            self.assertFalse(entry.stale)
            self.assertFalse(entry.approved)
            self.assertTrue(entry.review)
        restored.switch_version('1.10')
        for language, text in (('Japanese', '乙'), ('French', 'Bêta')):
            restored.switch_language(language)
            entry = restored.entry_index()[identity]
            self.assertEqual(entry.japanese, text)
            self.assertTrue(entry.approved)
            self.assertFalse(entry.review)


if __name__ == '__main__':
    unittest.main()

"""Q17 A: formal multi-version output exports finished versions and holds the rest."""
from pathlib import Path
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Entry, Project, Scan, export_versions

REL = 'Languages/Japanese/DefInjected/ResearchProjectDef/Translations.xml'


def entry(text='steel armor', ja=''):
    return Entry('DefInjected:ResearchProjectDef:Armor.label', 'DefInjected', 'ResearchProjectDef',
                 'Armor.label', text, 'Research.xml', japanese=ja)


class FormalVersionExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.versions = ['1.3', '1.4', '1.5', '1.6']

    def project(self, translated=('1.4', '1.5', '1.6')):
        scans = {v: Scan(entries=[entry()], name='Fixture', package_id='test.formal17',
                         versions=self.versions, stats={'active_version': v}) for v in self.versions}
        project = Project.create_versions(self.source, scans)
        for version in translated:
            project.switch_version(version)
            ident = project.entries[0].id
            project.set_translation(ident, '鋼鉄の鎧')
            project.mark_reviewed(ident, approved=True)
        project.switch_version('1.6')
        return project

    def test_finished_versions_only_and_held_version_is_not_advertised(self):
        target = self.root / 'out'
        result = export_versions(self.project(), target)
        self.assertEqual(result.exported, ['1.4', '1.5', '1.6'])
        self.assertIn('1.3', result.held)
        for version in result.exported:
            self.assertEqual(ET.parse(target / version / REL).getroot()[-1].text, '鋼鉄の鎧')
        self.assertFalse((target / '1.3').exists())
        about = ET.parse(target / 'About/About.xml').getroot()
        self.assertEqual([li.text for li in about.find('supportedVersions')], ['1.4', '1.5', '1.6'])
        folders = ET.parse(target / 'LoadFolders.xml').getroot()
        self.assertEqual([child.tag for child in folders], ['v1.4', 'v1.5', 'v1.6'])
        marker = json.loads((target / '.rimworld-translator.json').read_text(encoding='utf-8'))
        self.assertTrue(marker['formal'])
        self.assertNotIn('test_only', marker)
        self.assertEqual(marker['exported_versions'], ['1.4', '1.5', '1.6'])
        self.assertIn('1.3', marker['held_versions'])
        self.assertTrue(any('保留' in warning and '1.3' in warning for warning in result.warnings))

    def test_dangerous_translation_holds_only_that_version(self):
        project = self.project()
        project.switch_version('1.5')
        project.entries[0].english = 'Hello {0}'
        project.set_translation(project.entries[0].id, 'こんにちは')  # placeholder lost
        project.switch_version('1.6')
        target = self.root / 'out'
        result = export_versions(project, target)
        self.assertEqual(result.exported, ['1.4', '1.6'])
        self.assertIn('1.5', result.held)
        self.assertFalse((target / '1.5').exists())

    def test_explicit_selection_holds_unselected_versions(self):
        target = self.root / 'out'
        result = export_versions(self.project(), target, versions=['1.6'])
        self.assertEqual(result.exported, ['1.6'])
        self.assertEqual(sorted(result.held), ['1.3', '1.4', '1.5'])
        with self.assertRaisesRegex(ValueError, 'Not declared'):
            export_versions(self.project(), self.root / 'x', versions=['1.9'])

    def test_nothing_ready_blocks_and_leaves_existing_output_untouched(self):
        target = self.root / 'out'
        export_versions(self.project(), target)
        before = {p: p.read_bytes() for p in target.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'No version is ready'):
            export_versions(self.project(translated=()), target)
        self.assertEqual({p: p.read_bytes() for p in target.rglob('*') if p.is_file()}, before)

    def test_untranslated_keys_are_omitted_not_filled(self):
        target = self.root / 'out'
        project = self.project()
        project.switch_version('1.6')
        project.entries.append(entry('wood armor'))
        project.entries[-1] = Entry('DefInjected:ResearchProjectDef:Wood.label', 'DefInjected',
                                    'ResearchProjectDef', 'Wood.label', 'wood armor', 'Research.xml')
        export_versions(project, target)
        keys = [node.tag for node in ET.parse(target / '1.6' / REL).getroot() if node.tag != ET.Comment]
        self.assertEqual(keys, ['Armor.label'])

    def test_one_point_zero_is_held(self):
        scans = {v: Scan(entries=[entry(ja='鎧')], name='F', package_id='test.formal17',
                         versions=['1.0', '1.6'], stats={'active_version': v}) for v in ('1.0', '1.6')}
        project = Project.create_versions(self.source, scans)
        result = export_versions(project, self.root / 'out')
        self.assertEqual(result.exported, ['1.6'])
        self.assertIn('1.0', result.held)


if __name__ == '__main__':
    unittest.main()

"""One translation set that every declared game version reads (root Languages/, no per-version folders)."""
from pathlib import Path
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Entry, Project, Scan, export_shared, export_versions

REL = 'Languages/Japanese/DefInjected/HediffDef/Translations.xml'


def hediff(key, english='initial'):
    return Entry(f'DefInjected:HediffDef:{key}', 'DefInjected', 'HediffDef', key, english, 'Hediffs.xml')


class SharedExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.versions = ['1.3', '1.4', '1.5', '1.6']

    def project(self, entries_by_version, translations):
        """entries_by_version: {version: [Entry]}; translations: {version: {key: text}}."""
        scans = {v: Scan(entries=entries_by_version.get(v, [hediff('Drug.stages.0.label')]), name='Fixture',
                         package_id='test.shared', versions=self.versions, stats={'active_version': v})
                 for v in self.versions}
        project = Project.create_versions(self.source, scans)
        for version, texts in translations.items():
            project.switch_version(version)
            for entry in project.entries:
                if entry.key in texts:
                    project.set_translation(entry.id, texts[entry.key])
                    project.mark_reviewed(entry.id, approved=True)
        project.switch_version('1.6')
        return project

    def keys(self, target):
        return [node.tag for node in ET.parse(target / REL).getroot() if node.tag != ET.Comment]

    def test_one_root_set_for_all_ready_versions_and_no_version_folders(self):
        project = self.project({}, {v: {'Drug.stages.0.label': '初期'} for v in ('1.4', '1.5', '1.6')})
        target = self.root / 'out'
        result = export_shared(project, target)
        self.assertEqual(result.exported, ['1.4', '1.5', '1.6'])
        self.assertIn('1.3', result.held)
        self.assertEqual(self.keys(target), ['Drug.stages.0.label'])
        self.assertEqual(ET.parse(target / REL).getroot()[-1].text, '初期')
        for version in self.versions:
            self.assertFalse((target / version).exists())
        self.assertFalse((target / 'LoadFolders.xml').exists())
        about = ET.parse(target / 'About/About.xml').getroot()
        self.assertEqual([li.text for li in about.find('supportedVersions')], ['1.4', '1.5', '1.6'])
        marker = json.loads((target / '.rimworld-translator.json').read_text(encoding='utf-8'))
        self.assertTrue(marker['formal'])
        self.assertTrue(marker['shared'])
        self.assertEqual(marker['exported_versions'], ['1.4', '1.5', '1.6'])
        self.assertIn('1.3', marker['held_versions'])

    def test_keys_are_the_union_of_the_versions(self):
        entries = {'1.4': [hediff('Drug.stages.0.label')],
                   '1.5': [hediff('Drug.stages.0.label')],
                   '1.6': [hediff('Drug.stages.0.label'), hediff('Drug.stages.1.label', 'severe')]}
        project = self.project(entries, {'1.4': {'Drug.stages.0.label': '初期'},
                                         '1.5': {'Drug.stages.0.label': '初期'},
                                         '1.6': {'Drug.stages.0.label': '初期', 'Drug.stages.1.label': '重症'}})
        target = self.root / 'out'
        export_shared(project, target)
        self.assertEqual(sorted(self.keys(target)), ['Drug.stages.0.label', 'Drug.stages.1.label'])

    def test_index_form_and_handle_form_of_one_item_are_both_written(self):
        entries = {'1.4': [hediff('Drug.stages.0.label')], '1.5': [hediff('Drug.stages.0.label')],
                   '1.6': [hediff('Drug.stages.Initial.label')]}
        project = self.project(entries, {'1.4': {'Drug.stages.0.label': '初期'},
                                         '1.5': {'Drug.stages.0.label': '初期'},
                                         '1.6': {'Drug.stages.Initial.label': '初期'}})
        target = self.root / 'out'
        export_shared(project, target)
        self.assertEqual(sorted(self.keys(target)), ['Drug.stages.0.label', 'Drug.stages.Initial.label'])

    def test_same_key_with_different_translations_takes_the_newest_version_and_warns(self):
        project = self.project({}, {'1.4': {'Drug.stages.0.label': '旧訳'}, '1.5': {'Drug.stages.0.label': '旧訳'},
                                    '1.6': {'Drug.stages.0.label': '新訳'}})
        target = self.root / 'out'
        result = export_shared(project, target)
        self.assertEqual(ET.parse(target / REL).getroot()[-1].text, '新訳')
        self.assertTrue(any('Drug.stages.0.label' in w and '1.6' in w and '旧訳' in w for w in result.warnings),
                        result.warnings)

    def test_a_held_version_contributes_nothing(self):
        project = self.project({'1.5': [hediff('Only15.stages.0.label')]},
                               {'1.4': {'Drug.stages.0.label': '初期'}, '1.6': {'Drug.stages.0.label': '初期'},
                                '1.5': {'Only15.stages.0.label': '五'}})
        project.switch_version('1.5')
        project.entries[0].english = 'Hello {0}'
        project.set_translation(project.entries[0].id, 'こんにちは')   # placeholder lost: 1.5 is held
        project.switch_version('1.6')
        target = self.root / 'out'
        result = export_shared(project, target)
        self.assertEqual(result.exported, ['1.4', '1.6'])
        self.assertIn('1.5', result.held)
        self.assertEqual(self.keys(target), ['Drug.stages.0.label'])

    def test_nothing_ready_raises(self):
        project = self.project({}, {})
        with self.assertRaisesRegex(ValueError, 'No version is ready'):
            export_shared(project, self.root / 'out')

    def test_reexporting_over_a_per_version_output_removes_the_old_layout(self):
        project = self.project({}, {v: {'Drug.stages.0.label': '初期'} for v in ('1.4', '1.5', '1.6')})
        target = self.root / 'out'
        export_versions(project, target)
        self.assertTrue((target / '1.6' / REL).is_file())
        export_shared(project, target)
        for version in ('1.4', '1.5', '1.6'):
            self.assertFalse((target / version).exists())
        self.assertFalse((target / 'LoadFolders.xml').exists())
        self.assertTrue((target / REL).is_file())


if __name__ == '__main__':
    unittest.main()

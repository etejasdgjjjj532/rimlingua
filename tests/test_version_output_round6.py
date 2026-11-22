"""Predictable output conflicts must not partially replace version trees."""
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_versions_test
from rimworld_translator.multiversion import scan_declared_scenarios, scan_declared_versions


VERSIONS = ('1.3', '1.4', '1.5', '1.6', '1.9', '1.10')
LABEL = 'DefInjected:ThingDef:Item.label'


class VersionOutputRound6Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Independent versions</name>'
                   '<packageId>test.independent</packageId><supportedVersions>'
                   + ''.join(f'<li>{v}</li>' for v in reversed(VERSIONS))
                   + '</supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders>'
                   + ''.join(f'<v{v}><li>{v}</li></v{v}>' for v in VERSIONS)
                   + '</loadFolders>')
        for index, version in enumerate(VERSIONS):
            self.write(f'{version}/Defs/item.xml', '<Defs><ThingDef><defName>Item</defName>'
                       f'<label>source {version}</label></ThingDef><ThingDef>'
                       f'<defName>Only{index}</defName><label>exclusive {version}</label>'
                       '</ThingDef></Defs>')
        self.scans = scan_declared_versions(self.source)
        self.assertEqual(self.scans.failures, {})
        self.project = Project.create_versions(self.source, self.scans.scans)
        for version in VERSIONS:
            self.project.switch_version(version)
            self.project.set_translation(LABEL, f'訳 {version}')
            self.project.mark_reviewed(LABEL, approved=True)
        self.saved = self.root / 'workspace/project.json'
        self.project.save(self.saved)
        self.project = Project.load(self.saved)
        self.target = self.root / 'output'

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def output_xml(self, version):
        return self.target / version / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml'

    def snapshot(self):
        return {str(path.relative_to(self.target)): path.read_bytes()
                for path in self.target.rglob('*') if path.is_file()}

    def change_translations(self):
        for version in VERSIONS:
            self.project.switch_version(version)
            self.project.set_translation(LABEL, f'変更 {version}')

    def test_six_declared_versions_roundtrip_independent_sources_and_approvals(self):
        self.assertEqual(self.scans.declared_versions, list(VERSIONS))
        self.project.switch_version('1.6')
        self.project.set_translation(LABEL, '変更版')
        self.project.save(self.saved)
        restored = Project.load(self.saved)
        warnings = export_versions_test(restored, self.target)
        self.assertTrue(any('未検証' in warning for warning in warnings))
        for index, version in enumerate(VERSIONS):
            restored.switch_version(version)
            self.assertEqual({entry.key: entry.english for entry in restored.entries},
                             {'Item.label': f'source {version}',
                              f'Only{index}.label': f'exclusive {version}'})
            self.assertEqual(restored.entry_index()[LABEL].approved, version != '1.6')
            self.assertFalse(restored.version_profiles[version]['coverage']['source_verified'])
            self.assertFalse(restored.version_profiles[version]['coverage']['game_tested'])
            xml = ET.parse(self.output_xml(version)).getroot()
            self.assertEqual({node.tag: node.text for node in xml},
                             {'Item.label': '変更版' if version == '1.6' else f'訳 {version}'})
        marker = json.loads((self.target / '.rimworld-translator.json').read_text())
        self.assertTrue(marker['test_only'])
        self.assertEqual(marker['unverified_versions'], list(VERSIONS))

    def test_late_version_directory_conflict_preserves_all_prior_output(self):
        export_versions_test(self.project, self.target)
        conflict = self.output_xml('1.10')
        conflict.unlink()
        conflict.mkdir()
        self.change_translations()
        before = self.snapshot()
        with self.assertRaises((ValueError, OSError)):
            export_versions_test(self.project, self.target)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(conflict.is_dir())

    def test_late_version_parent_file_conflict_preserves_all_prior_output(self):
        export_versions_test(self.project, self.target)
        conflict = self.output_xml('1.10')
        conflict.unlink()
        conflict.parent.rmdir()
        conflict.parent.write_text('user file', encoding='utf-8')
        self.change_translations()
        before = self.snapshot()
        with self.assertRaises((ValueError, OSError)):
            export_versions_test(self.project, self.target)
        self.assertEqual(self.snapshot(), before)

    def test_stale_directory_conflict_preserves_all_prior_output(self):
        export_versions_test(self.project, self.target)
        conflict = self.output_xml('1.10')
        conflict.unlink()
        conflict.mkdir()
        self.change_translations()
        self.project.switch_version('1.10')
        self.project.set_translation(LABEL, '')
        before = self.snapshot()
        with self.assertRaises((ValueError, OSError)):
            export_versions_test(self.project, self.target)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(conflict.is_dir())

    def test_new_payload_does_not_overwrite_an_unowned_user_file(self):
        self.project.switch_version('1.10')
        self.project.set_translation(LABEL, '')
        export_versions_test(self.project, self.target)
        conflict = self.output_xml('1.10')
        conflict.parent.mkdir(parents=True, exist_ok=True)
        conflict.write_text('<LanguageData><User>saved work</User></LanguageData>', encoding='utf-8')
        self.change_translations()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            export_versions_test(self.project, self.target)
        self.assertEqual(self.snapshot(), before)

    def test_large_scenario_counts_survive_project_save_without_losing_unexamined_evidence(self):
        for count in (3, 15000):
            with self.subTest(optional_mods=count):
                packages = ','.join(f'opt.p{number}' for number in range(count))
                self.write('1.10/Defs/conditional.xml',
                           f'<Defs><ThingDef MayRequireAnyOf="{packages}"/></Defs>')
                result = scan_declared_scenarios(self.source, max_scenarios=2)
                self.assertEqual(result.failures, {})
                plan = result.plans['1.10']
                self.assertEqual(plan.total_scenarios, 1 << count)
                self.assertEqual(plan.unexamined_scenarios, (1 << count) - 2)
                self.assertEqual(len(result.scans['1.10']), 2)
                project = Project.create_versions(self.source,
                    {version: result.scans[version]['base'] for version in VERSIONS})
                project.save(self.saved)
                restored = Project.load(self.saved)
                profile = restored.version_profiles['1.10']
                self.assertEqual(profile['stats']['dependency_scenarios_total'],
                                 8 if count == 3 else '2^15000')
                self.assertEqual(profile['stats']['dependency_scenarios_unexamined'],
                                 6 if count == 3 else '2^15000 - 2')
                self.assertTrue(any(item['code'] == 'scenario-limit'
                                    for item in profile['stats']['dependency_plan_diagnostics']))
                self.assertFalse(profile['coverage']['source_verified'])
                self.assertFalse(profile['coverage']['game_tested'])


if __name__ == '__main__':
    unittest.main()

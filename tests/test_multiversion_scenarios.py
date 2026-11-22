"""Bounded dependency scenarios retain version-specific extraction results."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator import multiversion
from rimworld_translator.core import Project, export_versions_test
from rimworld_translator.extraction import ScanCancelled


class DeclaredScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Scenario</name>'
                   '<packageId>sample.source</packageId><supportedVersions>'
                   '<li>1.10</li><li>1.9</li></supportedVersions>'
                   '<modDependencies><li><packageId>sample.old</packageId></li></modDependencies>'
                   '<modDependenciesByVersion><v1.10><li><packageId>sample.new</packageId></li>'
                   '</v1.10></modDependenciesByVersion></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders><v1.9><li>1.9</li>'
                   '<li IfModActive="sample.extra">Extra</li></v1.9>'
                   '<v1.10><li>1.10</li><li IfModActive="sample.extra">Extra</li></v1.10></loadFolders>')
        for version, text in [('1.9', 'old source'), ('1.10', 'new source')]:
            self.write(f'{version}/Defs/a.xml', '<Defs><ThingDef><defName>A</defName>'
                       f'<label>{text}</label></ThingDef></Defs>')
        self.write('Extra/Defs/b.xml', '<Defs><ThingDef><defName>B</defName><label>extra source</label>'
                   '</ThingDef></Defs>')

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_all_declared_versions_and_conditions_are_independent(self):
        before = {str(p): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        updates = []
        result = multiversion.scan_declared_scenarios(self.source, progress=lambda *args: updates.append(args))
        self.assertEqual(result.declared_versions, ['1.9', '1.10'])
        self.assertEqual(result.failures, {})
        for version, text, dependency in [('1.9', 'old source', 'sample.old'),
                                          ('1.10', 'new source', 'sample.new')]:
            self.assertEqual(set(result.scans[version]), {'base', 'optional:sample.extra'})
            base = result.scans[version]['base']
            extra = result.scans[version]['optional:sample.extra']
            self.assertEqual({e.key: e.english for e in base.entries}, {'A.label': text})
            self.assertEqual({e.key: e.english for e in extra.entries},
                             {'A.label': text, 'B.label': 'extra source'})
            self.assertEqual(set(base.stats['active_mods']), {'sample.source', dependency})
            self.assertEqual(base.stats['dependency_scenario'], 'base')
        self.assertEqual({(v, s) for v, s, done, total in updates},
                         {('1.9', 'base'), ('1.9', 'optional:sample.extra'),
                          ('1.10', 'base'), ('1.10', 'optional:sample.extra')})
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.source.rglob('*') if p.is_file()})

    def test_selected_context_per_version_can_roundtrip_and_export(self):
        result = multiversion.scan_declared_scenarios(self.source)
        project = Project.create_versions(self.source, {
            '1.9': result.scans['1.9']['base'],
            '1.10': result.scans['1.10']['optional:sample.extra']})
        project.set_translation('DefInjected:ThingDef:A.label', '旧版の訳')
        project.switch_version('1.10')
        project.set_translation('DefInjected:ThingDef:A.label', '新版の訳')
        project.set_translation('DefInjected:ThingDef:B.label', '条件付きの訳')
        path = Path(self.temp.name) / 'workspace/project.json'
        project.save(path)
        loaded = Project.load(path)
        output = Path(self.temp.name) / 'output'
        export_versions_test(loaded, output)
        old = ET.parse(output/'1.9/Languages/Japanese/DefInjected/ThingDef/Translations.xml').getroot()
        new = ET.parse(output/'1.10/Languages/Japanese/DefInjected/ThingDef/Translations.xml').getroot()
        self.assertEqual(old.findtext('A.label'), '旧版の訳')
        self.assertIsNone(old.find('B.label'))
        self.assertEqual(new.findtext('A.label'), '新版の訳')
        self.assertEqual(new.findtext('B.label'), '条件付きの訳')
        self.assertTrue(all(not p['coverage']['source_verified'] for p in loaded.version_profiles.values()))

    def test_bound_records_unexamined_contexts(self):
        result = multiversion.scan_declared_scenarios(self.source, max_scenarios=1)
        self.assertEqual(set(result.scans['1.9']), {'base'})
        self.assertEqual(result.plans['1.9'].unexamined_scenarios, 1)
        self.assertEqual(result.scans['1.9']['base'].stats['dependency_scenarios_unexamined'], 1)
        selected = {v: scans['base'] for v, scans in result.scans.items()}
        project = Project.create_versions(self.source, selected)
        path = Path(self.temp.name) / 'workspace/limited.json'
        project.save(path)
        restored = Project.load(path)
        codes = {d['code'] for d in restored.diagnostics}
        self.assertIn('scenario-limit', codes)
        self.assertIn('dependency-context-unverified', codes)

    def test_failed_version_context_does_not_skip_other_versions(self):
        result = multiversion.scan_declared_scenarios(self.source, contexts={
            '1.9': {'context_sources': [self.source/'missing']}})
        self.assertNotIn('1.9', result.scans)
        self.assertEqual(set(result.failures['1.9']), {'<planning>'})
        self.assertEqual(set(result.scans['1.10']), {'base', 'optional:sample.extra'})

    def test_inactive_dependency_sources_cannot_supply_inherited_text(self):
        dependency = Path(self.temp.name) / 'dependency'
        (dependency/'About').mkdir(parents=True)
        (dependency/'About/About.xml').write_text(
            '<ModMetaData><packageId>sample.extra</packageId></ModMetaData>', encoding='utf-8')
        (dependency/'Defs').mkdir()
        (dependency/'Defs/parent.xml').write_text(
            '<Defs><ThingDef Name="ExtraParent" Abstract="True"><label>external parent</label>'
            '</ThingDef></Defs>', encoding='utf-8')
        self.write('1.9/Defs/child.xml', '<Defs><ThingDef ParentName="ExtraParent">'
                   '<defName>Child</defName></ThingDef></Defs>')
        result = multiversion.scan_declared_scenarios(self.source, contexts={
            '1.9': {'context_sources': [dependency]}})
        self.assertEqual(result.failures, {})
        self.assertNotIn('Child.label', {e.key for e in result.scans['1.9']['base'].entries})
        optional = result.scans['1.9']['optional:sample.extra']
        self.assertEqual(next(e.english for e in optional.entries if e.key == 'Child.label'), 'external parent')

    def test_cancel_and_unsafe_cache_fail_before_writing(self):
        with self.assertRaises(ScanCancelled):
            multiversion.scan_declared_scenarios(self.source, cancel=lambda: True)
        cache = self.source/'forbidden.sqlite'
        with self.assertRaises(ValueError):
            multiversion.scan_declared_scenarios(self.source, contexts={'1.10': {'cache_path': cache}})
        self.assertFalse(cache.exists())
        with self.assertRaises(ValueError):
            multiversion.scan_declared_scenarios(self.source, contexts={'1.6': {}})

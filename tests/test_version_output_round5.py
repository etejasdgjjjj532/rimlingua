"""Provided FindMod contexts must reach version planning and independent output."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator import multiversion
from rimworld_translator.core import Project, export_versions_test


class FindModVersionOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.dependency = self.root / 'dependency'
        self.write(self.source, 'About/About.xml', '''<ModMetaData><name>Target</name>
          <packageId>target.mod</packageId><supportedVersions><li>1.9</li><li>1.10</li>
          </supportedVersions></ModMetaData>''')
        self.write(self.source, 'Defs/base.xml', '''<Defs><ThingDef><defName>Base</defName>
          <label>base label</label></ThingDef></Defs>''')
        self.write(self.source, 'Patches/find.xml', '''<Patch>
          <Operation Class="PatchOperationFindMod"><mods><li>Dependency Display Name</li></mods>
          <match Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Base"]</xpath>
          <value><description>conditional target text</description></value></match>
          </Operation></Patch>''')
        self.write(self.dependency, 'About/About.xml', '''<ModMetaData>
          <name>Dependency Display Name</name><packageId>dep.package</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li></supportedVersions></ModMetaData>''')
        self.write(self.dependency, 'Defs/private.xml', '''<Defs><ThingDef>
          <defName>DependencyOwn</defName><label>dependency text</label></ThingDef></Defs>''')

    def write(self, source, relative, text):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_context_iterator_is_reused_for_planning_and_each_scenario(self):
        result = multiversion.scan_declared_scenarios(self.source, contexts={
            '1.10': {'context_sources': iter([self.dependency])}})
        self.assertEqual(result.failures, {})
        self.assertEqual(set(result.scans['1.10']), {'base', 'optional:dep.package'})
        self.assertIn('Base.description', {entry.key for entry in
                      result.scans['1.10']['optional:dep.package'].entries})

    def test_findmod_context_reaches_version_scan_project_and_test_xml(self):
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result = multiversion.scan_declared_scenarios(self.source, contexts={
            '1.10': {'context_sources': [self.dependency]}})
        self.assertEqual(result.failures, {})
        self.assertEqual(set(result.scans['1.9']), {'base'})
        self.assertEqual(set(result.scans['1.10']), {'base', 'optional:dep.package'})
        conditional = result.scans['1.10']['optional:dep.package']
        self.assertEqual({entry.key: entry.english for entry in conditional.entries},
                         {'Base.label': 'base label', 'Base.description': 'conditional target text'})
        self.assertNotIn('Base.description', {entry.key for entry in result.scans['1.10']['base'].entries})
        project = Project.create_versions(self.source, {
            '1.9': result.scans['1.9']['base'], '1.10': conditional})
        project.set_translation('DefInjected:ThingDef:Base.label', '旧版の訳')
        project.mark_reviewed('DefInjected:ThingDef:Base.label', approved=True)
        project.switch_version('1.10')
        project.set_translation('DefInjected:ThingDef:Base.label', '新版の訳')
        project.set_translation('DefInjected:ThingDef:Base.description', '条件付きの訳')
        saved = self.root / 'workspace/project.json'
        project.save(saved)
        restored = Project.load(saved)
        output = self.root / 'output'
        warnings = export_versions_test(restored, output)
        self.assertTrue(any('未検証' in warning for warning in warnings))
        for version, text in [('1.9', '旧版の訳'), ('1.10', '新版の訳')]:
            xml = ET.parse(output / version / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml').getroot()
            self.assertEqual(xml.findtext('Base.label'), text)
            self.assertEqual(xml.findtext('Base.description'), '条件付きの訳' if version == '1.10' else None)
            self.assertIsNone(xml.find('DependencyOwn.label'))
        restored.switch_version('1.9')
        self.assertTrue(restored.entry_index()['DefInjected:ThingDef:Base.label'].approved)
        self.assertEqual(restored.active_mods, ['target.mod'])
        self.assertTrue(all(not profile['coverage']['source_verified']
                            for profile in restored.version_profiles.values()))
        self.assertEqual(before, {path: Path(path).read_bytes() for path in before})


if __name__ == '__main__':
    unittest.main()

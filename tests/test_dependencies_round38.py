"""Leading LoadFolders separators must not hide dependency scenarios."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.dependency_profiles import plan_dependency_scenarios
from rimworld_translator.multiversion import scan_declared_scenarios


class LeadingSeparatorPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li></supportedVersions>
          <modDependencies><li><packageId>dep.parent</packageId></li></modDependencies>
          </ModMetaData>''')
        self.write('parent/About/About.xml', '<ModMetaData><packageId>dep.parent</packageId></ModMetaData>')
        self.write('parent/Defs/base.xml', '''<Defs><ThingDef><defName>Foreign</defName>
          <label>dependency original must stay excluded</label></ThingDef></Defs>''')
        self.write('target/Common/Defs/conditional.xml', '''<Defs>
          <ThingDef MayRequire="zzz.def"><defName>Conditional</defName>
          <label>target conditional label</label></ThingDef></Defs>''')
        self.write('target/Common/Patches/conditional.xml', '''<Patch>
          <Operation Class="PatchOperationAdd" MayRequire="zzz.patch">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>target patch description</description></value></Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def load_folder(self, alias, guard=''):
        self.write('target/LoadFolders.xml', f'''<loadFolders><v1.9>
          <li {guard}>{alias}</li></v1.9></loadFolders>''')

    def assert_scan(self, alias, guard=''):
        self.load_folder(alias, guard)
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=8,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        for version in self.versions:
            optional = ('zzz.def', 'zzz.gate', 'zzz.patch') if guard else ('zzz.def', 'zzz.patch')
            self.assertEqual(result.plans[version].optional_mods, optional)
            self.assertEqual(result.plans[version].unexamined_scenarios, 0)
            self.assertFalse(any(d.code == 'load-path' for d in result.plans[version].diagnostics))
            scans = result.scans[version]
            self.assertEqual(scans['base'].entries, [])
            scenario = 'optional:' + ','.join(optional)
            entries = {e.key: e for e in scans[scenario].entries}
            self.assertEqual({key: e.english for key, e in entries.items()}, {
                'Conditional.label': 'target conditional label',
                'Foreign.description': 'target patch description'})
            self.assertEqual(entries['Conditional.label'].source_file, 'Common/Defs/conditional.xml')
            self.assertEqual(entries['Foreign.description'].source_file, 'Common/Patches/conditional.xml')
            if guard:
                self.assertEqual(scans['optional:zzz.def,zzz.patch'].entries, [])

    def test_leading_slash_common_discovers_target_conditions(self):
        self.assert_scan('/Common')

    def test_leading_backslash_common_discovers_target_conditions(self):
        self.assert_scan('\\Common\\')

    def test_leading_separators_preserve_folder_guards(self):
        self.assert_scan('///Common///', 'IfModActive="zzz.gate"')

    def test_traversal_after_leading_separator_stays_rejected(self):
        for alias in ('/../parent', '\\..\\parent', '///../parent///',
                      '/Common/../../parent'):
            with self.subTest(alias=alias):
                self.load_folder(alias)
                for version in self.versions:
                    plan = plan_dependency_scenarios(self.root / 'target', version)
                    self.assertEqual(plan.optional_mods, ())
                    self.assertTrue(any(d.code == 'load-path' for d in plan.diagnostics))


if __name__ == '__main__':
    unittest.main()

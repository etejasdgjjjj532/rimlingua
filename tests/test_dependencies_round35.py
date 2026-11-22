"""Fixed FindMod matches must not displace useful bounded scenarios."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class FixedFindModPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><name>Target</name>
          <packageId>target.mod</packageId><supportedVersions><li>1.9</li>
          <li>1.10</li></supportedVersions><modDependencies><li>
          <packageId>dep.parent</packageId></li></modDependencies></ModMetaData>''')
        self.write('decoy/About/About.xml', '''<ModMetaData><name>Decoy</name>
          <packageId>aaa.decoy</packageId></ModMetaData>''')
        self.write('decoy/Defs/base.xml', '''<Defs><ThingDef><defName>Private</defName>
          <label>dependency text must not leak</label></ThingDef></Defs>''')
        self.write('parent/About/About.xml', '''<ModMetaData><name>Required Parent</name>
          <packageId>dep.parent</packageId></ModMetaData>''')
        self.write('parent/Defs/base.xml', '''<Defs><ThingDef MayRequire="zzz.real">
          <defName>Owned</defName><label>parent text must not leak</label></ThingDef></Defs>''')

    def write(self, relative, value):
        file = self.root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(value, encoding='utf-8')

    def patch(self, fixed_name, extra_names=''):
        self.write('target/Patches/find.xml', f'''<Patch>
          <Operation Class="PatchOperationFindMod"><mods><li>{fixed_name}</li>
          <li>Decoy</li>{extra_names}</mods><match Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Owned"]</xpath>
          <value><description>target patch text</description></value></match>
          </Operation></Patch>''')

    def scan(self, sources):
        return scan_declared_scenarios(self.root / 'target', max_scenarios=2,
            contexts={version: {'context_sources': sources} for version in self.versions})

    def test_fixed_findmod_any_keeps_real_second_scenario_and_target_patch_origin(self):
        for fixed_name in ('Target', 'Required Parent'):
            with self.subTest(fixed_name=fixed_name):
                sources = [self.root / 'decoy', self.root / 'parent']
                self.patch(fixed_name)
                before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
                result = self.scan(sources)
                self.assertEqual(result.failures, {})
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
                    self.assertEqual(result.scans[version]['base'].entries, [])
                    entries = result.scans[version]['optional:zzz.real'].entries
                    self.assertEqual({e.key: e.english for e in entries}, {
                        'Owned.description': 'target patch text'})
                    self.assertEqual({e.key: e.source_file for e in entries}, {
                        'Owned.description': 'Patches/find.xml'})
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_decoy_needed_by_other_condition_remains_optional(self):
        self.patch('Target')
        self.write('target/Defs/other.xml', '''<Defs><ThingDef MayRequire="aaa.decoy">
          <defName>Other</defName><label>other target text</label></ThingDef></Defs>''')
        result = self.scan([self.root / 'decoy', self.root / 'parent'])
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.decoy', 'zzz.real'))
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:aaa.decoy'].entries}, {'Other.label': 'other target text'})

    def test_fixed_match_preserves_unknown_and_ambiguous_name_diagnostics(self):
        self.write('other/About/About.xml', '''<ModMetaData><name>Decoy</name>
          <packageId>bbb.other</packageId></ModMetaData>''')
        self.patch('Target', '<li>Unknown Display Name</li>')
        result = self.scan([self.root / 'decoy', self.root / 'other', self.root / 'parent'])
        self.assertEqual(result.failures, {})
        for version in self.versions:
            plan = result.plans[version]
            self.assertEqual(plan.optional_mods, ('zzz.real',))
            self.assertTrue(any(d.code == 'findmod-context' and 'Unknown Display Name' in d.message
                                for d in plan.diagnostics))
            self.assertIn('findmod-ambiguous-name', {d.code for d in plan.diagnostics})

    def test_without_fixed_name_each_known_alternative_remains_optional(self):
        self.write('other/About/About.xml', '''<ModMetaData><name>Other</name>
          <packageId>bbb.other</packageId></ModMetaData>''')
        self.patch('Other')
        result = self.scan([self.root / 'decoy', self.root / 'other', self.root / 'parent'])
        self.assertEqual(result.failures, {})
        for version in self.versions:
            plan = result.plans[version]
            self.assertEqual(plan.optional_mods, ('aaa.decoy', 'bbb.other', 'zzz.real'))
            self.assertEqual(plan.total_scenarios, 8)
            self.assertEqual(plan.unexamined_scenarios, 6)


if __name__ == '__main__':
    unittest.main()

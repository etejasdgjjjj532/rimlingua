"""Fixed FindMod branches cannot consume bounded dependency contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class FixedFindModBranchPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><name>Target</name>
          <packageId>target.mod</packageId><supportedVersions><li>1.9</li><li>1.10</li>
          </supportedVersions><modDependencies><li><packageId>dep.parent</packageId>
          </li></modDependencies></ModMetaData>''')
        self.write('parent/About/About.xml', '''<ModMetaData><name>Required Parent</name>
          <packageId>dep.parent</packageId></ModMetaData>''')
        self.write('parent/Defs/base.xml', '''<Defs><ThingDef><defName>Foreign</defName>
          <label>dependency source text must not leak</label></ThingDef></Defs>''')
        self.write('optional/About/About.xml', '''<ModMetaData><name>Optional</name>
          <packageId>opt.mod</packageId></ModMetaData>''')
        self.write('decoy/About/About.xml', '''<ModMetaData><name>Decoy</name>
          <packageId>aaa.decoy</packageId></ModMetaData>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def findmod(self, name):
        self.write('target/Patches/find.xml', f'''<Patch>
          <Operation Class="PatchOperationFindMod"><mods><li>{name}</li></mods>
          <match Class="PatchOperationAdd" MayRequire="zzz.real">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>target match text</description></value></match>
          <nomatch Class="PatchOperationAdd" MayRequire="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>target nomatch text</labelShort></value></nomatch>
          </Operation></Patch>''')

    def scan(self, maximum=2):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=maximum,
            contexts={v: {'context_sources': [self.root / 'parent', self.root / 'optional',
                                             self.root / 'decoy']}
                      for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(tuple(result.plans), self.versions)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def test_fixed_match_excludes_nomatch_conditions_from_bounded_plan(self):
        for name in ('Target', 'Required Parent'):
            with self.subTest(name=name):
                self.findmod(name)
                result = self.scan()
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
                    self.assertEqual(result.scans[version]['base'].entries, [])
                    self.assertEqual({e.key: (e.english, e.source_file) for e in
                        result.scans[version]['optional:zzz.real'].entries}, {
                            'Foreign.description': ('target match text', 'Patches/find.xml')})

    def test_optional_match_preserves_both_branch_contexts(self):
        self.findmod('Optional')
        result = self.scan(8)
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods,
                             ('aaa.decoy', 'opt.mod', 'zzz.real'))
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:opt.mod,zzz.real'].entries}, {
                    'Foreign.description': 'target match text'})
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:aaa.decoy'].entries}, {
                    'Foreign.labelShort': 'target nomatch text'})

    def test_unreachable_nomatch_does_not_hide_same_dependency_elsewhere(self):
        self.findmod('Target')
        self.write('target/Defs/other.xml', '''<Defs><ThingDef MayRequire="aaa.decoy">
          <defName>Other</defName><label>independent target text</label></ThingDef></Defs>''')
        result = self.scan(4)
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.decoy', 'zzz.real'))
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:aaa.decoy'].entries}, {
                    'Other.label': 'independent target text'})


if __name__ == '__main__':
    unittest.main()

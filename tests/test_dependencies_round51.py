"""Unknown patch success modes must not consume child dependency contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class UnknownSuccessPlanningTests(unittest.TestCase):
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
          <label>dependency text must not leak</label></ThingDef></Defs>''')
        self.write('target/Patches/real.xml', '''<Patch><Operation Class="PatchOperationAdd"
          MayRequire="zzz.real"><xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>target reachable text</description></value></Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def sequence(self, success, guard=''):
        return f'''<Operation Class="PatchOperationSequence" {guard}><success>{success}</success>
          <operations><li Class="PatchOperationAdd" MayRequire="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>child target text</labelShort></value></li></operations></Operation>'''

    def scan(self, maximum=2):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=maximum,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(tuple(result.plans), self.versions)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def test_unknown_top_level_success_does_not_displace_reachable_target_text(self):
        for success in ('Unknown', 'normal', ' '):
            with self.subTest(success=success):
                operation = self.sequence(success, 'MayRequire="bbb.guard"')
                self.write('target/Patches/unknown.xml',
                    f'<Patch>{operation}</Patch>')
                result = self.scan()
                for version in self.versions:
                    self.assertEqual({e.key: (e.english, e.source_file)
                        for scan in result.scans[version].values() for e in scan.entries},
                        {'Foreign.description': ('target reachable text', 'Patches/real.xml')})
                    self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
                    self.assertTrue(any(d.code == 'patch-success' and d.source == 'Patches/unknown.xml'
                                        for d in result.plans[version].diagnostics))

    def test_unknown_nested_success_keeps_its_guard_but_not_unexecuted_child_guards(self):
        unknown = self.sequence('Unknown', 'IfModNotActive="bbb.guard"')
        self.write('target/Patches/unknown.xml', f'''<Patch>
          <Operation Class="PatchOperationSequence"><operations>{unknown}
          <li Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <value><labelShort>target after skipped failure</labelShort></value></li>
          </operations></Operation></Patch>''')
        result = self.scan(3)
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('bbb.guard', 'zzz.real'))
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:bbb.guard'].entries},
                {'Foreign.labelShort': 'target after skipped failure'})
            self.assertEqual(result.scans[version]['base'].entries, [])
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:zzz.real'].entries},
                {'Foreign.description': 'target reachable text'})

    def test_known_success_modes_preserve_child_dependency_and_target_provenance(self):
        for success in ('Normal', 'Always', 'Never', 'Invert', ''):
            with self.subTest(success=success):
                self.write('target/Patches/known.xml', f'<Patch>{self.sequence(success)}</Patch>')
                result = self.scan(4)
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('aaa.decoy', 'zzz.real'))
                    self.assertEqual({e.key: (e.english, e.source_file) for e in
                        result.scans[version]['optional:aaa.decoy'].entries},
                        {'Foreign.labelShort': ('child target text', 'Patches/known.xml')})


if __name__ == '__main__':
    unittest.main()

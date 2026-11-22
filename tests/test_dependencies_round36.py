"""Unreachable direct PatchOperations must not consume bounded contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class PatchGuardPlanningTests(unittest.TestCase):
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
        self.write('target/Patches/real.xml', '''<Patch>
          <Operation Class="PatchOperationAdd" MayRequire="zzz.real">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>target patch text</description></value></Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def guarded_patch(self, folder, guard):
        self.write(f'target/{folder}Patches/guarded.xml', f'''<Patch>
          <Operation Class="PatchOperationSequence" {guard}>
          <operations><li Class="PatchOperationAdd" MayRequire="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>conditional patch text</description></value></li></operations>
          </Operation></Patch>''')

    def scan(self, limit=2):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=limit,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def assert_real_patch(self, result, optional=('zzz.real',)):
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, optional)
            self.assertEqual(result.scans[version]['base'].entries, [])
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries},
                             {'Foreign.description': 'target patch text'})
            self.assertEqual({e.source_file for e in entries}, {'Patches/real.xml'})

    def test_impossible_direct_operation_does_not_displace_real_patch(self):
        self.guarded_patch('', 'IfModNotActive="target.mod"')
        self.assert_real_patch(self.scan())

    def test_folder_and_operation_contradiction_do_not_displace_real_patch(self):
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9><li>.</li>
          <li IfModActive="zzz.gate">Conditional</li></v1.9></loadFolders>''')
        self.guarded_patch('Conditional/', 'IfModNotActive="zzz.gate"')
        self.assert_real_patch(self.scan(3), ('zzz.gate', 'zzz.real'))

    def test_alternative_folder_route_preserves_reachable_operation(self):
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9><li>.</li>
          <li IfModActive="zzz.gate">Conditional</li>
          <li IfModNotActive="zzz.gate">Conditional</li></v1.9></loadFolders>''')
        self.guarded_patch('Conditional/', 'IfModNotActive="zzz.gate"')
        result = self.scan(8)
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods,
                             ('aaa.decoy', 'zzz.gate', 'zzz.real'))
            entries = result.scans[version]['optional:aaa.decoy'].entries
            self.assertEqual({e.key: e.english for e in entries},
                             {'Foreign.description': 'conditional patch text'})
            self.assertEqual({e.source_file for e in entries}, {'Conditional/Patches/guarded.xml'})

    def test_unknown_direct_condition_keeps_diagnostic_without_decoy(self):
        self.guarded_patch('', 'IfModUnknown="aaa.unknown"')
        result = self.scan()
        self.assert_real_patch(result)
        for version in self.versions:
            self.assertTrue(any(d.code == 'unknown-condition' and
                d.source == 'Patches/guarded.xml' for d in result.plans[version].diagnostics))


if __name__ == '__main__':
    unittest.main()

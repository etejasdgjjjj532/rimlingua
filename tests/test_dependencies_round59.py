"""Only operation payloads actually published by extraction affect contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class InertOperationBodyPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10')
    inert = ('PatchOperationRemove', 'PatchOperationTest', 'PatchOperationAttributeAdd',
             'PatchOperationAttributeSet', 'PatchOperationAttributeRemove')

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
          <label>dependency text</label></ThingDef></Defs>''')
        self.write('target/Patches/real.xml', '''<Patch><Operation Class="PatchOperationAdd"
          MayRequire="zzz.real"><xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>owned reachable text</description></value></Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def operation(self, kind, guard='', xpath='Defs/ThingDef[defName="Absent"]'):
        return f'''<li Class="{kind}" {guard}><xpath>{xpath}</xpath>
          <attribute>unused</attribute><value MayRequire="aaa.decoy">
          <labelShort>owned value text</labelShort></value></li>'''

    def scan(self, maximum):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=maximum,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(tuple(result.plans), self.versions)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def test_unused_terminal_body_does_not_displace_reachable_owned_text(self):
        for kind in self.inert:
            for prefix in ('', 'Verse.'):
                with self.subTest(kind=prefix + kind):
                    self.write('target/Patches/inert.xml', '<Patch>' + self.operation(prefix + kind) + '</Patch>')
                    result = self.scan(2)
                    for version in self.versions:
                        self.assertEqual({e.key: (e.english, e.source_file)
                            for scan in result.scans[version].values() for e in scan.entries},
                            {'Foreign.description': ('owned reachable text', 'Patches/real.xml')})
                        self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))

    def test_nested_terminal_keeps_own_guard_and_sequence_outcome(self):
        for kind in self.inert:
            with self.subTest(kind=kind):
                operation = self.operation(kind, 'IfModNotActive="bbb.guard"')
                self.write('target/Patches/inert.xml', f'''<Patch>
                  <Operation Class="PatchOperationSequence"><operations>{operation}
                  <li Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Foreign"]</xpath>
                  <value><labelShort>owned after skipped terminal</labelShort></value></li>
                  </operations></Operation></Patch>''')
                result = self.scan(3)
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('bbb.guard', 'zzz.real'))
                    self.assertEqual(result.scans[version]['base'].entries, [])
                    self.assertEqual({e.key: (e.english, e.source_file) for e in
                        result.scans[version]['optional:bbb.guard'].entries},
                        {'Foreign.labelShort': ('owned after skipped terminal', 'Patches/inert.xml')})
                    self.assertEqual({e.key: e.english for e in
                        result.scans[version]['optional:zzz.real'].entries},
                        {'Foreign.description': 'owned reachable text'})

    def test_published_values_preserve_payload_conditions(self):
        for kind in ('PatchOperationAdd', 'PatchOperationReplace', 'PatchOperationInsert'):
            with self.subTest(kind=kind):
                xpath = 'Defs/ThingDef[defName="Foreign"]' + ('' if kind.endswith('Add') else '/label')
                self.write('target/Patches/inert.xml', '<Patch>' + self.operation(kind, xpath=xpath) + '</Patch>')
                result = self.scan(4)
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('aaa.decoy', 'zzz.real'))
                    self.assertEqual({e.key: (e.english, e.source_file) for e in
                        result.scans[version]['optional:aaa.decoy'].entries},
                        {'Foreign.labelShort': ('owned value text', 'Patches/inert.xml')})


if __name__ == '__main__':
    unittest.main()

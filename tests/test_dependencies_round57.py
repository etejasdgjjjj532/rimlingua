"""Unsupported PatchOperation bodies cannot displace reachable target contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class UnsupportedOperationPlanningTests(unittest.TestCase):
    versions = ('1.8', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.8</li><li>1.10</li></supportedVersions>
          <modDependencies><li><packageId>dep.parent</packageId></li></modDependencies>
          </ModMetaData>''')
        self.write('parent/About/About.xml', '<ModMetaData><packageId>dep.parent</packageId></ModMetaData>')
        self.write('parent/Defs/base.xml', '''<Defs><ThingDef><defName>Foreign</defName>
          <label>dependency original</label></ThingDef></Defs>''')
        self.write('target/Patches/real.xml', '''<Patch><Operation Class="PatchOperationAdd"
          MayRequire="zzz.real"><xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>owned reachable text</description></value></Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def unsupported(self, class_attribute, success='Normal', guard=''):
        return f'''<Operation {class_attribute} {guard}><success>{success}</success>
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <value MayRequire="aaa.decoy"><labelShort>unexecuted value text</labelShort></value>
          <operations><li Class="PatchOperationAdd" MayRequire="aaa.child">
          <value><reportString>unexecuted child text</reportString></value></li></operations>
          </Operation>'''

    def scan(self, maximum):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=maximum,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(tuple(result.plans), self.versions)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def test_unsupported_top_level_body_does_not_displace_reachable_owned_text(self):
        for class_attribute in ('Class="Custom.Unsupported"', 'Class="PatchOperation"', ''):
            with self.subTest(class_attribute=class_attribute):
                operation = self.unsupported(class_attribute, guard='MayRequire="bbb.guard"')
                self.write('target/Patches/unsupported.xml', f'<Patch>{operation}</Patch>')
                result = self.scan(2)
                for version in self.versions:
                    self.assertEqual({e.key: (e.english, e.source_file)
                        for scan in result.scans[version].values() for e in scan.entries},
                        {'Foreign.description': ('owned reachable text', 'Patches/real.xml')})
                    self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
                    self.assertTrue(any(d.code == 'patch-unsupported' and d.source == 'Patches/unsupported.xml'
                                        for d in result.plans[version].diagnostics))

    def test_unsupported_nested_body_keeps_own_guard_for_later_sequence_text(self):
        for success in ('Normal', 'Always', 'Never', 'Invert'):
            with self.subTest(success=success):
                operation = self.unsupported('Class="Custom.Unsupported"', success,
                                             'IfModNotActive="bbb.guard"')
                self.write('target/Patches/unsupported.xml', f'''<Patch>
                  <Operation Class="PatchOperationSequence"><operations>{operation}
                  <li Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Foreign"]</xpath>
                  <value><labelShort>owned text after absent unknown</labelShort></value></li>
                  </operations></Operation></Patch>''')
                result = self.scan(3)
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('bbb.guard', 'zzz.real'))
                    self.assertEqual(result.scans[version]['base'].entries, [])
                    self.assertEqual({e.key: e.english for e in
                        result.scans[version]['optional:bbb.guard'].entries},
                        {'Foreign.labelShort': 'owned text after absent unknown'})
                    self.assertEqual({e.key: e.english for e in
                        result.scans[version]['optional:zzz.real'].entries},
                        {'Foreign.description': 'owned reachable text'})

    def test_supported_namespaced_add_preserves_value_condition(self):
        self.write('target/Patches/supported.xml', '''<Patch>
          <Operation Class="Verse.PatchOperationAdd"><xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <value MayRequire="aaa.value"><labelShort>owned supported text</labelShort></value>
          </Operation></Patch>''')
        result = self.scan(4)
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.value', 'zzz.real'))
            self.assertEqual({e.key: (e.english, e.source_file) for e in
                result.scans[version]['optional:aaa.value'].entries},
                {'Foreign.labelShort': ('owned supported text', 'Patches/supported.xml')})


if __name__ == '__main__':
    unittest.main()

"""Unknown PatchOperation order must not hide unrelated reachable text."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class UnknownOrderPlanningTests(unittest.TestCase):
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
          <label>dependency text</label></ThingDef></Defs>''')
        self.write('target/Patches/real.xml', '''<Patch><Operation Class="PatchOperationAdd"
          MayRequire="zzz.real"><xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>owned reachable text</description></value></Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def operation(self, kind, order, guard=''):
        return f'''<Operation Class="{kind}" {guard}><order>{order}</order>
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value MayRequire="aaa.decoy">
          <labelShort>owned value text</labelShort></value></Operation>'''

    def scan(self, maximum):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=maximum,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(tuple(result.plans), self.versions)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def test_unknown_top_level_order_does_not_displace_reachable_owned_text(self):
        for kind in ('PatchOperationAdd', 'Verse.PatchOperationInsert'):
            for order in ('Sideways', 'append', ' '):
                with self.subTest(kind=kind, order=order):
                    operation = self.operation(kind, order, 'MayRequire="bbb.guard"')
                    self.write('target/Patches/unknown.xml', f'<Patch>{operation}</Patch>')
                    result = self.scan(2)
                    for version in self.versions:
                        self.assertEqual({e.key: (e.english, e.source_file)
                            for scan in result.scans[version].values() for e in scan.entries},
                            {'Foreign.description': ('owned reachable text', 'Patches/real.xml')})
                        self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
                        self.assertTrue(any(d.code == 'patch-order' and d.source == 'Patches/unknown.xml'
                                            for d in result.plans[version].diagnostics))

    def test_unknown_nested_order_keeps_own_guard_for_later_sequence_text(self):
        for kind in ('PatchOperationAdd', 'PatchOperationInsert'):
            with self.subTest(kind=kind):
                operation = self.operation(kind, 'Sideways', 'IfModNotActive="bbb.guard"')
                self.write('target/Patches/unknown.xml', f'''<Patch>
                  <Operation Class="PatchOperationSequence"><operations>{operation}
                  <li Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Foreign"]</xpath>
                  <value><labelShort>owned after skipped unknown</labelShort></value></li>
                  </operations></Operation></Patch>''')
                result = self.scan(3)
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('bbb.guard', 'zzz.real'))
                    self.assertEqual(result.scans[version]['base'].entries, [])
                    self.assertEqual({e.key: e.english for e in
                        result.scans[version]['optional:bbb.guard'].entries},
                        {'Foreign.labelShort': 'owned after skipped unknown'})
                    self.assertEqual({e.key: e.english for e in
                        result.scans[version]['optional:zzz.real'].entries},
                        {'Foreign.description': 'owned reachable text'})

    def test_valid_and_default_order_preserve_value_conditions(self):
        for kind in ('PatchOperationAdd', 'PatchOperationInsert'):
            for order in ('Append', 'Prepend', ''):
                with self.subTest(kind=kind, order=order):
                    # Selecting the label makes Insert produce a sibling field.
                    operation = self.operation(kind, order).replace(
                        'Defs/ThingDef[defName="Foreign"]',
                        'Defs/ThingDef[defName="Foreign"]/label' if kind.endswith('Insert')
                        else 'Defs/ThingDef[defName="Foreign"]')
                    self.write('target/Patches/unknown.xml', f'<Patch>{operation}</Patch>')
                    result = self.scan(4)
                    for version in self.versions:
                        self.assertEqual(result.plans[version].optional_mods, ('aaa.decoy', 'zzz.real'))
                        self.assertEqual({e.key: (e.english, e.source_file) for e in
                            result.scans[version]['optional:aaa.decoy'].entries},
                            {'Foreign.labelShort': ('owned value text', 'Patches/unknown.xml')})


if __name__ == '__main__':
    unittest.main()

"""Unreachable nested PatchOperations must not crowd out useful contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class NestedPatchGuardPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><name>Target</name><packageId>target.mod</packageId>
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

    def test_impossible_nested_sequence_does_not_displace_real_patch(self):
        self.write('target/Patches/nested.xml', '''<Patch>
          <Operation Class="PatchOperationSequence"><operations>
          <li Class="PatchOperationSequence" IfModNotActive="target.mod"><operations>
          <li Class="PatchOperationAdd" MayRequire="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>unreachable target text</labelShort></value></li>
          </operations></li></operations></Operation></Patch>''')
        self.assert_real_patch()

    def test_impossible_conditional_branch_does_not_displace_real_patch(self):
        self.write('target/Patches/nested.xml', '''<Patch>
          <Operation Class="PatchOperationConditional">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <match Class="PatchOperationSequence" IfModNotActive="target.mod"><operations>
          <li Class="PatchOperationAdd" MayRequire="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>unreachable target text</labelShort></value></li>
          </operations></match></Operation></Patch>''')
        self.assert_real_patch()

    def test_impossible_findmod_branch_does_not_displace_real_patch(self):
        self.write('target/Patches/nested.xml', '''<Patch>
          <Operation Class="PatchOperationFindMod"><mods><li>Target</li></mods>
          <match Class="PatchOperationSequence" IfModNotActive="target.mod"><operations>
          <li Class="PatchOperationAdd" MayRequire="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>unreachable target text</labelShort></value></li>
          </operations></match></Operation></Patch>''')
        self.assert_real_patch()

    def test_reachable_nested_operations_preserve_optional_target_text(self):
        for kind, opening, closing in (
                ('PatchOperationSequence', '<operations><li', '</li></operations>'),
                ('PatchOperationConditional',
                 '<xpath>Defs/ThingDef[defName="Foreign"]</xpath><match', '</match>'),
                ('PatchOperationFindMod', '<mods><li>Target</li></mods><match', '</match>')):
            with self.subTest(kind=kind):
                self.write('target/Patches/nested.xml', f'''<Patch>
                  <Operation Class="{kind}">{opening} Class="PatchOperationAdd" MayRequire="zzz.real">
                  <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
                  <labelShort>reachable target text</labelShort></value>{closing}</Operation></Patch>''')
                result = self.scan()
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
                    self.assertEqual(result.scans[version]['base'].entries, [])
                    entries = result.scans[version]['optional:zzz.real'].entries
                    self.assertEqual({e.key: e.english for e in entries}, {
                        'Foreign.description': 'target patch text',
                        'Foreign.labelShort': 'reachable target text'})
                    self.assertEqual({e.key: e.source_file for e in entries}, {
                        'Foreign.description': 'Patches/real.xml',
                        'Foreign.labelShort': 'Patches/nested.xml'})

    def test_value_subtree_is_not_pruned_as_an_operation(self):
        self.write('target/Patches/nested.xml', '''<Patch>
          <Operation Class="PatchOperationSequence"><operations>
          <li Class="PatchOperationAdd" MayRequire="zzz.real">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <value IfModUnknown="aaa.unknown" IfModNotActive="target.mod">
          <labelShort>target value text</labelShort></value></li>
          </operations></Operation></Patch>''')
        result = self.scan()
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            self.assertIn('unknown-condition', {d.code for d in result.plans[version].diagnostics})
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:zzz.real'].entries}, {
                    'Foreign.description': 'target patch text',
                    'Foreign.labelShort': 'target value text'})

    def test_nested_operation_respects_root_folder_guard(self):
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9>
          <li IfModActive="target.mod">/</li></v1.9></loadFolders>''')
        self.test_impossible_nested_sequence_does_not_displace_real_patch()

    def assert_real_patch(self):
        result = self.scan()
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            self.assertEqual(result.scans[version]['base'].entries, [])
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries},
                             {'Foreign.description': 'target patch text'})
            self.assertEqual({e.source_file for e in entries}, {'Patches/real.xml'})

    def scan(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result


if __name__ == '__main__':
    unittest.main()

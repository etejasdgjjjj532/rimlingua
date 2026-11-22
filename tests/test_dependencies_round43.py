"""Ancestor patch guards must not displace reachable target translations."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class AncestorPatchGuardPlanningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><name>Target</name>
          <packageId>target.mod</packageId><supportedVersions><li>1.9</li><li>1.10</li>
          </supportedVersions><modDependencies><li><packageId>dep.parent</packageId>
          </li></modDependencies></ModMetaData>''')
        self.write('parent/About/About.xml', '<ModMetaData><packageId>dep.parent</packageId></ModMetaData>')
        self.write('parent/Defs/base.xml', '''<Defs><ThingDef><defName>Foreign</defName>
          <label>dependency source text</label></ThingDef></Defs>''')
        self.write('target/Patches/real.xml', '''<Patch><Operation Class="PatchOperationAdd"
          MayRequire="zzz.real"><xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <value><description>target patch text</description></value></Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def nested(self, kind, guard, child_guard):
        opening, closing = {
            'PatchOperationSequence': ('<operations><li', '</li></operations>'),
            'PatchOperationConditional': ('<xpath>Defs/ThingDef[defName="Foreign"]</xpath><match', '</match>'),
            'PatchOperationFindMod': ('<mods><li>Target</li></mods><match', '</match>'),
        }[kind]
        self.write('target/Patches/nested.xml', f'''<Patch><Operation Class="{kind}" {guard}>
          {opening} Class="PatchOperationAdd" {child_guard}>
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>nested target text</labelShort></value>{closing}</Operation></Patch>''')

    def scan(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in ('1.9', '1.10')})
        self.assertEqual(result.failures, {})
        self.assertEqual(tuple(result.plans), ('1.9', '1.10'))
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def test_ancestor_contradiction_does_not_consume_bounded_contexts(self):
        for kind in ('PatchOperationSequence', 'PatchOperationConditional', 'PatchOperationFindMod'):
            with self.subTest(kind=kind):
                self.nested(kind, 'IfModNotActive="aaa.decoy"', 'MayRequire="aaa.decoy"')
                result = self.scan()
                for version in ('1.9', '1.10'):
                    self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
                    self.assertEqual(result.scans[version]['base'].entries, [])
                    entries = result.scans[version]['optional:zzz.real'].entries
                    self.assertEqual({e.key: (e.english, e.source_file) for e in entries}, {
                        'Foreign.description': ('target patch text', 'Patches/real.xml')})

    def test_same_named_any_guards_do_not_overwrite_reachable_ancestor_clause(self):
        self.nested('PatchOperationSequence', 'IfModActive="aaa.optional,zzz.real"',
                    'IfModActive="zzz.real"')
        result = self.scan()
        for version in ('1.9', '1.10'):
            self.assertEqual(result.plans[version].optional_mods, ('aaa.optional', 'zzz.real'))
        # Inspect all contexts for the positive control: both ANY clauses can
        # hold with zzz.real, so ancestor propagation must preserve its text.
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=4,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in ('1.9', '1.10')})
        for version in ('1.9', '1.10'):
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries}, {
                'Foreign.description': 'target patch text', 'Foreign.labelShort': 'nested target text'})

    def test_repeated_any_clauses_across_three_levels_keep_earlier_constraint(self):
        self.write('target/Patches/nested.xml', '''<Patch>
          <Operation Class="PatchOperationSequence" IfModActive="aaa.decoy"><operations>
          <li Class="PatchOperationSequence" IfModActive="bbb.decoy"><operations>
          <li Class="PatchOperationAdd" IfModNotActive="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>unreachable target text</labelShort></value></li>
          </operations></li></operations></Operation></Patch>''')
        result = self.scan()
        for version in ('1.9', '1.10'):
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries}, {
                'Foreign.description': 'target patch text'})

    def test_impossible_sibling_does_not_prune_reachable_branch(self):
        self.write('target/Patches/nested.xml', '''<Patch>
          <Operation Class="PatchOperationSequence" IfModNotActive="aaa.decoy"><operations>
          <li Class="PatchOperationAdd" MayRequire="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>unreachable target text</labelShort></value></li>
          <li Class="PatchOperationAdd" MayRequire="zzz.real">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>reachable target text</labelShort></value></li>
          </operations></Operation></Patch>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=4,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in ('1.9', '1.10')})
        for version in ('1.9', '1.10'):
            # The ancestor's negative guard is relevant to the reachable child.
            self.assertEqual(result.plans[version].optional_mods, ('aaa.decoy', 'zzz.real'))
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:zzz.real'].entries}, {
                    'Foreign.description': 'target patch text',
                    'Foreign.labelShort': 'reachable target text'})
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:aaa.decoy,zzz.real'].entries}, {
                    'Foreign.description': 'target patch text'})

    def test_empty_container_failure_control_keeps_following_patch_reachable(self):
        for success in ('Never', 'Invert', 'Unknown'):
            with self.subTest(success=success):
                self.write('target/Patches/nested.xml', f'''<Patch>
                  <Operation Class="PatchOperationSequence"><operations>
                  <li Class="PatchOperationSequence" IfModNotActive="aaa.decoy">
                  <success>{success}</success><operations>
                  <li Class="PatchOperationAdd" MayRequire="aaa.decoy">
                  <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
                  <labelShort>unreachable text</labelShort></value></li></operations></li>
                  <li Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Foreign"]</xpath>
                  <value><labelShort>reachable with decoy</labelShort></value></li>
                  </operations></Operation></Patch>''')
                result = self.scan()
                for version in ('1.9', '1.10'):
                    self.assertEqual(result.plans[version].optional_mods, ('aaa.decoy', 'zzz.real'))
                    self.assertEqual(result.scans[version]['base'].entries, [])
                    entries = result.scans[version]['optional:aaa.decoy'].entries
                    self.assertEqual({e.key: e.english for e in entries}, {
                        'Foreign.labelShort': 'reachable with decoy'})


if __name__ == '__main__':
    unittest.main()

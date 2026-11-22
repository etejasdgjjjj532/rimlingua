"""Impossible top-level Def conditions must not consume bounded scenarios."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class ImpossibleDefPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10', '2.0')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li><li>2.0</li></supportedVersions>
          <modDependencies><li><packageId>dep.parent</packageId></li></modDependencies>
          </ModMetaData>''')
        self.write('parent/About/About.xml', '<ModMetaData><packageId>dep.parent</packageId></ModMetaData>')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_impossible_target_def_does_not_hide_reachable_owned_string(self):
        self.write('target/Defs/own.xml', '''<Defs>
          <ThingDef IfModActiveAny="aaa.toggle,bbb.toggle" IfModNotActive="aaa.toggle"
                    IfModNotActiveAll="bbb.toggle">
            <defName>Never</defName><label MayRequire="aaa.nested">never label</label>
          </ThingDef>
          <ThingDef MayRequire="zzz.real"><defName>Owned</defName><label>owned label</label></ThingDef>
          </Defs>''')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        # The direct evaluator independently excludes Never for all four assignments.
        for active in ((), ('aaa.toggle',), ('bbb.toggle',), ('aaa.toggle', 'bbb.toggle')):
            direct = scan_mod(self.root / 'target', game_version='1.10',
                active_mods=['target.mod', 'dep.parent', 'aaa.nested', 'zzz.real', *active])
            self.assertEqual({e.key: e.english for e in direct.entries}, {'Owned.label': 'owned label'})
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            self.assertEqual(result.plans[version].unexamined_scenarios, 0)
            self.assertEqual(result.scans[version]['base'].entries, [])
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Owned.label': 'owned label'})
            self.assertEqual({e.source_file for e in entries}, {'Defs/own.xml'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_inactive_context_owner_def_does_not_hide_target_patch_string(self):
        self.write('parent/Defs/foreign.xml', '''<Defs>
          <ThingDef IfModNotActive="dep.parent" MayRequire="aaa.never">
            <defName>Never</defName><label MayRequire="aaa.nested">foreign never label</label>
          </ThingDef>
          <ThingDef MayRequire="zzz.real"><defName>Foreign</defName><label>foreign label</label></ThingDef>
          </Defs>''')
        self.write('target/Patches/add.xml', '''<Patch><Operation Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <value><description>target added description</description></value></Operation></Patch>''')
        options = {'context_sources': [self.root / 'parent']}
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2,
            contexts={v: options for v in self.versions})
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries},
                             {'Foreign.description': 'target added description'})
            self.assertEqual({e.source_file for e in entries}, {'Patches/add.xml'})
            self.assertEqual(result.scans[version]['base'].entries, [])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_fixed_dependency_pruning_is_independent_for_each_declared_version(self):
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li><li>2.0</li></supportedVersions>
          <modDependencies><li><packageId>dep.parent</packageId></li></modDependencies>
          <modDependenciesByVersion><v1.10/><v2.0/></modDependenciesByVersion>
          </ModMetaData>''')
        self.write('target/Defs/own.xml', '''<Defs>
          <ThingDef IfModNotActive="dep.parent" MayRequire="aaa.branch">
            <defName>Optional</defName><label>optional version label</label></ThingDef>
          <ThingDef MayRequire="zzz.real"><defName>Owned</defName><label>owned label</label></ThingDef>
          </Defs>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=8)
        self.assertEqual(result.failures, {})
        self.assertEqual(result.plans['1.9'].required_mods, ('dep.parent',))
        self.assertEqual(result.plans['1.9'].optional_mods, ('zzz.real',))
        self.assertEqual({e.key: e.english for e in result.scans['1.9']['optional:zzz.real'].entries},
                         {'Owned.label': 'owned label'})
        for version in ('1.10', '2.0'):
            self.assertEqual(result.plans[version].required_mods, ())
            self.assertEqual(result.plans[version].optional_mods, ('aaa.branch', 'dep.parent', 'zzz.real'))
            self.assertEqual({e.key: e.english for e in result.scans[version]['optional:aaa.branch'].entries},
                             {'Optional.label': 'optional version label'})
            self.assertEqual(result.scans[version]['optional:aaa.branch,dep.parent'].entries, [])

    def test_reachable_any_def_keeps_all_possible_conditions(self):
        self.write('target/Defs/own.xml', '''<Defs>
          <ThingDef IfModActiveAny="aaa.toggle,bbb.toggle" IfModNotActive="aaa.toggle">
            <defName>Owned</defName><label>reachable label</label>
          </ThingDef></Defs>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=4)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.toggle', 'bbb.toggle'))
            self.assertEqual({e.key: e.english for e in result.scans[version]['optional:bbb.toggle'].entries},
                             {'Owned.label': 'reachable label'})
            self.assertEqual(result.scans[version]['optional:aaa.toggle,bbb.toggle'].entries, [])


if __name__ == '__main__':
    unittest.main()

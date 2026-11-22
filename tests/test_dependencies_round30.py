"""Excluded unknown Def conditions must not displace reachable owned text."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class UnknownDefConditionPlanningTests(unittest.TestCase):
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

    def test_unknown_target_def_condition_does_not_displace_owned_string(self):
        self.write('target/Defs/own.xml', '''<Defs>
          <ThingDef IfModActiveTypo="aaa.unknown" MayRequire="aaa.never">
            <defName>Excluded</defName><label MayRequire="aaa.nested">excluded label</label>
          </ThingDef>
          <ThingDef MayRequire="zzz.real"><defName>Owned</defName><label>owned label</label></ThingDef>
          </Defs>''')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        for version in self.versions:
            direct = scan_mod(self.root / 'target', game_version=version,
                active_mods=['target.mod', 'dep.parent', 'aaa.unknown', 'aaa.never', 'aaa.nested', 'zzz.real'])
            self.assertEqual({e.key: e.english for e in direct.entries}, {'Owned.label': 'owned label'})
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            plan = result.plans[version]
            self.assertEqual(plan.optional_mods, ('zzz.real',))
            self.assertEqual(plan.unexamined_scenarios, 0)
            self.assertTrue(any(d.code == 'unknown-condition' and d.source == 'Defs/own.xml'
                                for d in plan.diagnostics))
            self.assertEqual(result.scans[version]['base'].entries, [])
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Owned.label': 'owned label'})
            self.assertEqual({e.source_file for e in entries}, {'Defs/own.xml'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_unknown_context_def_condition_does_not_displace_target_patch_text(self):
        self.write('parent/Defs/foreign.xml', '''<Defs>
          <ThingDef IFMODUNKNOWN="aaa.unknown" MayRequire="aaa.never">
            <defName>Excluded</defName><label MayRequire="aaa.nested">foreign excluded label</label>
          </ThingDef>
          <ThingDef MayRequire="zzz.real"><defName>Foreign</defName><label>foreign label</label></ThingDef>
          </Defs>''')
        self.write('target/Patches/add.xml', '''<Patch><Operation Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <value><description>target added description</description></value></Operation></Patch>''')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        options = {'context_sources': [self.root / 'parent']}
        for version in self.versions:
            direct = scan_mod(self.root / 'target', game_version=version,
                active_mods=['target.mod', 'dep.parent', 'zzz.real', 'aaa.never', 'aaa.nested'], **options)
            self.assertEqual({e.key: e.english for e in direct.entries},
                             {'Foreign.description': 'target added description'})
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2,
            contexts={v: options for v in self.versions})
        self.assertEqual(result.failures, {})
        for version in self.versions:
            plan = result.plans[version]
            self.assertEqual(plan.optional_mods, ('zzz.real',))
            self.assertTrue(any(d.code == 'unknown-condition' and d.source == str(self.root / 'parent/Defs/foreign.xml')
                                for d in plan.diagnostics))
            self.assertEqual(result.scans[version]['base'].entries, [])
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries},
                             {'Foreign.description': 'target added description'})
            self.assertEqual({e.source_file for e in entries}, {'Patches/add.xml'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_unknown_mayrequire_attribute_does_not_exclude_reachable_def(self):
        self.write('target/Defs/own.xml', '''<Defs>
          <ThingDef MayRequireTypo="aaa.unknown" MayRequire="zzz.real">
            <defName>Owned</defName><label>owned label</label></ThingDef></Defs>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Owned.label': 'owned label'})


if __name__ == '__main__':
    unittest.main()

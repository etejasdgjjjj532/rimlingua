"""Load-folder guards and direct Def guards must be considered together."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class CrossFolderDefPlanningTests(unittest.TestCase):
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

    def prepare(self, owner):
        self.write(f'{owner}/LoadFolders.xml', '''<loadFolders><v1.9>
          <li IfModActive="zzz.gate">Conditional</li><li>Actual</li>
          </v1.9></loadFolders>''')
        self.write(f'{owner}/Conditional/Defs/never.xml', '''<Defs>
          <ThingDef IfModNotActive="zzz.gate" MayRequire="aaa.phantom">
          <defName>Never</defName><label>unreachable label</label></ThingDef></Defs>''')
        self.write(f'{owner}/Actual/Defs/actual.xml', '''<Defs>
          <ThingDef MayRequire="zzz.real"><defName>Owned</defName><label>owned label</label>
          </ThingDef></Defs>''')

    def test_cross_folder_contradiction_does_not_displace_target_string(self):
        self.prepare('target')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        # The direct evaluator independently excludes Never with either gate state.
        for version in self.versions:
            for active in ((), ('zzz.gate',)):
                direct = scan_mod(self.root / 'target', game_version=version,
                    active_mods=['target.mod', 'dep.parent', 'aaa.phantom', 'zzz.real', *active])
                self.assertEqual({e.key: e.english for e in direct.entries}, {'Owned.label': 'owned label'})
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=3)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.gate', 'zzz.real'))
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Owned.label': 'owned label'})
            self.assertEqual({e.source_file for e in entries}, {'Actual/Defs/actual.xml'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_cross_folder_context_contradiction_keeps_only_target_patch_text(self):
        self.prepare('parent')
        self.write('parent/Actual/Defs/actual.xml', '''<Defs>
          <ThingDef MayRequire="zzz.real"><defName>Foreign</defName><label>foreign label</label>
          </ThingDef></Defs>''')
        self.write('target/Patches/add.xml', '''<Patch><Operation Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <value><description>target added description</description></value></Operation></Patch>''')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        options = {'context_sources': [self.root / 'parent']}
        for version in self.versions:
            direct = scan_mod(self.root / 'target', game_version=version,
                active_mods=['target.mod', 'dep.parent', 'zzz.real'], **options)
            self.assertEqual({e.key: e.english for e in direct.entries},
                             {'Foreign.description': 'target added description'})
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=3,
            contexts={v: options for v in self.versions})
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.gate', 'zzz.real'))
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries},
                             {'Foreign.description': 'target added description'})
            self.assertEqual({e.source_file for e in entries}, {'Patches/add.xml'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_second_route_to_same_folder_preserves_reachable_def(self):
        self.prepare('target')
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9>
          <li IfModActive="zzz.gate">Conditional</li><li IfModNotActive="zzz.gate">Conditional</li>
          </v1.9></loadFolders>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=4)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            entries = result.scans[version]['optional:aaa.phantom'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Never.label': 'unreachable label'})

    def test_repeated_any_attributes_preserve_both_conjunctive_guards(self):
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9>
          <li IfModActive="aaa.gate,bbb.gate">Conditional</li><li>Actual</li>
          </v1.9></loadFolders>''')
        self.write('target/Conditional/Defs/never.xml', '''<Defs>
          <ThingDef IfModActive="ccc.gate" IfModNotActive="aaa.gate,bbb.gate" MayRequire="aaa.phantom">
          <defName>Never</defName><label>unreachable label</label></ThingDef></Defs>''')
        self.write('target/Actual/Defs/actual.xml', '''<Defs><ThingDef MayRequire="zzz.real">
          <defName>Owned</defName><label>owned label</label></ThingDef></Defs>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=4)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.gate', 'bbb.gate', 'zzz.real'))
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Owned.label': 'owned label'})


if __name__ == '__main__':
    unittest.main()

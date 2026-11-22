"""Unconditional higher-priority files must not spend dependency scenarios."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class ShadowedDependencyPlanningTests(unittest.TestCase):
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
          <li>Low</li><li>High</li></v1.9></loadFolders>''')
        self.write(f'{owner}/Low/Defs/nested/shared.xml', '''<Defs>
          <ThingDef MayRequire="aaa.phantom"><defName>Shadowed</defName>
          <label>shadowed label</label></ThingDef></Defs>''')
        self.write(f'{owner}/High/Defs/nested/shared.xml', '<Defs/>')
        self.write(f'{owner}/Low/Defs/real.xml', '''<Defs>
          <ThingDef MayRequire="zzz.real"><defName>Owned</defName>
          <label>real label</label></ThingDef></Defs>''')

    def test_shadowed_target_def_does_not_displace_reachable_string(self):
        self.prepare('target')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        for version in self.versions:
            direct = scan_mod(self.root / 'target', game_version=version,
                active_mods=['target.mod', 'dep.parent', 'aaa.phantom', 'zzz.real'])
            self.assertEqual({e.key: e.english for e in direct.entries}, {'Owned.label': 'real label'})
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Owned.label': 'real label'})
            self.assertEqual({e.source_file for e in entries}, {'Low/Defs/real.xml'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_shadowed_context_def_keeps_only_target_patch_text(self):
        self.prepare('parent')
        self.write('target/Patches/add.xml', '''<Patch><Operation Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Owned"]</xpath>
          <value><description>target description</description></value></Operation></Patch>''')
        options = {'context_sources': [self.root / 'parent']}
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2,
            contexts={v: options for v in self.versions})
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Owned.description': 'target description'})
            self.assertEqual({e.source_file for e in entries}, {'Patches/add.xml'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_conditional_higher_file_keeps_lower_file_conditions(self):
        self.prepare('target')
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9>
          <li>Low</li><li IfModActive="zzz.gate">High</li></v1.9></loadFolders>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=8)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.phantom', 'zzz.gate', 'zzz.real'))
            self.assertEqual({e.key for e in result.scans[version]['optional:aaa.phantom'].entries},
                             {'Shadowed.label'})
            self.assertEqual(result.scans[version]['optional:aaa.phantom,zzz.gate'].entries, [])

    def test_repeated_folder_uses_each_routes_actual_priority(self):
        self.prepare('target')
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9>
          <li>High</li><li>Low</li><li IfModActive="zzz.gate">High</li>
          </v1.9></loadFolders>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=8)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.phantom', 'zzz.gate', 'zzz.real'))
            self.assertEqual({e.key for e in result.scans[version]['optional:aaa.phantom'].entries},
                             {'Shadowed.label'})
            self.assertEqual(result.scans[version]['optional:aaa.phantom,zzz.gate'].entries, [])


if __name__ == '__main__':
    unittest.main()

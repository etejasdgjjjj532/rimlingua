"""Satisfied ANY guards must not displace useful bounded contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class SatisfiedAnyPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li></supportedVersions></ModMetaData>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_satisfied_target_folder_any_keeps_useful_second_scenario(self):
        for attribute in ('IfModActive', 'IfModActiveAny', 'MayRequireAnyOf'):
            with self.subTest(attribute=attribute):
                self.write('target/LoadFolders.xml', f'''<loadFolders><v1.9>
                  <li {attribute}="TARGET.MOD;aaa.phantom">Content</li>
                  </v1.9></loadFolders>''')
                self.write('target/Content/Defs/real.xml', '''<Defs>
                  <ThingDef MayRequire="zzz.real"><defName>Owned</defName>
                  <label>owned text</label></ThingDef></Defs>''')
                result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
                self.assertEqual(result.failures, {})
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
                    entries = result.scans[version]['optional:zzz.real'].entries
                    self.assertEqual({e.key: e.english for e in entries}, {'Owned.label': 'owned text'})
                    self.assertEqual({e.source_file for e in entries}, {'Content/Defs/real.xml'})

    def test_satisfied_def_any_keeps_useful_second_scenario(self):
        self.write('target/Defs/real.xml', '''<Defs>
          <ThingDef MayRequireAnyOf="aaa.phantom,target.mod" MayRequire="zzz.real">
          <defName>Owned</defName><label>owned text</label></ThingDef></Defs>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            self.assertEqual({e.key for e in result.scans[version]['optional:zzz.real'].entries},
                             {'Owned.label'})

    def test_optional_context_owner_only_fixes_its_own_any_clause(self):
        self.write('parent/About/About.xml', '<ModMetaData><packageId>dep.parent</packageId></ModMetaData>')
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9>
          <li IfModActive="dep.parent">Content</li></v1.9></loadFolders>''')
        self.write('target/Content/Patches/add.xml', '''<Patch><Operation Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Owned"]</xpath><value>
          <description>target description</description></value></Operation></Patch>''')
        for folder_guard, def_guard in (
                ('', 'MayRequireAnyOf="aaa.phantom,DEP.PARENT"'),
                ('IfModActiveAny="aaa.phantom,DEP.PARENT"', '')):
            with self.subTest(folder_guard=folder_guard, def_guard=def_guard):
                self.write('parent/LoadFolders.xml', f'''<loadFolders><v1.9>
                  <li {folder_guard}>Content</li></v1.9></loadFolders>''')
                self.write('parent/Content/Defs/real.xml', f'''<Defs>
                  <ThingDef {def_guard} MayRequire="zzz.real"><defName>Owned</defName>
                  <label>parent text must not leak</label></ThingDef></Defs>''')
                before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
                result = scan_declared_scenarios(self.root / 'target', max_scenarios=4,
                    contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
                self.assertEqual(result.failures, {})
                for version in self.versions:
                    self.assertEqual(result.plans[version].optional_mods, ('dep.parent', 'zzz.real'))
                    self.assertEqual(result.scans[version]['base'].entries, [])
                    entries = result.scans[version]['optional:dep.parent,zzz.real'].entries
                    self.assertEqual({e.key: e.english for e in entries},
                                     {'Owned.description': 'target description'})
                    self.assertEqual({e.source_file for e in entries}, {'Content/Patches/add.xml'})
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_satisfied_any_does_not_erase_an_alternative_needed_by_another_def(self):
        self.write('target/Defs/real.xml', '''<Defs>
          <ThingDef MayRequireAnyOf="aaa.real,target.mod"><defName>Always</defName>
          <label>always text</label></ThingDef>
          <ThingDef MayRequire="aaa.real"><defName>Gated</defName>
          <label>gated text</label></ThingDef></Defs>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.real',))
            self.assertEqual({e.key for e in result.scans[version]['base'].entries}, {'Always.label'})
            self.assertEqual({e.key for e in result.scans[version]['optional:aaa.real'].entries},
                             {'Always.label', 'Gated.label'})

    def test_unsatisfied_any_retains_each_reachable_alternative(self):
        self.write('target/Defs/real.xml', '''<Defs>
          <ThingDef MayRequireAnyOf="aaa.left;zzz.right"><defName>Owned</defName>
          <label>owned text</label></ThingDef></Defs>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=4)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.left', 'zzz.right'))
            self.assertEqual(result.scans[version]['base'].entries, [])
            for scenario in ('optional:aaa.left', 'optional:zzz.right'):
                self.assertEqual({e.key for e in result.scans[version][scenario].entries}, {'Owned.label'})


if __name__ == '__main__':
    unittest.main()

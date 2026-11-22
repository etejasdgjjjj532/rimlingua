"""Root LoadFolders aliases must expose the same bounded dependency contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.dependency_profiles import plan_dependency_scenarios
from rimworld_translator.multiversion import scan_declared_scenarios


class RootAliasPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10')

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
          <label>dependency text must not leak</label></ThingDef></Defs>''')
        self.write('target/Defs/conditional.xml', '''<Defs><ThingDef MayRequire="zzz.def">
          <defName>Conditional</defName><label>target conditional label</label></ThingDef></Defs>''')
        self.write('target/Patches/conditional.xml', '''<Patch>
          <Operation Class="PatchOperationAdd" MayRequire="zzz.patch">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>target patch description</description></value></Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def load_folder(self, alias, guard=''):
        self.write('target/LoadFolders.xml', f'''<loadFolders><v1.9>
          <li {guard}>{alias}</li></v1.9></loadFolders>''')

    def scan(self, limit=4):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=limit,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def assert_complete_root_scan(self, alias):
        self.load_folder(alias)
        result = self.scan()
        for version in self.versions:
            plan = result.plans[version]
            self.assertEqual(plan.optional_mods, ('zzz.def', 'zzz.patch'))
            self.assertEqual(plan.unexamined_scenarios, 0)
            self.assertFalse(any(d.code == 'load-path' for d in plan.diagnostics))
            scans = result.scans[version]
            self.assertEqual(scans['base'].entries, [])
            expected = {
                'optional:zzz.def': {'Conditional.label': 'target conditional label'},
                'optional:zzz.patch': {'Foreign.description': 'target patch description'},
                'optional:zzz.def,zzz.patch': {
                    'Conditional.label': 'target conditional label',
                    'Foreign.description': 'target patch description'},
            }
            for scenario, entries in expected.items():
                self.assertEqual({e.key: e.english for e in scans[scenario].entries}, entries)
                for entry in scans[scenario].entries:
                    self.assertEqual(entry.source_file, 'Defs/conditional.xml'
                        if entry.key == 'Conditional.label' else 'Patches/conditional.xml')

    def test_slash_root_preserves_conditional_defs_and_target_patch(self):
        self.assert_complete_root_scan('/')

    def test_backslash_root_preserves_conditional_defs_and_target_patch(self):
        self.assert_complete_root_scan('\\')

    def test_dot_and_empty_roots_remain_equivalent(self):
        for alias in ('.', ''):
            with self.subTest(alias=alias):
                self.assert_complete_root_scan(alias)

    def test_root_alias_keeps_folder_guards(self):
        self.load_folder('/', 'IfModActive="zzz.gate"')
        result = self.scan(8)
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods,
                             ('zzz.def', 'zzz.gate', 'zzz.patch'))
            self.assertEqual(result.scans[version]['optional:zzz.def,zzz.patch'].entries, [])
            self.assertEqual({e.key for e in
                result.scans[version]['optional:zzz.def,zzz.gate,zzz.patch'].entries},
                {'Conditional.label', 'Foreign.description'})

    def test_parent_traversal_is_still_rejected(self):
        self.load_folder('/../parent')
        for version in self.versions:
            plan = plan_dependency_scenarios(self.root / 'target', version)
            self.assertEqual(plan.optional_mods, ())
            self.assertTrue(any(d.code == 'load-path' for d in plan.diagnostics))


if __name__ == '__main__':
    unittest.main()

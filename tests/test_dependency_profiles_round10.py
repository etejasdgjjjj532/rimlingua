"""処理命令が版別依存の探索枠や条件付きキーを変えないことを確認する。"""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.dependency_profiles import plan_dependency_scenarios
from rimworld_translator.multiversion import scan_declared_scenarios


class ProcessingInstructionDependencyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('About/About.xml', '''<ModMetaData>
          <?metadata MayRequire="aaa.not-a-package-condition"?>
          <packageId>target.mod</packageId><supportedVersions>
          <li>1.10</li><li>1.9</li></supportedVersions>
          <modDependenciesByVersion>
          <v1.9><li><packageId>dep.old</packageId></li></v1.9>
          <v1.10><li><packageId>dep.new</packageId></li></v1.10>
          </modDependenciesByVersion></ModMetaData>''')
        self.write('LoadFolders.xml', '''<loadFolders>
          <?folders IfModActive="aaa.fake"?>
          <v1.9><?old IfModActive="aaa.fake"?>
            <li>Common</li><li IfModActiveAll="opt.a,opt.b">Old</li>
          </v1.9><v1.10><li>Common</li>
            <li IfModActive="opt.c">New</li></v1.10></loadFolders>''')
        for folder, name, label in [('Common', 'Own', 'own label'),
                                    ('Old', 'OldOnly', 'old combination label'),
                                    ('New', 'NewOnly', 'new conditional label')]:
            self.write(f'{folder}/Defs/own.xml' if folder == 'Common'
                       else f'{folder}/Defs/extra.xml', f'''<Defs><ThingDef>
                       <defName>{name}</defName><label>{label}</label>
                       </ThingDef></Defs>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_non_element_content_does_not_consume_bounded_optional_slots(self):
        self.write('Old/Patches/conditions.xml', '''<Patch>
          <?probe MayRequire="aaa.fake"?>
          <!-- <Operation MayRequire="aaa.comment"/> -->
          <Operation Class="PatchOperationSequence" MayRequire="opt.a">
            <?nested MayRequire="aaa.nested"?>
            <operations><li Class="PatchOperationAdd" MayRequire="opt.b"/>
            </operations></Operation></Patch>''')
        old = plan_dependency_scenarios(self.root, '1.9', max_scenarios=4)
        future = plan_dependency_scenarios(self.root, '1.10', max_scenarios=4)
        self.assertEqual(old.required_mods, ('dep.old',))
        self.assertEqual(old.optional_mods, ('opt.a', 'opt.b'))
        self.assertEqual([item.name for item in old.scenarios], [
            'base', 'optional:opt.a', 'optional:opt.b', 'optional:opt.a,opt.b'])
        self.assertEqual(old.unexamined_scenarios, 0)
        self.assertEqual(future.required_mods, ('dep.new',))
        self.assertEqual(future.optional_mods, ('opt.c',))
        self.assertEqual(future.total_scenarios, 2)

    def test_version_scenarios_retain_combination_only_keys_with_loadfolder_pi(self):
        result = scan_declared_scenarios(self.root, max_scenarios=4)
        self.assertEqual(result.declared_versions, ['1.9', '1.10'])
        self.assertEqual(result.failures, {})
        actual = {version: {scenario: {entry.key: entry.english for entry in scan.entries}
                            for scenario, scan in scans.items()}
                  for version, scans in result.scans.items()}
        self.assertEqual(actual, {
            '1.9': {
                'base': {'Own.label': 'own label'},
                'optional:opt.a': {'Own.label': 'own label'},
                'optional:opt.b': {'Own.label': 'own label'},
                'optional:opt.a,opt.b': {'Own.label': 'own label',
                                       'OldOnly.label': 'old combination label'},
            },
            '1.10': {
                'base': {'Own.label': 'own label'},
                'optional:opt.c': {'Own.label': 'own label',
                                   'NewOnly.label': 'new conditional label'},
            },
        })
        for version, scans in result.scans.items():
            required = 'dep.old' if version == '1.9' else 'dep.new'
            self.assertTrue(all(required in item.active_mods
                                for item in result.plans[version].scenarios))
            for scan in scans.values():
                self.assertIn('dependency-context-unverified',
                              {item['code'] for item in scan.diagnostics})


if __name__ == '__main__':
    unittest.main()

"""版別依存と条件付き本文の有界探索を、小さい実XMLで検証する。"""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import dependency_profiles as profiles
from rimworld_translator.core import scan_mod


class DependencyProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.about('''<modDependencies><li><packageId>Dep.Base</packageId></li></modDependencies>
          <modDependenciesByVersion><v1.9><li><packageId>Dep.Old</packageId></li></v1.9>
          <v1.10><li><packageId>Dep.New</packageId></li></v1.10></modDependenciesByVersion>''')

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def about(self, extra=''):
        self.write('About/About.xml', f'''<ModMetaData><packageId>Target.Mod</packageId>
          <supportedVersions><li>1.6</li><li>1.9</li><li>1.10</li></supportedVersions>{extra}</ModMetaData>''')

    def test_exact_version_dependencies_replace_base_without_older_fallback(self):
        for version, expected in [('1.6', ('dep.base',)), ('1.9', ('dep.old',)), ('1.10', ('dep.new',))]:
            with self.subTest(version=version):
                plan = profiles.plan_dependency_scenarios(self.root, version)
                self.assertEqual(plan.required_mods, expected)
                self.assertEqual(plan.scenarios[0].active_mods, frozenset((*expected, 'target.mod')))

    def test_empty_exact_override_removes_base_dependency(self):
        self.about('<modDependencies><li><packageId>dep.base</packageId></li></modDependencies><modDependenciesByVersion><v1.6/></modDependenciesByVersion>')
        self.assertEqual(profiles.plan_dependency_scenarios(self.root, '1.6').required_mods, ())

    def test_scenarios_recover_a_b_and_combined_keys_without_other_version(self):
        self.about()
        self.write('LoadFolders.xml', '''<loadFolders><v1.6><li>Common</li>
          <li IfModActive="opt.a">A</li><li IfModActiveAll="opt.a,opt.b">AB</li>
          </v1.6><v1.9><li IfModActive="other.version">Other</li></v1.9></loadFolders>''')
        self.write('Common/Defs/base.xml', '<Defs><ThingDef><defName>Base</defName><label>base</label></ThingDef><ThingDef MayRequire="opt.b"><defName>B</defName><label>b</label></ThingDef></Defs>')
        self.write('A/Defs/a.xml', '<Defs><ThingDef><defName>A</defName><label>a</label></ThingDef></Defs>')
        self.write('AB/Patches/ab.xml', '<Patch><Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Base"]</xpath><value><description>both</description></value></Operation></Patch>')
        plan = profiles.plan_dependency_scenarios(self.root, '1.6')
        self.assertEqual(plan.optional_mods, ('opt.a', 'opt.b'))
        actual = {scenario.name: {e.key for e in scan_mod(self.root, game_version='1.6', active_mods=scenario.active_mods).entries}
                  for scenario in plan.scenarios}
        self.assertEqual(actual, {'base': {'Base.label'}, 'optional:opt.a': {'Base.label', 'A.label'},
            'optional:opt.b': {'Base.label', 'B.label'}, 'optional:opt.a,opt.b': {'Base.label', 'A.label', 'B.label', 'Base.description'}})
        self.assertEqual(plan.unexamined_scenarios, 0)

    def test_numeric_load_branch_does_not_read_1_10_for_1_9(self):
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li MayRequire="opt.old">Old</li></v1.6><v1.10><li MayRequire="opt.future">Future</li></v1.10></loadFolders>')
        self.write('Old/Defs/a.xml', '<Defs/>')
        self.write('Future/Defs/a.xml', '<Defs/>')
        self.assertEqual(profiles.plan_dependency_scenarios(self.root, '1.9').optional_mods, ('opt.old',))
        self.assertEqual(profiles.plan_dependency_scenarios(self.root, '1.10').optional_mods, ('opt.future',))

    def test_limit_retains_explicit_unexamined_count(self):
        self.write('Defs/a.xml', '<Defs><ThingDef MayRequireAnyOf="opt.a,opt.b,opt.c"/></Defs>')
        plan = profiles.plan_dependency_scenarios(self.root, '1.6', max_scenarios=3)
        self.assertEqual(len(plan.scenarios), 3)
        self.assertEqual(plan.total_scenarios, 8)
        self.assertEqual(plan.unexamined_scenarios, 5)
        self.assertIn('scenario-limit', {d.code for d in plan.diagnostics})

    def test_fixed_active_context_does_not_become_optional(self):
        self.write('Defs/a.xml', '<Defs><ThingDef MayRequire="Opt.A,opt.b"/></Defs>')
        plan = profiles.plan_dependency_scenarios(self.root, '1.6', base_active_mods={'OPT.A'})
        self.assertEqual(plan.optional_mods, ('opt.b',))
        self.assertTrue(all('opt.a' in s.active_mods for s in plan.scenarios))

    def test_unknown_conditions_and_findmod_names_are_diagnosed(self):
        self.write('Defs/a.xml', '<Defs><ThingDef IfModMystery="opt.a"/></Defs>')
        self.write('Patches/a.xml', '<Patch><Operation Class="PatchOperationFindMod"><mods><li>Display.Name</li><li>Display Name</li></mods></Operation></Patch>')
        plan = profiles.plan_dependency_scenarios(self.root, '1.6')
        self.assertEqual(plan.optional_mods, ())
        self.assertTrue({'unknown-condition', 'findmod-context'} <= {d.code for d in plan.diagnostics})

    def test_rejects_undeclared_version_and_invalid_limits(self):
        for version, limit in [('1.7', 16), ('1.6', 0), ('1.6', 257), ('1.6', True)]:
            with self.subTest(version=version, limit=limit), self.assertRaises(ValueError):
                profiles.plan_dependency_scenarios(self.root, version, max_scenarios=limit)

    def test_xml_file_limit_is_diagnosed_and_missing_folders_are_not_silent(self):
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li>Missing</li><li>.</li></v1.6></loadFolders>')
        self.write('Defs/a.xml', '<Defs/>')
        self.write('Defs/b.xml', '<Defs/>')
        plan = profiles.plan_dependency_scenarios(self.root, '1.6', max_xml_files=1)
        self.assertTrue({'condition-file-limit', 'missing-folder'} <= {d.code for d in plan.diagnostics})


if __name__ == '__main__':
    unittest.main()

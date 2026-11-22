"""Nested dependency conditions and bounded exploration regression fixtures."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.dependency_profiles import plan_dependency_scenarios


class DependencyPlanningRound6Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('target/About/About.xml', '''<ModMetaData><name>Target</name>
          <packageId>target.mod</packageId><supportedVersions><li>1.9</li><li>1.10</li>
          </supportedVersions></ModMetaData>''')
        self.target = self.root / 'target'

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def test_large_optional_set_still_returns_bounded_plan_and_exact_remaining_count(self):
        # 15000 optional IDs fit in a small XML but 2**15000 has >4300
        # decimal digits, exceeding Python's default integer string limit.
        packages = ','.join(f'opt.p{number}' for number in range(15000))
        self.write('target/Defs/large.xml',
                   f'<Defs><ThingDef MayRequireAnyOf="{packages}"/></Defs>')
        plan = plan_dependency_scenarios(self.target, '1.10', max_scenarios=2)
        self.assertEqual(len(plan.optional_mods), 15000)
        self.assertEqual(len(plan.scenarios), 2)
        self.assertEqual(plan.total_scenarios, 1 << 15000)
        self.assertEqual(plan.unexamined_scenarios, (1 << 15000) - 2)
        diagnostic = next(item for item in plan.diagnostics if item.code == 'scenario-limit')
        self.assertLess(len(diagnostic.message), 200)

    def test_nested_findmod_and_mayrequire_recover_only_active_branch_text(self):
        for letter in ('a', 'b'):
            self.write(f'dep-{letter}/About/About.xml', f'''<ModMetaData>
              <name>Dependency {letter}</name><packageId>dep.{letter}</packageId>
              </ModMetaData>''')
        self.write('gate/About/About.xml', '''<ModMetaData><name>Gate</name>
          <packageId>opt.gate</packageId></ModMetaData>''')
        self.write('target/Defs/base.xml', '''<Defs><ThingDef><defName>Base</defName>
          <label>base</label></ThingDef></Defs>''')

        def add(text):
            return f'''<xpath>Defs/ThingDef[defName="Base"]</xpath>
              <value><description>{text}</description></value>'''

        self.write('target/Patches/nested.xml', f'''<Patch>
          <Operation Class="PatchOperationFindMod" MayRequire="opt.gate">
            <mods><li>Dependency a</li></mods>
            <match Class="PatchOperationFindMod"><mods><li>Dependency b</li></mods>
              <match Class="PatchOperationAdd">{add('both')}</match>
              <nomatch Class="PatchOperationAdd">{add('a only')}</nomatch>
            </match>
            <nomatch Class="PatchOperationAdd">{add('without a')}</nomatch>
          </Operation></Patch>''')
        contexts = [self.root / 'dep-a', self.root / 'dep-b', self.root / 'gate']
        plan = plan_dependency_scenarios(self.target, '1.10', context_sources=contexts)
        self.assertEqual(plan.optional_mods, ('dep.a', 'dep.b', 'opt.gate'))
        actual = {}
        for scenario in plan.scenarios:
            active_contexts = [self.root / f'dep-{letter}' for letter in ('a', 'b')
                               if f'dep.{letter}' in scenario.active_mods]
            if 'opt.gate' in scenario.active_mods:
                active_contexts.append(self.root / 'gate')
            result = scan_mod(self.target, game_version='1.10',
                              active_mods=scenario.active_mods, context_sources=active_contexts)
            self.assertEqual({entry.key for entry in result.entries} - {'Base.description'},
                             {'Base.label'})
            actual[scenario.name] = next((entry.english for entry in result.entries
                                         if entry.key == 'Base.description'), None)
        self.assertEqual(actual, {
            'base': None, 'optional:dep.a': None, 'optional:dep.b': None,
            'optional:opt.gate': 'without a', 'optional:dep.a,dep.b': None,
            'optional:dep.a,opt.gate': 'a only',
            'optional:dep.b,opt.gate': 'without a',
            'optional:dep.a,dep.b,opt.gate': 'both',
        })

    def test_nested_mayrequire_under_fixed_parent_does_not_toggle_fixed_mod(self):
        self.write('target/Defs/conditional.xml', '''<Defs>
          <ThingDef MayRequire="opt.parent"><defName>Conditional</defName>
            <label>conditional</label><description MayRequire="opt.child">child text</description>
          </ThingDef></Defs>''')
        plan = plan_dependency_scenarios(self.target, '1.9', base_active_mods={'opt.parent'})
        self.assertEqual(plan.optional_mods, ('opt.child',))
        actual = {}
        for scenario in plan.scenarios:
            self.assertIn('opt.parent', scenario.active_mods)
            result = scan_mod(self.target, game_version='1.9', active_mods=scenario.active_mods)
            actual[scenario.name] = {entry.key for entry in result.entries}
        self.assertEqual(actual, {
            'base': {'Conditional.label'},
            'optional:opt.child': {'Conditional.label', 'Conditional.description'},
        })

    def test_xml_limit_keeps_nested_condition_and_reports_unexplored_files(self):
        self.write('target/Defs/a.xml', '''<Defs><ThingDef><description
          MayRequireAnyOf="opt.a,opt.b">conditional</description></ThingDef></Defs>''')
        self.write('target/Defs/b.xml', '<Defs><ThingDef MayRequire="opt.unread"/></Defs>')
        plan = plan_dependency_scenarios(self.target, '1.10', max_xml_files=1, max_scenarios=2)
        self.assertEqual(plan.optional_mods, ('opt.a', 'opt.b'))
        self.assertEqual(plan.total_scenarios, 4)
        self.assertEqual(plan.unexamined_scenarios, 2)
        self.assertTrue({'condition-file-limit', 'scenario-limit'} <=
                        {item.code for item in plan.diagnostics})


if __name__ == '__main__':
    unittest.main()

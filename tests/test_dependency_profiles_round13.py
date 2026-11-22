"""版フォールバックと条件付き上書きを、依存元文章の非混入と照合する。"""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.dependency_profiles import plan_dependency_scenarios
from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class ConditionalOverrideInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / 'target'
        self.write('target/About/About.xml', '''<ModMetaData>
          <packageId>target.mod</packageId><supportedVersions>
          <li>1.10</li><li>1.8</li><li>1.9</li></supportedVersions>
          <modDependencies><li><packageId>dep.base</packageId></li></modDependencies>
          <modDependenciesByVersion>
            <v1.9><li><packageId>dep.old</packageId></li></v1.9>
            <v1.10><li><packageId>dep.new</packageId></li></v1.10>
          </modDependenciesByVersion></ModMetaData>''')
        self.write('target/LoadFolders.xml', '''<loadFolders>
          <default><li>Common</li></default>
          <v1.9><li>Common</li><li IfModActive="opt.a">Override</li>
            <li IfModNotActive="opt.b">WithoutB</li></v1.9>
          <v1.11><li IfModActive="future.only">Future</li></v1.11>
          </loadFolders>''')
        self.write('target/Common/Defs/item.xml', '''<Defs><ThingDef>
          <defName>Own</defName><label>original own label</label></ThingDef></Defs>''')
        self.write('target/Override/Defs/item.xml', '''<Defs><ThingDef>
          <defName>Own</defName><label>replacement own label</label></ThingDef></Defs>''')
        self.write('target/WithoutB/Defs/absent.xml', '''<Defs><ThingDef>
          <defName>AbsentB</defName><label>without b label</label></ThingDef></Defs>''')
        self.write('target/Future/Defs/future.xml', '''<Defs><ThingDef>
          <defName>Future</defName><label>undeclared branch label</label></ThingDef></Defs>''')
        self.contexts = []
        for name in ('base', 'old', 'new'):
            self.contexts.append(self.root / name)
            self.write(f'{name}/About/About.xml', f'''<ModMetaData>
              <packageId>dep.{name}</packageId></ModMetaData>''')
            self.write(f'{name}/Defs/foreign.xml', f'''<Defs><ThingDef>
              <defName>Foreign{name}</defName><label>foreign {name} label</label>
              <description>foreign {name} original description</description>
              </ThingDef></Defs>''')
            self.write(f'target/Common/Patches/{name}.xml', f'''<Patch>
              <Operation Class="PatchOperationAdd" MayRequire="dep.{name}">
                <xpath>Defs/ThingDef[defName="Foreign{name}"]</xpath>
                <value><labelShort>target addition for {name}</labelShort></value>
              </Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_fallback_planning_does_not_discover_future_branch_conditions(self):
        # Common patches mention all three dependency IDs. The two dependencies
        # not required by this version are optional hypotheses, never required.
        for version, required in [('1.8', 'base'), ('1.9', 'old'), ('1.10', 'new')]:
            with self.subTest(version=version):
                plan = plan_dependency_scenarios(self.target, version, max_scenarios=16)
                expected = {f'dep.{name}' for name in ('base', 'old', 'new')}
                expected.remove(f'dep.{required}')
                if version != '1.8':
                    expected.update(('opt.a', 'opt.b'))
                self.assertEqual(plan.required_mods, (f'dep.{required}',))
                self.assertEqual(set(plan.optional_mods), expected)
                self.assertEqual(plan.total_scenarios, 1 << len(expected))
                self.assertEqual(plan.unexamined_scenarios, 0)
                self.assertNotIn('future.only', plan.optional_mods)

    def test_every_declared_version_and_scenario_has_exact_owned_inventory(self):
        contexts = {version: {'context_sources': self.contexts}
                    for version in ('1.8', '1.9', '1.10')}
        result = scan_declared_scenarios(self.target, contexts=contexts, max_scenarios=16)
        self.assertEqual(result.declared_versions, ['1.8', '1.9', '1.10'])
        self.assertEqual(result.failures, {})
        self.assertEqual({version: len(scans) for version, scans in result.scans.items()},
                         {'1.8': 4, '1.9': 16, '1.10': 16})
        for version, scans in result.scans.items():
            for scenario in result.plans[version].scenarios:
                with self.subTest(version=version, scenario=scenario.name):
                    active = scenario.active_mods
                    expected = {'Own.label': 'replacement own label'
                                if version != '1.8' and 'opt.a' in active
                                else 'original own label'}
                    if version != '1.8' and 'opt.b' not in active:
                        expected['AbsentB.label'] = 'without b label'
                    for name in ('base', 'old', 'new'):
                        if f'dep.{name}' in active:
                            expected[f'Foreign{name}.labelShort'] = f'target addition for {name}'
                    scan = scans[scenario.name]
                    self.assertEqual({entry.key: entry.english for entry in scan.entries}, expected)
                    self.assertTrue(all(entry.source_file.startswith(('Common/', 'Override/', 'WithoutB/'))
                                        for entry in scan.entries))
                    self.assertIn('dependency-context-unverified',
                                  {item['code'] for item in scan.diagnostics})


class ConditionalContextParentTests(unittest.TestCase):
    def test_context_parent_conditions_follow_its_versioned_load_folders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def write(relative, text):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')

            write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
              <supportedVersions><li>1.9</li><li>1.10</li></supportedVersions>
              <modDependencies><li><packageId>dep.parent</packageId></li></modDependencies>
              </ModMetaData>''')
            write('target/Defs/child.xml', '''<Defs><ThingDef ParentName="ConditionalParent">
              <defName>OwnedChild</defName></ThingDef></Defs>''')
            write('parent/About/About.xml', '''<ModMetaData>
              <packageId>dep.parent</packageId></ModMetaData>''')
            write('parent/LoadFolders.xml', '''<loadFolders><v1.9><li>Old</li></v1.9>
              <v1.10><li>New</li></v1.10></loadFolders>''')
            for folder, gate in [('Old', 'opt.old'), ('New', 'opt.new')]:
                write(f'parent/{folder}/Defs/parent.xml', f'''<Defs>
                  <ThingDef Name="ConditionalParent" Abstract="True" MayRequire="{gate}">
                  <label>inherited {folder} label</label></ThingDef></Defs>''')
            options = {'context_sources': [root / 'parent']}
            result = scan_declared_scenarios(
                root / 'target', contexts={v: options for v in ('1.9', '1.10')})
            self.assertEqual(result.failures, {})
            for version, folder, gate in [('1.9', 'Old', 'opt.old'), ('1.10', 'New', 'opt.new')]:
                with self.subTest(version=version):
                    self.assertEqual(result.plans[version].optional_mods, (gate,))
                    self.assertEqual({name: {entry.key: entry.english for entry in scan.entries}
                                      for name, scan in result.scans[version].items()},
                                     {'base': {}, f'optional:{gate}': {
                                         'OwnedChild.label': f'inherited {folder} label'}})

    def test_context_parent_condition_is_explored_for_owned_child_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def write(relative, text):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')

            write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
              <supportedVersions><li>1.9</li><li>1.10</li></supportedVersions>
              <modDependencies><li><packageId>dep.parent</packageId></li></modDependencies>
              </ModMetaData>''')
            write('target/Defs/child.xml', '''<Defs><ThingDef ParentName="ConditionalParent">
              <defName>OwnedChild</defName></ThingDef></Defs>''')
            write('parent/About/About.xml', '''<ModMetaData>
              <packageId>dep.parent</packageId></ModMetaData>''')
            write('parent/Defs/parent.xml', '''<Defs>
              <ThingDef Name="ConditionalParent" Abstract="True" MayRequire="opt.gate">
                <label>conditional inherited label</label></ThingDef>
              <ThingDef><defName>Foreign</defName><label>foreign label</label></ThingDef>
              </Defs>''')
            options = {'context_sources': [root / 'parent']}
            expected = {'OwnedChild.label': 'conditional inherited label'}
            # Establish the concrete missing inventory independently of planning.
            for version in ('1.9', '1.10'):
                manual = scan_mod(root / 'target', game_version=version,
                                  active_mods=['target.mod', 'dep.parent', 'opt.gate'],
                                  **options)
                self.assertEqual({entry.key: entry.english for entry in manual.entries}, expected)
            result = scan_declared_scenarios(
                root / 'target', contexts={v: options for v in ('1.9', '1.10')})
            self.assertEqual(result.failures, {})
            for version in ('1.9', '1.10'):
                with self.subTest(version=version):
                    self.assertEqual(result.plans[version].optional_mods, ('opt.gate',))
                    self.assertEqual({name: {entry.key: entry.english for entry in scan.entries}
                                      for name, scan in result.scans[version].items()},
                                     {'base': {}, 'optional:opt.gate': expected})


class ContextExplorationBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / 'target'
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.10</li></supportedVersions>
          <modDependencies><li><packageId>dep.parent</packageId></li></modDependencies>
          </ModMetaData>''')
        self.write('target/Defs/owned.xml', '''<Defs><ThingDef ParentName="FinalParent">
          <defName>Owned</defName></ThingDef></Defs>''')
        for name in ('parent', 'branch', 'unrelated'):
            self.write(f'{name}/About/About.xml', f'''<ModMetaData>
              <packageId>dep.{name}</packageId></ModMetaData>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_unrelated_supplied_context_does_not_consume_optional_slots(self):
        self.write('parent/Defs/parent.xml', '''<Defs>
          <ThingDef Name="FinalParent" Abstract="True" MayRequire="opt.gate">
          <label>owned inherited label</label></ThingDef></Defs>''')
        self.write('unrelated/Defs/noise.xml', '''<Defs>
          <ThingDef MayRequire="aaa.noise"><label>foreign noise</label></ThingDef></Defs>''')
        self.write('parent/Patches/ignored.xml', '''<Patch>
          <Operation Class="PatchOperationAdd" MayRequire="aaa.context.patch"/>
          </Patch>''')
        plan = plan_dependency_scenarios(
            self.target, '1.10', max_scenarios=2,
            context_sources=[self.root / 'parent', self.root / 'unrelated'])
        self.assertEqual(plan.optional_mods, ('opt.gate',))
        self.assertEqual(plan.total_scenarios, 2)
        self.assertEqual(plan.unexamined_scenarios, 0)

    def test_context_xml_uses_the_same_global_exploration_limit(self):
        self.write('parent/Defs/parent.xml', '''<Defs>
          <ThingDef Name="FinalParent" Abstract="True" MayRequire="opt.gate">
          <label>owned inherited label</label></ThingDef></Defs>''')
        plan = plan_dependency_scenarios(
            self.target, '1.10', max_xml_files=1, context_sources=[self.root / 'parent'])
        self.assertEqual(plan.optional_mods, ())
        self.assertIn('condition-file-limit', {item.code for item in plan.diagnostics})

    def test_context_condition_diagnostic_keeps_its_own_source_path(self):
        self.write('parent/Defs/invalid.xml', '''<Defs>
          <ThingDef MayRequire="invalid package"/></Defs>''')
        plan = plan_dependency_scenarios(
            self.target, '1.10', context_sources=[self.root / 'parent'])
        diagnostic = next(item for item in plan.diagnostics if item.code == 'invalid-package')
        self.assertEqual(diagnostic.source, str(self.root / 'parent/Defs/invalid.xml'))
        self.assertEqual(plan.optional_mods, ())

    def test_newly_possible_supplied_context_is_explored_without_activating_it(self):
        self.write('parent/Defs/branch.xml', '''<Defs>
          <ThingDef Name="Intermediate" Abstract="True" MayRequire="dep.branch"/>
          </Defs>''')
        self.write('branch/Defs/parent.xml', '''<Defs>
          <ThingDef Name="FinalParent" Abstract="True" MayRequire="opt.gate">
          <label>owned inherited label</label></ThingDef></Defs>''')
        result = scan_declared_scenarios(
            self.target, contexts={'1.10': {'context_sources': [
                self.root / 'branch', self.root / 'parent']}}, max_scenarios=4)
        self.assertEqual(result.failures, {})
        plan = result.plans['1.10']
        self.assertEqual(plan.required_mods, ('dep.parent',))
        self.assertEqual(plan.optional_mods, ('dep.branch', 'opt.gate'))
        self.assertEqual({name: {entry.key: entry.english for entry in scan.entries}
                          for name, scan in result.scans['1.10'].items()}, {
                              'base': {}, 'optional:dep.branch': {}, 'optional:opt.gate': {},
                              'optional:dep.branch,opt.gate': {'Owned.label': 'owned inherited label'}})


if __name__ == '__main__':
    unittest.main()

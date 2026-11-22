"""Rejected load-folder conditions must not displace reachable contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.dependency_profiles import plan_dependency_scenarios
from rimworld_translator.multiversion import scan_declared_scenarios


class RejectedConditionPlanningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li><li>2.0</li></supportedVersions>
          </ModMetaData>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def check_reachable_inventory(self, options=None):
        options = options or {}
        expected = {'Actual.label': 'actual conditional label'}
        for version in ('1.9', '1.10', '2.0'):
            direct = scan_mod(self.root / 'target', game_version=version,
                              active_mods=['target.mod', 'dep.parent', 'zzz.real'],
                              **options)
            self.assertEqual({entry.key: entry.english for entry in direct.entries}, expected)
        result = scan_declared_scenarios(
            self.root / 'target', max_scenarios=2,
            contexts={version: options for version in ('1.9', '1.10', '2.0')})
        self.assertEqual(result.failures, {})
        for version in result.declared_versions:
            with self.subTest(version=version):
                plan = result.plans[version]
                self.assertEqual(plan.optional_mods, ('zzz.real',))
                self.assertEqual(plan.unexamined_scenarios, 0)
                self.assertIn('unknown-condition', {item.code for item in plan.diagnostics})
                self.assertEqual({name: {entry.key: entry.english for entry in scan.entries}
                                  for name, scan in result.scans[version].items()},
                                 {'base': {}, 'optional:zzz.real': expected})

    def test_rejected_target_folder_does_not_consume_bounded_scenarios(self):
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9>
          <li IfModUnexpected="anything" IfModActive="aaa.never">Rejected</li>
          <li IfModActive="zzz.real">Actual</li></v1.9></loadFolders>''')
        self.write('target/Rejected/Defs/never.xml', '''<Defs>
          <ThingDef MayRequire="aaa.nested"><defName>Never</defName>
          <label>unreachable label</label></ThingDef></Defs>''')
        self.write('target/Actual/Defs/actual.xml', '''<Defs><ThingDef>
          <defName>Actual</defName><label>actual conditional label</label>
          </ThingDef></Defs>''')
        self.check_reachable_inventory()

    def test_rejected_context_folder_does_not_hide_owned_inherited_label(self):
        self.write('target/Defs/actual.xml', '''<Defs><ThingDef ParentName="Parent">
          <defName>Actual</defName></ThingDef></Defs>''')
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li><li>2.0</li></supportedVersions>
          <modDependencies><li><packageId>dep.parent</packageId></li></modDependencies>
          </ModMetaData>''')
        self.write('parent/About/About.xml', '''<ModMetaData>
          <packageId>dep.parent</packageId></ModMetaData>''')
        self.write('parent/LoadFolders.xml', '''<loadFolders><v1.9>
          <li ifmodFuture="anything" IfModActive="aaa.never">Rejected</li>
          <li IfModActive="zzz.real">Actual</li></v1.9></loadFolders>''')
        self.write('parent/Rejected/Defs/never.xml', '''<Defs>
          <ThingDef MayRequire="aaa.nested"><defName>Never</defName>
          <label>foreign unreachable label</label></ThingDef></Defs>''')
        self.write('parent/Actual/Defs/actual.xml', '''<Defs>
          <ThingDef Name="Parent" Abstract="True"><label>actual conditional label</label>
          </ThingDef><ThingDef><defName>Foreign</defName><label>foreign label</label>
          </ThingDef></Defs>''')
        self.check_reachable_inventory({'context_sources': [self.root / 'parent']})

    def test_unknown_mayrequire_does_not_reject_reachable_folder_or_hide_limit(self):
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.10>
          <li MayRequireFuture="ignored.by.resolver" IfModActive="aaa.real">First</li>
          <li IfModActive="zzz.real">Actual</li></v1.10></loadFolders>''')
        self.write('target/First/Defs/first.xml', '''<Defs><ThingDef>
          <defName>First</defName><label>first conditional label</label></ThingDef></Defs>''')
        self.write('target/Actual/Defs/actual.xml', '''<Defs><ThingDef>
          <defName>Actual</defName><label>actual conditional label</label></ThingDef></Defs>''')
        plan = plan_dependency_scenarios(self.root / 'target', '1.10', max_scenarios=2)
        self.assertEqual(plan.optional_mods, ('aaa.real', 'zzz.real'))
        self.assertEqual(plan.total_scenarios, 4)
        self.assertEqual(plan.unexamined_scenarios, 2)
        self.assertTrue({'unknown-condition', 'scenario-limit'} <=
                        {item.code for item in plan.diagnostics})
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=4)
        self.assertEqual(result.failures, {})
        scans = result.scans['1.10']
        self.assertEqual({entry.key: entry.english for entry in scans['optional:aaa.real'].entries},
                         {'First.label': 'first conditional label'})
        self.assertEqual({entry.key: entry.english
                          for entry in scans['optional:aaa.real,zzz.real'].entries},
                         {'First.label': 'first conditional label',
                          'Actual.label': 'actual conditional label'})


if __name__ == '__main__':
    unittest.main()

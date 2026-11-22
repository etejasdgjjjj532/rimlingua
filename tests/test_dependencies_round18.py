"""Fixed active packages cannot be disabled to activate a load folder."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class FixedNegativeConditionPlanningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li><li>2.0</li></supportedVersions>
          <modDependencies><li><packageId>dep.required</packageId></li></modDependencies>
          </ModMetaData>''')
        self.write('Rejected/Defs/never.xml', '''<Defs><ThingDef MayRequire="aaa.nested">
          <defName>Never</defName><label>unreachable label</label></ThingDef></Defs>''')
        self.write('Actual/Defs/actual.xml', '''<Defs><ThingDef>
          <defName>Actual</defName><label>actual conditional label</label>
          </ThingDef></Defs>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_fixed_negative_folders_cannot_displace_reachable_scenarios(self):
        cases = (
            ('IfModNotActive', 'TARGET.MOD,aaa.never'),
            ('IfModNotActive', 'DEP.REQUIRED;aaa.never'),
            ('IfModNotActive', 'FIXED.USER,aaa.never'),
            ('IfModNotActiveAll', 'target.mod,dep.required;fixed.user'),
        )
        for attribute, packages in cases:
            with self.subTest(attribute=attribute, packages=packages):
                self.write('LoadFolders.xml', f'''<loadFolders><v1.9>
                  <li {attribute}="{packages}">Rejected</li>
                  <li IfModActive="zzz.real">Actual</li></v1.9></loadFolders>''')
                expected = {'Actual.label': 'actual conditional label'}
                active = ['target.mod', 'dep.required', 'fixed.user', 'zzz.real']
                for version in ('1.9', '1.10', '2.0'):
                    direct = scan_mod(self.root, game_version=version, active_mods=active)
                    self.assertEqual({e.key: e.english for e in direct.entries}, expected)
                result = scan_declared_scenarios(
                    self.root, max_scenarios=2,
                    contexts={v: {'active_mods': ['fixed.user']}
                              for v in ('1.9', '1.10', '2.0')})
                self.assertEqual(result.failures, {})
                for version in result.declared_versions:
                    plan = result.plans[version]
                    self.assertEqual(plan.optional_mods, ('zzz.real',))
                    self.assertEqual(plan.unexamined_scenarios, 0)
                    self.assertEqual({name: {e.key: e.english for e in scan.entries}
                                      for name, scan in result.scans[version].items()},
                                     {'base': {}, 'optional:zzz.real': expected})

    def test_optional_negative_and_mayrequire_folders_remain_reachable(self):
        for attribute, packages in (
            ('IfModNotActive', 'aaa.toggle'),
            ('IfModNotActiveAll', 'target.mod,aaa.toggle'),
            ('MayRequire', 'aaa.toggle'),
        ):
            with self.subTest(attribute=attribute):
                self.write('LoadFolders.xml', f'''<loadFolders><v1.9>
                  <li {attribute}="{packages}">Actual</li>
                  </v1.9></loadFolders>''')
                result = scan_declared_scenarios(self.root, max_scenarios=2)
                self.assertEqual(result.failures, {})
                for version in result.declared_versions:
                    self.assertEqual(result.plans[version].optional_mods, ('aaa.toggle',))
                    scans = result.scans[version]
                    present = 'optional:aaa.toggle' if attribute == 'MayRequire' else 'base'
                    absent = 'base' if attribute == 'MayRequire' else 'optional:aaa.toggle'
                    self.assertEqual({e.key: e.english for e in scans[present].entries},
                                     {'Actual.label': 'actual conditional label'})
                    self.assertEqual(scans[absent].entries, [])

    def test_empty_negative_conditions_match_resolver_any_and_all_semantics(self):
        for attribute in ('IfModNotActive', 'IfModNotActiveAll'):
            with self.subTest(attribute=attribute):
                self.write('LoadFolders.xml', f'''<loadFolders><v1.9>
                  <li {attribute}=" , ; ">Rejected</li></v1.9></loadFolders>''')
                direct = scan_mod(self.root, game_version='1.9',
                                  active_mods=['target.mod', 'dep.required', 'aaa.nested'])
                reachable = attribute == 'IfModNotActive'
                expected = {'Never.label': 'unreachable label'} if reachable else {}
                self.assertEqual({e.key: e.english for e in direct.entries}, expected)
                result = scan_declared_scenarios(self.root, max_scenarios=2)
                self.assertEqual(result.failures, {})
                for version in result.declared_versions:
                    plan = result.plans[version]
                    self.assertEqual(plan.optional_mods, ('aaa.nested',) if reachable else ())
                    scans = result.scans[version]
                    self.assertEqual(scans['base'].entries, [])
                    if reachable:
                        self.assertEqual({e.key: e.english
                                          for e in scans['optional:aaa.nested'].entries}, expected)


if __name__ == '__main__':
    unittest.main()

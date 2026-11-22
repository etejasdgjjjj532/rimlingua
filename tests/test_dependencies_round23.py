"""Contradictory optional conditions must not consume exploration slots."""
from itertools import combinations
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class ContradictoryLoadFolderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li><li>2.0</li></supportedVersions>
          <modDependencies><li><packageId>dep.parent</packageId></li></modDependencies>
          </ModMetaData>''')

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def prepare(self, owner, attributes):
        self.write(f'{owner}/LoadFolders.xml', f'''<loadFolders><v1.9>
          <li {attributes}>Rejected</li><li IfModActive="zzz.real">Actual</li>
          </v1.9></loadFolders>''')
        self.write(f'{owner}/Rejected/Defs/never.xml', '''<Defs>
          <ThingDef MayRequire="aaa.nested"><defName>Never</defName>
          <label>unreachable label</label></ThingDef></Defs>''')
        self.write(f'{owner}/Actual/Defs/actual.xml', '''<Defs><ThingDef>
          <defName>Actual</defName><label>actual conditional label</label>
          </ThingDef></Defs>''')

    def test_optional_contradictions_cannot_hide_reachable_target_string(self):
        for attributes in (
            'IfModActive="AAA.TOGGLE" IfModNotActive="aaa.toggle"',
            'IfModActiveAll="aaa.toggle;bbb.toggle" IfModNotActiveAll="aaa.toggle,bbb.toggle"',
            'MayRequire="aaa.toggle" IfModNotActive="aaa.toggle;bbb.toggle"',
            'IfModActiveAny="aaa.toggle,bbb.toggle" IfModNotActive="aaa.toggle;bbb.toggle"',
            'MayRequireAnyOf=" , ; "',
        ):
            with self.subTest(attributes=attributes):
                self.prepare('target', attributes)
                # Exhaust every optional combination independently of the planner.
                for size in range(4):
                    for subset in combinations(('aaa.toggle', 'bbb.toggle', 'aaa.nested'), size):
                        direct = scan_mod(self.root / 'target', game_version='1.9',
                                          active_mods=['target.mod', 'dep.parent', 'zzz.real', *subset])
                        self.assertEqual({e.key: e.english for e in direct.entries},
                                         {'Actual.label': 'actual conditional label'})
                result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
                self.assertEqual(result.failures, {})
                for version in result.declared_versions:
                    self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
                    self.assertEqual(result.plans[version].unexamined_scenarios, 0)
                    self.assertEqual({name: {e.key: e.english for e in scan.entries}
                                      for name, scan in result.scans[version].items()},
                                     {'base': {}, 'optional:zzz.real':
                                      {'Actual.label': 'actual conditional label'}})

    def test_context_contradiction_does_not_hide_target_inherited_string(self):
        self.prepare('parent', 'IfModActive="aaa.toggle" IfModNotActive="aaa.toggle"')
        self.write('parent/About/About.xml', '<ModMetaData><packageId>dep.parent</packageId></ModMetaData>')
        self.write('parent/Actual/Defs/actual.xml', '''<Defs>
          <ThingDef Name="Parent" Abstract="True"><label>owned inherited label</label></ThingDef>
          <ThingDef><defName>Foreign</defName><label>foreign label</label></ThingDef></Defs>''')
        self.write('target/Defs/actual.xml', '''<Defs><ThingDef ParentName="Parent">
          <defName>Actual</defName></ThingDef></Defs>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in ('1.9', '1.10', '2.0')})
        self.assertEqual(result.failures, {})
        for version in result.declared_versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            self.assertEqual({e.key: e.english for e in result.scans[version]['optional:zzz.real'].entries},
                             {'Actual.label': 'owned inherited label'})

    def test_any_positive_and_not_all_remain_reachable(self):
        # Activating aaa alone satisfies both clauses; treating ANY as ALL loses it.
        self.prepare('target', 'IfModActive="aaa.toggle,bbb.toggle" IfModNotActiveAll="aaa.toggle;bbb.toggle"')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=16)
        self.assertEqual(result.failures, {})
        for version in result.declared_versions:
            scans = result.scans[version]
            self.assertEqual({e.key: e.english for e in scans['optional:aaa.nested,aaa.toggle'].entries},
                             {'Never.label': 'unreachable label'})
            self.assertEqual(scans['optional:aaa.nested,aaa.toggle,bbb.toggle'].entries, [])


if __name__ == '__main__':
    unittest.main()

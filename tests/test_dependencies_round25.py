"""Forced ANY/NOT-ALL clauses must not hide reachable owned strings."""
from itertools import combinations
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class ForcedLoadConditionTests(unittest.TestCase):
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

    def prepare(self, owner, attributes):
        self.write(f'{owner}/LoadFolders.xml', f'''<loadFolders><v1.9>
          <li {attributes}>Rejected</li><li IfModActive="zzz.real">Actual</li>
          </v1.9></loadFolders>''')
        self.write(f'{owner}/Rejected/Defs/never.xml', '''<Defs>
          <ThingDef MayRequire="aaa.nested"><defName>Never</defName>
          <label>unreachable label</label></ThingDef></Defs>''')
        self.write(f'{owner}/Actual/Defs/actual.xml', '''<Defs><ThingDef>
          <defName>Owned</defName><label>owned reachable label</label></ThingDef></Defs>''')

    def test_forced_clauses_do_not_displace_reachable_target_string(self):
        for attributes in (
            'IfModActiveAny="aaa.toggle,bbb.toggle" IfModNotActive="aaa.toggle" IfModNotActiveAll="bbb.toggle"',
            'IfModActive="aaa.toggle,bbb.toggle" MayRequire="target.mod" IfModNotActiveAll="target.mod,bbb.toggle" IfModNotActive="aaa.toggle"',
            'MayRequireAnyOf="aaa.toggle,bbb.toggle" IfModActiveAll="ccc.toggle" IfModNotActiveAll="bbb.toggle,ccc.toggle" IfModNotActive="aaa.toggle"',
        ):
            with self.subTest(attributes=attributes):
                self.prepare('target', attributes)
                # All assignments still exclude Rejected; the zzz branch is real.
                for size in range(4):
                    for subset in combinations(('aaa.toggle', 'bbb.toggle', 'ccc.toggle'), size):
                        direct = scan_mod(self.root / 'target', game_version='1.9',
                            active_mods=['target.mod', 'dep.parent', 'zzz.real', 'aaa.nested', *subset])
                        self.assertEqual({e.key: e.english for e in direct.entries},
                                         {'Owned.label': 'owned reachable label'})
                result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
                self.assertEqual(result.failures, {})
                for version in self.versions:
                    plan = result.plans[version]
                    self.assertEqual(plan.optional_mods, ('zzz.real',))
                    self.assertEqual(plan.unexamined_scenarios, 0)
                    self.assertEqual({name: {e.key: e.english for e in scan.entries}
                                      for name, scan in result.scans[version].items()},
                                     {'base': {}, 'optional:zzz.real': {'Owned.label': 'owned reachable label'}})

    def test_forced_context_clauses_do_not_hide_target_added_string(self):
        self.prepare('parent', 'IfModActiveAny="aaa.toggle,bbb.toggle" IfModNotActive="aaa.toggle" IfModNotActiveAll="bbb.toggle"')
        self.write('parent/Actual/Defs/actual.xml', '''<Defs><ThingDef>
          <defName>Foreign</defName><label>foreign ordinary label</label></ThingDef></Defs>''')
        self.write('target/Patches/add.xml', '''<Patch><Operation Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath>
          <value><description>target added description</description></value></Operation></Patch>''')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        options = {'context_sources': [self.root / 'parent']}
        for version in self.versions:
            direct = scan_mod(self.root / 'target', game_version=version,
                active_mods=['target.mod', 'dep.parent', 'zzz.real'], **options)
            self.assertEqual({e.key: e.english for e in direct.entries},
                             {'Foreign.description': 'target added description'})
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2,
            contexts={v: options for v in self.versions})
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            self.assertEqual(result.scans[version]['base'].entries, [])
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries},
                             {'Foreign.description': 'target added description'})
            self.assertEqual({e.source_file for e in entries}, {'Patches/add.xml'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_forced_choice_with_another_available_member_remains_reachable(self):
        self.prepare('target', 'IfModActiveAny="aaa.toggle,bbb.toggle,ccc.toggle" IfModNotActive="aaa.toggle" IfModNotActiveAll="bbb.toggle"')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=32)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            entries = result.scans[version]['optional:aaa.nested,ccc.toggle'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Never.label': 'unreachable label'})
            self.assertEqual(result.scans[version]['optional:aaa.nested,bbb.toggle,ccc.toggle'].entries, [])


if __name__ == '__main__':
    unittest.main()

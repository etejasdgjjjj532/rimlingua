"""Optional context folders are inspected only while their owner is active."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class OptionalContextOwnerPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10', '2.0')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li><li>2.0</li></supportedVersions>
          </ModMetaData>''')
        self.write('target/Defs/own.xml', '''<Defs>
          <ThingDef ParentName="Parent" MayRequire="dep.parent">
          <defName>Owned</defName></ThingDef></Defs>''')
        self.write('parent/About/About.xml', '''<ModMetaData>
          <packageId>dep.parent</packageId></ModMetaData>''')
        self.write('parent/Rejected/Defs/never.xml', '''<Defs>
          <ThingDef MayRequire="aaa.nested"><defName>ForeignNever</defName>
          <label>foreign unreachable label</label></ThingDef></Defs>''')
        self.write('parent/Actual/Defs/parent.xml', '''<Defs>
          <ThingDef Name="Parent" Abstract="True"><label>inherited owned label</label></ThingDef>
          <ThingDef><defName>Foreign</defName><label>foreign ordinary label</label></ThingDef>
          </Defs>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def prepare(self, attributes):
        self.write('parent/LoadFolders.xml', f'''<loadFolders><v1.9>
          <li {attributes}>Rejected</li><li IfModActive="zzz.real">Actual</li>
          </v1.9></loadFolders>''')

    def test_inactive_owner_folder_does_not_displace_owned_inherited_string(self):
        for attributes in (
            'IfModNotActive="DEP.PARENT;aaa.never"',
            'IfModNotActiveAll="dep.parent,target.mod"',
            'IfModActiveAll="aaa.never" IfModNotActiveAll="dep.parent;aaa.never"',
        ):
            with self.subTest(attributes=attributes):
                self.prepare(attributes)
                before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
                # The context is supplied only when active, as in the scenario runner.
                for version in self.versions:
                    direct = scan_mod(self.root / 'target', game_version=version,
                        active_mods=['target.mod', 'dep.parent', 'zzz.real', 'aaa.never', 'aaa.nested'],
                        context_sources=[self.root / 'parent'])
                    self.assertEqual({e.key: e.english for e in direct.entries},
                                     {'Owned.label': 'inherited owned label'})
                result = scan_declared_scenarios(self.root / 'target', max_scenarios=4,
                    contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
                self.assertEqual(result.failures, {})
                for version in self.versions:
                    plan = result.plans[version]
                    self.assertEqual(plan.required_mods, ())
                    self.assertEqual(plan.optional_mods, ('dep.parent', 'zzz.real'))
                    self.assertEqual(plan.unexamined_scenarios, 0)
                    self.assertEqual({name: {e.key: e.english for e in scan.entries}
                                      for name, scan in result.scans[version].items()}, {
                        'base': {}, 'optional:dep.parent': {}, 'optional:zzz.real': {},
                        'optional:dep.parent,zzz.real': {'Owned.label': 'inherited owned label'}})
                    entries = result.scans[version]['optional:dep.parent,zzz.real'].entries
                    self.assertEqual({e.source_file for e in entries}, {'Defs/own.xml'})
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_owner_active_does_not_make_other_optional_packages_fixed(self):
        self.prepare('IfModNotActiveAll="dep.parent;aaa.toggle"')
        self.write('parent/Rejected/Defs/never.xml', '''<Defs>
          <ThingDef Name="Parent" Abstract="True"><label>without toggle label</label></ThingDef>
          <ThingDef><defName>Foreign</defName><label>foreign ordinary label</label></ThingDef>
          </Defs>''')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=8,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        for version in self.versions:
            plan = result.plans[version]
            self.assertEqual(plan.optional_mods, ('aaa.toggle', 'dep.parent', 'zzz.real'))
            scans = result.scans[version]
            self.assertEqual({e.key: e.english for e in scans['optional:dep.parent'].entries},
                             {'Owned.label': 'without toggle label'})
            self.assertEqual(scans['optional:aaa.toggle,dep.parent'].entries, [])
            self.assertEqual(scans['optional:aaa.toggle'].entries, [])
            self.assertEqual({e.key: e.english
                              for e in scans['optional:aaa.toggle,dep.parent,zzz.real'].entries},
                             {'Owned.label': 'inherited owned label'})


if __name__ == '__main__':
    unittest.main()

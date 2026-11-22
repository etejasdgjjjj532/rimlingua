"""Fixed-active LoadFolders guards must not spend optional scenario slots."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_scenarios


class FixedGuardShadowingTests(unittest.TestCase):
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

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def prepare(self, owner, guard):
        self.write(f'{owner}/LoadFolders.xml', f'''<loadFolders><v1.9>
          <li>Low</li><li {guard}>High</li></v1.9></loadFolders>''')
        self.write(f'{owner}/Low/Defs/shared.xml', '''<Defs>
          <ThingDef MayRequire="aaa.phantom"><defName>Hidden</defName>
          <label>hidden text</label></ThingDef></Defs>''')
        self.write(f'{owner}/High/Defs/shared.xml', '<Defs/>')
        self.write(f'{owner}/Low/Defs/real.xml', '''<Defs>
          <ThingDef MayRequire="zzz.real"><defName>Owned</defName>
          <label>dependency label</label></ThingDef></Defs>''')

    def test_fixed_positive_guards_do_not_displace_target_strings(self):
        guards = (
            'IfModActive="TARGET.MOD,dep.optional"',
            'IfModActiveAny="dep.optional;dep.parent"',
            'IfModActiveAll="target.mod,dep.parent"',
            'MayRequire="target.mod;dep.parent"',
            'MayRequireAnyOf="dep.parent,target.mod"',
        )
        for guard in guards:
            with self.subTest(guard=guard):
                self.prepare('target', guard)
                before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
                for version in self.versions:
                    direct = scan_mod(self.root / 'target', game_version=version,
                        active_mods=['target.mod', 'dep.parent', 'dep.optional',
                                     'aaa.phantom', 'zzz.real'])
                    self.assertEqual({e.key: e.english for e in direct.entries},
                                     {'Owned.label': 'dependency label'})
                result = scan_declared_scenarios(self.root / 'target', max_scenarios=2)
                self.assertEqual(result.failures, {})
                for version in self.versions:
                    # The guard's optional ID may remain a conservative hypothesis;
                    # the permanently hidden Def must never contribute its own ID.
                    self.assertNotIn('aaa.phantom', result.plans[version].optional_mods)
                    if 'dep.optional' not in guard:
                        entries = result.scans[version]['optional:zzz.real'].entries
                        self.assertEqual({e.key: e.english for e in entries},
                                         {'Owned.label': 'dependency label'})
                        self.assertEqual({e.source_file for e in entries}, {'Low/Defs/real.xml'})
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_required_context_guard_keeps_only_target_patch_text(self):
        self.prepare('parent', 'IfModActiveAll="target.mod,dep.parent"')
        self.write('target/Patches/add.xml', '''<Patch><Operation Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Owned"]</xpath><value>
          <description>target description</description></value></Operation></Patch>''')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=2,
            contexts={v: {'context_sources': [self.root / 'parent']} for v in self.versions})
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('zzz.real',))
            entries = result.scans[version]['optional:zzz.real'].entries
            self.assertEqual({e.key: e.english for e in entries},
                             {'Owned.description': 'target description'})
            self.assertEqual({e.source_file for e in entries}, {'Patches/add.xml'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_optional_negative_guard_does_not_permanently_hide_lower_file(self):
        self.prepare('target', 'IfModActive="target.mod" IfModNotActive="zzz.gate"')
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=8)
        self.assertEqual(result.failures, {})
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods,
                             ('aaa.phantom', 'zzz.gate', 'zzz.real'))
            entries = result.scans[version]['optional:aaa.phantom,zzz.gate'].entries
            self.assertEqual({e.key: e.english for e in entries}, {'Hidden.label': 'hidden text'})


if __name__ == '__main__':
    unittest.main()

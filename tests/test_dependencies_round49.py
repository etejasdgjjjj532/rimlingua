"""Guarded FindMod branches must preserve bounded target extraction."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class GuardedFindModPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><name>Target</name>
          <packageId>target.mod</packageId><supportedVersions><li>1.9</li><li>1.10</li>
          </supportedVersions><modDependencies><li><packageId>dep.parent</packageId>
          </li></modDependencies></ModMetaData>''')
        self.write('parent/About/About.xml', '''<ModMetaData><name>Parent</name>
          <packageId>dep.parent</packageId></ModMetaData>''')
        self.write('parent/Defs/base.xml', '''<Defs><ThingDef><defName>Foreign</defName>
          <label>dependency text must not leak</label></ThingDef></Defs>''')
        for folder, name, ident in (('optional', 'Optional', 'zzz.optional'),
                                    ('alternative', 'Alternative', 'yyy.alternative'),
                                    ('decoy', 'Decoy', 'aaa.decoy')):
            self.write(f'{folder}/About/About.xml', f'''<ModMetaData><name>{name}</name>
              <packageId>{ident}</packageId></ModMetaData>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def findmod(self, guard=''):
        return f'''<Operation Class="PatchOperationFindMod" {guard}>
          <mods><li>Optional</li></mods><match Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>target match text</description></value></match>
          <nomatch Class="PatchOperationAdd" MayRequire="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>target nomatch text</labelShort></value></nomatch></Operation>'''

    def scan(self, maximum=2):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=maximum,
            contexts={v: {'context_sources': [self.root / name for name in
                ('parent', 'optional', 'alternative', 'decoy')]} for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(tuple(result.plans), self.versions)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def test_required_findmod_name_excludes_nomatch_at_each_guard_level(self):
        for level in ('operation', 'ancestor', 'folder'):
            with self.subTest(level=level):
                operation = self.findmod('MayRequire="zzz.optional"' if level == 'operation' else '')
                if level == 'ancestor':
                    operation = f'''<Operation Class="PatchOperationSequence" MayRequire="zzz.optional">
                      <operations>{operation}</operations></Operation>'''
                self.write('target/Patches/find.xml', f'<Patch>{operation}</Patch>')
                guard = 'MayRequire="zzz.optional"' if level == 'folder' else ''
                self.write('target/LoadFolders.xml',
                           f'<loadFolders><v1.9><li {guard}>/</li></v1.9></loadFolders>')
                result = self.scan()
                for version in self.versions:
                    extracted = {e.key: (e.english, e.source_file)
                        for scan in result.scans[version].values() for e in scan.entries}
                    self.assertEqual(extracted, {'Foreign.description':
                        ('target match text', 'Patches/find.xml')})
                    self.assertEqual(result.plans[version].optional_mods, ('zzz.optional',))
                    self.assertEqual(result.scans[version]['base'].entries, [])

    def test_any_guard_preserves_reachable_nomatch(self):
        operation = self.findmod('IfModActive="zzz.optional,yyy.alternative"')
        self.write('target/Patches/find.xml', f'<Patch>{operation}</Patch>')
        result = self.scan(8)
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods,
                             ('aaa.decoy', 'yyy.alternative', 'zzz.optional'))
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:aaa.decoy,yyy.alternative'].entries},
                {'Foreign.labelShort': 'target nomatch text'})
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:zzz.optional'].entries},
                {'Foreign.description': 'target match text'})

    def test_unconditional_folder_route_preserves_reachable_nomatch(self):
        self.write('target/Patches/find.xml', f'<Patch>{self.findmod()}</Patch>')
        self.write('target/LoadFolders.xml', '''<loadFolders><v1.9>
          <li MayRequire="zzz.optional">/</li><li>/</li></v1.9></loadFolders>''')
        result = self.scan(4)
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods, ('aaa.decoy', 'zzz.optional'))
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:aaa.decoy'].entries},
                {'Foreign.labelShort': 'target nomatch text'})


if __name__ == '__main__':
    unittest.main()

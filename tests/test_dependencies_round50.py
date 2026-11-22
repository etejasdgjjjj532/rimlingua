"""Excluded FindMod names must not displace reachable target patches."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.multiversion import scan_declared_scenarios


class ExcludedFindModPlanningTests(unittest.TestCase):
    versions = ('1.9', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('target/About/About.xml', '''<ModMetaData><name>Target</name>
          <packageId>target.mod</packageId><supportedVersions><li>1.9</li><li>1.10</li>
          </supportedVersions><modDependencies><li><packageId>dep.parent</packageId>
          </li></modDependencies></ModMetaData>''')
        for folder, name, ident in (('parent', 'Parent', 'dep.parent'),
                                    ('optional', 'Optional', 'yyy.optional'),
                                    ('alternative', 'Alternative', 'xxx.alternative'),
                                    ('real', 'Real', 'zzz.real'),
                                    ('decoy', 'Decoy', 'aaa.decoy')):
            self.write(f'{folder}/About/About.xml', f'''<ModMetaData><name>{name}</name>
              <packageId>{ident}</packageId></ModMetaData>''')
        self.write('parent/Defs/base.xml', '''<Defs><ThingDef><defName>Foreign</defName>
          <label>dependency source must not leak</label></ThingDef></Defs>''')
        self.write('target/Patches/real.xml', '''<Patch><Operation Class="PatchOperationAdd"
          MayRequire="zzz.real"><xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <description>target reachable text</description></value></Operation></Patch>''')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def findmod(self, names=('Optional',), guard=''):
        return f'''<Operation Class="PatchOperationFindMod" {guard}><mods>
          {''.join(f'<li>{name}</li>' for name in names)}</mods>
          <match Class="PatchOperationAdd" MayRequire="aaa.decoy">
          <xpath>Defs/ThingDef[defName="Foreign"]</xpath><value>
          <labelShort>target match text</labelShort></value></match>
          <nomatch Class="PatchOperationTest"><xpath>Defs/ThingDef[defName="Foreign"]
          </xpath></nomatch></Operation>'''

    def scan(self, maximum=3):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        result = scan_declared_scenarios(self.root / 'target', max_scenarios=maximum,
            contexts={v: {'context_sources': [self.root / name for name in
                ('parent', 'optional', 'alternative', 'real', 'decoy')]}
                for v in self.versions})
        self.assertEqual(result.failures, {})
        self.assertEqual(tuple(result.plans), self.versions)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})
        return result

    def test_excluded_findmod_match_does_not_consume_bounded_contexts(self):
        for level in ('operation', 'ancestor', 'folder'):
            with self.subTest(level=level):
                guard = 'IfModNotActive="yyy.optional"'
                operation = self.findmod(guard=guard if level == 'operation' else '')
                if level == 'ancestor':
                    operation = f'''<Operation Class="PatchOperationSequence" {guard}>
                      <operations>{operation}</operations></Operation>'''
                self.write('target/Patches/find.xml', f'<Patch>{operation}</Patch>')
                self.write('target/LoadFolders.xml', f'''<loadFolders><v1.9>
                  <li {guard if level == 'folder' else ''}>/</li>
                  </v1.9></loadFolders>''')
                result = self.scan()
                for version in self.versions:
                    self.assertEqual({e.key: e.english for scan in result.scans[version].values()
                                      for e in scan.entries},
                                     {'Foreign.description': 'target reachable text'})
                    self.assertEqual(result.plans[version].optional_mods,
                                     ('yyy.optional', 'zzz.real'))
                    self.assertEqual({e.key: (e.english, e.source_file) for e in
                        result.scans[version]['optional:zzz.real'].entries}, {
                            'Foreign.description': ('target reachable text', 'Patches/real.xml')})

    def test_one_reachable_display_name_preserves_match_conditions(self):
        operation = self.findmod(('Optional', 'Alternative'),
                                 'IfModNotActive="yyy.optional"')
        self.write('target/Patches/find.xml', f'<Patch>{operation}</Patch>')
        result = self.scan(16)
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods,
                             ('aaa.decoy', 'xxx.alternative', 'yyy.optional', 'zzz.real'))
            self.assertEqual({e.key: e.english for e in
                result.scans[version]['optional:aaa.decoy,xxx.alternative'].entries},
                {'Foreign.labelShort': 'target match text'})

    def test_unknown_display_name_keeps_match_conditions_and_diagnostic(self):
        operation = self.findmod(('Optional', 'Unknown'),
                                 'IfModNotActive="yyy.optional"')
        self.write('target/Patches/find.xml', f'<Patch>{operation}</Patch>')
        result = self.scan()
        for version in self.versions:
            self.assertEqual(result.plans[version].optional_mods,
                             ('aaa.decoy', 'yyy.optional', 'zzz.real'))
            self.assertTrue(any(d.code == 'findmod-context' and 'Unknown' in d.message
                                for d in result.plans[version].diagnostics))


if __name__ == '__main__':
    unittest.main()

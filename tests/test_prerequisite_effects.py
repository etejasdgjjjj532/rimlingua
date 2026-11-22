"""How many rows of a project depend on each found prerequisite MOD."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, Project
from rimworld_translator.prerequisite_effects import prerequisite_effects
from rimworld_translator.scan_context import Prerequisite

SOURCE_DEFS = '''<Defs>
 <ThingDef ParentName="LibBase"><defName>A</defName><label>a</label></ThingDef>
 <ThingDef Name="LocalBase" ParentName="LibBase" Abstract="True"/>
 <ThingDef ParentName="LocalBase"><defName>B</defName><label>b</label></ThingDef>
 <ThingDef ParentName="OwnBase"><defName>C</defName><label>c</label></ThingDef>
 <ThingDef Name="OwnBase" Abstract="True"/>
 <ThingDef><defName>D</defName><label>d</label><description MayRequire="Sample.Lib">dd</description></ThingDef>
 <ThingDef MayRequire="sample.lib,other.mod"><defName>E</defName><label>e</label></ThingDef>
 <ThingDef MayRequire="other.mod"><defName>F</defName><label>f</label></ThingDef>
 <ThingDef><defName>G</defName><label>g</label></ThingDef>
</Defs>'''


def entry(group, key, source_file='Defs/a.xml', evidence=(), kind='DefInjected'):
    return Entry(f'{kind}:{group}:{key}', kind, group, key, key, source_file, evidence=list(evidence))


class EffectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'Defs').mkdir(parents=True)
        (self.source / 'Defs/a.xml').write_text(SOURCE_DEFS)
        self.lib = self.root / 'lib'
        (self.lib / 'Defs').mkdir(parents=True)
        (self.lib / 'Defs/base.xml').write_text('<Defs><ThingDef Name="LibBase" Abstract="True"/></Defs>')
        (self.lib / 'Assemblies').mkdir()
        (self.lib / 'Assemblies/Lib.dll').write_bytes(b'MZ')
        self.entries = [
            entry('ThingDef', 'A.label', evidence=['XML parent: LibBase']),
            entry('ThingDef', 'B.label', evidence=['XML parent: LocalBase']),
            entry('ThingDef', 'C.label', evidence=['XML parent: OwnBase']),
            entry('ThingDef', 'D.label'),
            entry('ThingDef', 'D.description'),
            entry('ThingDef', 'E.label'),
            entry('ThingDef', 'F.label'),
            entry('ThingDef', 'G.label', evidence=['CLR Lib.Widget.label: string field']),
            entry('ThingDef', 'G.other', evidence=['CLR Own.Thing.other: string field']),
        ]
        self.project = Project(str(self.source), 'P', 'local.p', 'sample.src', ['1.6'], self.entries, [], languages=['Japanese'])
        self.prerequisite = Prerequisite('sample.lib', 'Lib', folder=self.lib)

    def compute(self, **kwargs):
        types = kwargs.pop('assembly_types', lambda path: {'Lib.Widget'})
        return prerequisite_effects(self.project, [self.prerequisite], '1.6', assembly_types=types, **kwargs)['sample.lib']

    def test_rows_inheriting_a_parent_defined_in_the_prerequisite(self):
        effect = self.compute()
        # A directly, B through the source's own abstract base; C's parent is the source's own.
        self.assertEqual(effect.parent_rows, 2)
        self.assertIn('DefInjected:ThingDef:A.label', effect.rows)
        self.assertIn('DefInjected:ThingDef:B.label', effect.rows)
        self.assertNotIn('DefInjected:ThingDef:C.label', effect.rows)

    def test_rows_whose_owner_type_comes_from_the_prerequisite_assemblies(self):
        effect = self.compute()
        self.assertEqual(effect.type_rows, 1)
        self.assertIn('DefInjected:ThingDef:G.label', effect.rows)
        self.assertNotIn('DefInjected:ThingDef:G.other', effect.rows)

    def test_rows_in_conditional_blocks_naming_the_prerequisite(self):
        effect = self.compute()
        # D has a nested MayRequire (counted for the whole Def, marked approximate), E a Def-level one, F names another MOD.
        self.assertEqual(effect.conditional_rows, 3)
        self.assertIn('DefInjected:ThingDef:E.label', effect.rows)
        self.assertNotIn('DefInjected:ThingDef:F.label', effect.rows)
        self.assertIn('conditional-def-level', effect.notes)
        self.assertEqual(len(effect.rows), 2 + 1 + 3)

    def test_load_folder_conditions_count_the_rows_in_that_folder(self):
        (self.source / 'Compat').mkdir()
        (self.source / 'LoadFolders.xml').write_text(
            '<loadFolders><default><li>/</li><li IfModActive="sample.lib">Compat</li></default></loadFolders>')
        self.project.entries.append(entry('ThingDef', 'H.label', 'Compat/Defs/h.xml'))
        effect = self.compute()
        self.assertIn('DefInjected:ThingDef:H.label', effect.rows)

    def test_unreadable_assemblies_leave_the_type_count_unknown(self):
        def broken(path):
            raise ValueError('not a managed assembly')
        effect = self.compute(assembly_types=broken)
        self.assertIsNone(effect.type_rows)
        self.assertIn('assemblies-unreadable', effect.notes)
        self.assertEqual(effect.parent_rows, 2)

    def test_prerequisite_without_assemblies_has_zero_type_rows(self):
        (self.lib / 'Assemblies/Lib.dll').unlink()
        effect = self.compute()
        self.assertEqual(effect.type_rows, 0)

    def test_a_type_the_source_defines_itself_is_not_blamed_on_the_prerequisite(self):
        (self.source / 'Assemblies').mkdir()
        (self.source / 'Assemblies/Own.dll').write_bytes(b'MZ')
        types = {'Own.dll': {'Lib.Widget'}, 'Lib.dll': {'Lib.Widget'}}
        effect = self.compute(assembly_types=lambda path: types[Path(path).name])
        self.assertEqual(effect.type_rows, 0)


if __name__ == '__main__':
    unittest.main()

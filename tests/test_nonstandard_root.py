import tempfile
import unittest
from pathlib import Path

from rimworld_translator.extraction import scan
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


class NonStandardRootTests(unittest.TestCase):
    def test_defs_under_a_differently_named_root_are_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'About').mkdir()
            (root / 'About/About.xml').write_text('<ModMetaData><name>T</name><packageId>a.b</packageId></ModMetaData>')
            (root / 'Defs').mkdir()
            (root / 'Defs/tab.xml').write_text(
                '<?xml version="1.0" encoding="utf-8"?><MainTabDefs><MainTabDef><defName>Tab</defName>'
                '<label>Numbers</label><description>See every stat.</description></MainTabDef></MainTabDefs>')
            result = scan(root, '1.6', None, None, None, None, None, (), None)
        keys = {entry.key for entry in result.entries}
        self.assertIn('Tab.label', keys)
        self.assertIn('Tab.description', keys)

    def test_custom_def_class_without_assembly_falls_back_to_the_element_type(self):
        schema = TranslationSchema({'IncidentDef': TypeSpec('IncidentDef', fields={
            'label': FieldSpec('System.String', attributes=('MustTranslateAttribute',)),
            'letterText': FieldSpec('System.String', attributes=('MustTranslateAttribute',))})})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'About').mkdir()
            (root / 'About/About.xml').write_text('<ModMetaData><name>T</name><packageId>a.b</packageId></ModMetaData>')
            (root / 'Defs').mkdir()
            (root / 'Defs/q.xml').write_text(
                '<Defs><IncidentDef Class="Missing.QuestDef"><defName>Q</defName><label>quest</label>'
                '<letterText>Hello there.</letterText><questClass>Missing.Q</questClass></IncidentDef></Defs>')
            result = scan(root, '1.6', None, None, None, None, schema, (), None)
        self.assertEqual({e.key for e in result.entries if e.kind == 'DefInjected'}, {'Q.label', 'Q.letterText'})
        self.assertIn('unresolved-class', {d['code'] for d in result.diagnostics})

    def test_unreadable_subclass_is_read_as_the_base_def_named_by_its_suffix(self):
        schema = TranslationSchema({'BackstoryDef': TypeSpec('BackstoryDef', fields={
            'title': FieldSpec('System.String', attributes=('MustTranslateAttribute',)),
            'titleShort': FieldSpec('System.String', attributes=('MustTranslateAttribute',))})})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'About').mkdir()
            (root / 'About/About.xml').write_text('<ModMetaData><name>T</name><packageId>a.b</packageId></ModMetaData>')
            (root / 'Defs').mkdir()
            (root / 'Defs/b.xml').write_text(
                '<Defs><Other.AlienBackstoryDef><defName>B</defName><title>Mouseling</title>'
                '<titleShort>Mouse</titleShort></Other.AlienBackstoryDef></Defs>')
            result = scan(root, '1.6', None, None, None, None, schema, (), None)
        self.assertEqual({e.key for e in result.entries if e.kind == 'DefInjected'}, {'B.title', 'B.titleShort'})

    def test_base_type_guess_falls_back_to_the_root_def(self):
        from rimworld_translator.extraction import base_type_by_name
        schema = TranslationSchema({'Def': TypeSpec('Def'), 'ThingDef': TypeSpec('ThingDef')})
        self.assertEqual(base_type_by_name(schema, 'Mod.CoolThingDef'), 'ThingDef')
        self.assertEqual(base_type_by_name(schema, 'Mod.CoolDef'), 'Def')
        self.assertEqual(base_type_by_name(schema, 'Mod.Widget'), '')

    def test_unreadable_mod_extension_text_is_offered_for_review(self):
        schema = TranslationSchema({'ThingDef': TypeSpec('ThingDef', fields={
            'label': FieldSpec('System.String', attributes=('MustTranslateAttribute',)),
            'modExtensions': FieldSpec('System.Collections.Generic.List`1<System.Object>', is_list=True)})})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'About').mkdir()
            (root / 'About/About.xml').write_text('<ModMetaData><name>T</name><packageId>a.b</packageId></ModMetaData>')
            (root / 'Defs').mkdir()
            (root / 'Defs/t.xml').write_text(
                '<Defs><ThingDef><defName>T</defName><label>thing</label><modExtensions>'
                '<li Class="Missing.Ext"><ChooseLabel>Choose plant</ChooseLabel><PlantDef>Plant_Rice</PlantDef>'
                '<chooseCount>3</chooseCount><ChooseTag>Single</ChooseTag></li></modExtensions></ThingDef></Defs>')
            result = scan(root, '1.6', None, None, None, None, schema, (), None)
        keys = {e.key for e in result.entries if e.kind == 'DefInjected'}
        self.assertIn('T.modExtensions.0.ChooseLabel', keys)
        # Single words, numbers and non-display names are not guessed at.
        self.assertFalse({k for k in keys if k.endswith(('PlantDef', 'chooseCount', 'ChooseTag'))})

    def test_value_naming_a_dependency_keyed_key_is_not_extracted(self):
        schema = TranslationSchema({'ThingDef': TypeSpec('ThingDef', fields={
            'qualityType': FieldSpec('System.String')})})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            core = base / 'core'
            (core / 'Languages/English/Keyed').mkdir(parents=True)
            (core / 'Languages/English/Keyed/Main.xml').write_text('<LanguageData><Range>range</Range></LanguageData>')
            (core / 'About').mkdir()
            (core / 'About/About.xml').write_text('<ModMetaData><name>C</name><packageId>c.c</packageId></ModMetaData>')
            mod = base / 'mod'
            (mod / 'About').mkdir(parents=True)
            (mod / 'About/About.xml').write_text('<ModMetaData><name>T</name><packageId>a.b</packageId></ModMetaData>')
            (mod / 'Defs').mkdir()
            (mod / 'Defs/t.xml').write_text('<Defs><ThingDef><defName>T</defName><qualityType>Range</qualityType></ThingDef></Defs>')
            result = scan(mod, '1.6', None, None, None, None, schema, (core,), None)
        self.assertEqual([e.key for e in result.entries if e.kind == 'DefInjected'], [])
        self.assertIn('internal-value', {d['code'] for d in result.diagnostics})

    def test_known_type_whose_base_lives_in_another_mods_assembly_still_gets_def_fields(self):
        schema = TranslationSchema({
            'Verse.Def': TypeSpec('Verse.Def', fields={
                'label': FieldSpec('System.String', attributes=('MustTranslateAttribute',)),
                'description': FieldSpec('System.String', attributes=('MustTranslateAttribute',))}),
            'RimWorld.AbilityDef': TypeSpec('RimWorld.AbilityDef', base='Verse.Def'),
            # The base lives in a framework mod's DLL that was not loaded.
            'Mod.ForceAbilityDef': TypeSpec('Mod.ForceAbilityDef', base='Framework.AbilityDef',
                                            fields={'cost': FieldSpec('System.Single')})})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'About').mkdir()
            (root / 'About/About.xml').write_text('<ModMetaData><name>T</name><packageId>a.b</packageId></ModMetaData>')
            (root / 'Defs').mkdir()
            (root / 'Defs/a.xml').write_text('<Defs><Mod.ForceAbilityDef><defName>F</defName><label>Force Rage</label>'
                                             '<description>Enrage an enemy.</description><cost>1</cost></Mod.ForceAbilityDef></Defs>')
            result = scan(root, '1.6', None, None, None, None, schema, (), None)
        self.assertEqual({e.key for e in result.entries if e.kind == 'DefInjected'}, {'F.label', 'F.description'})

    def test_base_named_in_an_old_namespace_still_resolves(self):
        schema = TranslationSchema({
            'Verse.Def': TypeSpec('Verse.Def', fields={'label': FieldSpec('System.String', attributes=('MustTranslateAttribute',))}),
            'RimWorld.BackstoryDef': TypeSpec('RimWorld.BackstoryDef', base='Verse.Def', fields={
                'title': FieldSpec('System.String', attributes=('MustTranslateAttribute',))}),
            'Alien.AlienBackstoryDef': TypeSpec('Alien.AlienBackstoryDef', base='Verse.BackstoryDef')})
        self.assertIn('title', schema.fields_for('Alien.AlienBackstoryDef'))
        self.assertIn('label', schema.fields_for('Alien.AlienBackstoryDef'))
        self.assertIs(schema.find_type('Verse.BackstoryDef'), schema.types['RimWorld.BackstoryDef'])


if __name__ == '__main__':
    unittest.main()

"""Exact RimWorld paths, version selection and conservative engine resolution."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from rimworld_translator.core import scan_mod


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.source.mkdir()

    def xml(self, path, content):
        dest = self.source / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding='utf-8')
        return dest

    def test_version_and_conditions_do_not_create_false_duplicates(self):
        self.xml('LoadFolders.xml', '<loadFolders><v1.5><li>1.5</li></v1.5><v1.6><li>/</li><li>1.6</li><li IfModActive="sample.extra">Extra</li></v1.6></loadFolders>')
        self.xml('1.5/Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>old gun</label></ThingDef></Defs>')
        self.xml('1.6/Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>new gun</label></ThingDef></Defs>')
        self.xml('Extra/Defs/b.xml', '<Defs><ThingDef><defName>Extra</defName><label>extra gun</label></ThingDef></Defs>')
        result = scan_mod(self.source)
        self.assertEqual([e.english for e in result.entries], ['new gun'])
        self.assertFalse(result.entries[0].blocked)
        conditional = scan_mod(self.source, active_mods={'sample.extra'})
        self.assertEqual({e.english for e in conditional.entries}, {'new gun', 'extra gun'})

    def test_same_relative_file_version_overrides_root(self):
        self.xml('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>base gun</label></ThingDef></Defs>')
        self.xml('1.6/Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>version gun</label></ThingDef></Defs>')
        result = scan_mod(self.source)
        self.assertEqual([(e.english,e.blocked) for e in result.entries], [('version gun',False)])

    def test_detected_build_number_uses_major_minor_translation_branch(self):
        from rimworld_translator.core import Project,export_mod
        import xml.etree.ElementTree as ET
        self.xml('LoadFolders.xml','<loadFolders><v1.6><li>1.6</li></v1.6></loadFolders>')
        self.xml('1.6/Defs/a.xml','<Defs><ThingDef><defName>A</defName><label>active label</label></ThingDef></Defs>')
        result = scan_mod(self.source,game_version='1.6.4633')
        self.assertEqual(result.stats['active_version'],'1.6')
        project = Project.create(self.source,result)
        target = self.source.parent/'work/mod'
        export_mod(project,target)
        self.assertEqual(ET.parse(target/'About/About.xml').getroot().findtext('supportedVersions/li'),'1.6')

    def test_if_mod_not_active_excludes_when_any_listed_mod_is_active(self):
        self.xml('LoadFolders.xml', '<loadFolders><v1.6><li>/</li><li IfModNotActive="mod.one,mod.two">Extra</li></v1.6></loadFolders>')
        self.xml('Defs/a.xml', '<Defs><ThingDef><defName>A</defName><label>base</label></ThingDef></Defs>')
        self.xml('Extra/Defs/b.xml', '<Defs><ThingDef><defName>B</defName><label>conditional</label></ThingDef></Defs>')
        excluded = scan_mod(self.source, active_mods={'mod.one'})
        self.assertEqual([e.english for e in excluded.entries], ['base'])
        included = scan_mod(self.source, active_mods=set())
        self.assertEqual({e.english for e in included.entries}, {'base', 'conditional'})

    def test_conditional_list_keys_follow_loaded_items(self):
        self.xml('Defs/a.xml', '<Defs><ThingDef><defName>A</defName><comps><li MayRequire="mod.absent"><label>inactive</label></li><li><label>first live</label></li><li><label>second live</label></li></comps></ThingDef></Defs>')
        result = scan_mod(self.source, active_mods={'ludeon.rimworld'})
        self.assertEqual({e.key:e.english for e in result.entries},
                         {'A.comps.0.label':'first live', 'A.comps.1.label':'second live'})

    def test_conditional_items_do_not_shift_duplicate_handle_suffixes(self):
        from rimworld_translator.schema import FieldSpec, TypeSpec, TranslationSchema
        schema = TranslationSchema({
            'ThingDef':TypeSpec('ThingDef', fields={'comps':FieldSpec('Example.Comp', is_list=True)}),
            'Example.Comp':TypeSpec('Example.Comp', fields={
                'name':FieldSpec('System.String', attributes=('NoTranslateAttribute','TranslationHandleAttribute')),
                'label':FieldSpec('System.String', attributes=('MustTranslateAttribute',))})})
        self.xml('Defs/a.xml', '<Defs><ThingDef><defName>A</defName><comps><li MayRequire="mod.absent"><name>shared</name><label>inactive</label></li><li><name>shared</name><label>first live</label></li><li><name>shared</name><label>second live</label></li></comps></ThingDef></Defs>')
        result = scan_mod(self.source, active_mods=set(), schema=schema)
        self.assertEqual({e.key:e.english for e in result.entries},
                         {'A.comps.shared-0.label':'first live', 'A.comps.shared-1.label':'second live'})

    def test_inheritance_lists_and_inherit_false(self):
        self.xml('Defs/a.xml', '<Defs><ThingDef Name="Base" Abstract="True"><label>base gun</label><description>Base description</description><comps><li Class="CompProperties_Test"><label>base component</label></li></comps></ThingDef><ThingDef ParentName="Base"><defName>Gun</defName><comps Inherit="False"><li Class="CompProperties_Test"><label>child component</label></li></comps></ThingDef></Defs>')
        result = scan_mod(self.source)
        values = {e.key:e.english for e in result.entries}
        self.assertEqual(values.get('Gun.description'), 'Base description')
        self.assertEqual(values.get('Gun.comps.0.label'), 'child component')
        self.assertNotIn('base component', values.values())

    def test_patch_replace_and_unknown_operations_have_evidence(self):
        self.xml('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>old gun</label></ThingDef></Defs>')
        self.xml('Patches/p.xml', '<Patch><Operation Class="PatchOperationReplace"><xpath>Defs/ThingDef[defName="Gun"]/label</xpath><value><label>patched gun</label></value></Operation><Operation Class="CustomPatch"><xpath>Defs</xpath></Operation></Patch>')
        result = scan_mod(self.source)
        self.assertEqual(result.entries[0].english, 'patched gun')
        self.assertTrue(any('CustomPatch' in warning for warning in result.warnings))
        self.assertTrue(result.entries[0].evidence)

    def test_empty_child_container_preserves_inherited_elements(self):
        self.xml('Defs/a.xml', '<Defs><ThingDef Name="Base" Abstract="True"><comps><li><label>inherited component</label></li></comps></ThingDef><ThingDef ParentName="Base"><defName>A</defName><comps/></ThingDef><ThingDef ParentName="Base"><defName>B</defName><comps Inherit="False"/></ThingDef></Defs>')
        result = scan_mod(self.source)
        self.assertEqual({e.key:e.english for e in result.entries},
                         {'A.comps.0.label':'inherited component'})

    def test_patch_add_prepend_preserves_value_order_and_list_keys(self):
        self.xml('Defs/a.xml', '<Defs><ThingDef><defName>A</defName><comps><li><label>existing</label></li></comps></ThingDef></Defs>')
        self.xml('Patches/p.xml', '<Patch><Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="A"]/comps</xpath><order>Prepend</order><value><li><label>first prepended</label></li><li><label>second prepended</label></li></value></Operation></Patch>')
        result = scan_mod(self.source)
        self.assertEqual({e.key:e.english for e in result.entries},
                         {'A.comps.0.label':'first prepended', 'A.comps.1.label':'second prepended', 'A.comps.2.label':'existing'})

    def test_schema_excludes_forbidden_fields_and_follows_nested_types(self):
        self.assertIsNotNone(importlib.util.find_spec('rimworld_translator.schema'), 'Metadata schema service is missing')
        from rimworld_translator.schema import FieldSpec, TypeSpec, TranslationSchema
        schema = TranslationSchema({
            'ThingDef': TypeSpec('ThingDef', fields={'label':FieldSpec('System.String', attributes=('MustTranslateAttribute',)), 'description':FieldSpec('System.String', attributes=('NoTranslateAttribute',)), 'comp':FieldSpec('Example.Comp'), 'defName':FieldSpec('System.String', attributes=('NoTranslateAttribute',))}),
            'Example.Comp':TypeSpec('Example.Comp', fields={'menuName':FieldSpec('System.String', attributes=('MustTranslateAttribute',)), 'texture':FieldSpec('System.String', attributes=('NoTranslateAttribute',))})})
        self.xml('Defs/a.xml','<Defs><ThingDef><defName>Gun</defName><label>gun</label><description>Do not translate</description><comp><menuName>menu name</menuName><texture>some/path</texture></comp></ThingDef></Defs>')
        result = scan_mod(self.source, schema=schema)
        self.assertEqual({e.key for e in result.entries}, {'Gun.label','Gun.comp.menuName'})
        self.assertTrue(all(e.confidence == 'schema' for e in result.entries))

    def test_incremental_index_and_cancel(self):
        self.xml('Defs/a.xml','<Defs><ThingDef><defName>A</defName><label>first</label></ThingDef></Defs>')
        self.xml('Defs/b.xml','<Defs><ThingDef><defName>B</defName><label>second</label></ThingDef></Defs>')
        self.assertIsNotNone(importlib.util.find_spec('rimworld_translator.extraction'), 'Incremental engine is missing')
        cache = self.source.parent / 'index.sqlite'
        first = scan_mod(self.source, cache_path=cache)
        second = scan_mod(self.source, cache_path=cache)
        self.assertEqual(first.stats['parsed_files'], 2)
        self.assertEqual(second.stats['parsed_files'], 0)
        self.assertEqual(second.stats['cached_files'], 2)
        self.xml('Defs/a.xml','<Defs><ThingDef><defName>A</defName><label>changed</label></ThingDef></Defs>')
        third = scan_mod(self.source, cache_path=cache)
        self.assertEqual(third.stats['parsed_files'], 1)
        self.assertEqual(next(e.english for e in third.entries if e.key=='A.label'), 'changed')
        from rimworld_translator.extraction import ScanCancelled
        with self.assertRaises(ScanCancelled):
            scan_mod(self.source, cache_path=cache, cancel=lambda: True)


if __name__ == '__main__':
    unittest.main()

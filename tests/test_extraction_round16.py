"""Explicit XML nulls cannot supply translatable object/string values."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod


class XmlNullExtractionTests(unittest.TestCase):
    versions = ('1.3', '1.4', '1.5', '1.6', '1.9', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.context = self.root / 'context'
        self.cache = self.root / 'cache.sqlite'
        self.clear_memory()
        self.addCleanup(self.clear_memory)
        self.write(self.source, 'About/About.xml',
                   '<ModMetaData><packageId>test.xml.null</packageId><supportedVersions>'
                   + ''.join('<li>' + v + '</li>' for v in self.versions)
                   + '</supportedVersions></ModMetaData>')

    @staticmethod
    def clear_memory():
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    @staticmethod
    def write(root, relative, xml):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding='utf-8')

    def assert_modes(self, body, expected, patch='', foreign=False, schema=None):
        self.write(self.context if foreign else self.source, 'Defs/items.xml',
                   '<Defs>' + body + '</Defs>')
        if patch:
            self.write(self.source, 'Patches/null.xml', '<Patch>' + patch + '</Patch>')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        for version in self.versions:
            for mode in ('uncached', 'sqlite-first', 'memory', 'sqlite-restored'):
                with self.subTest(version=version, mode=mode):
                    if mode == 'sqlite-restored':
                        self.clear_memory()
                    result = scan_mod(self.source, game_version=version,
                                      schema=schema,
                                      context_sources=[self.context] if foreign else [],
                                      cache_path=None if mode == 'uncached' else self.cache)
                    self.assertEqual({e.key: e.english for e in result.entries}, expected)
                    if foreign:
                        self.assertTrue(all(e.source_file == 'Patches/null.xml' for e in result.entries))
                    if mode == 'memory':
                        self.assertEqual(result.stats['memory_hits'], 2 if patch else 1)
                    if mode == 'sqlite-restored':
                        self.assertEqual(result.stats['parsed_files'], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_null_scalar_is_excluded_with_exact_attribute_and_case_insensitive_value(self):
        self.assert_modes('<ThingDef><defName>Item</defName><label IsNull="TrUe">ignored label</label>'
                          '<description IsNull="false">visible description</description>'
                          '<labelShort isNull="true">case sensitive attribute</labelShort>'
                          '<labelPlural IsNull=" true ">untrimmed value</labelPlural></ThingDef>',
                          {'Item.description': 'visible description',
                           'Item.labelShort': 'case sensitive attribute',
                           'Item.labelPlural': 'untrimmed value'})

    def test_null_nested_object_does_not_expose_descendant_fields(self):
        self.assert_modes('<ThingDef><defName>Item</defName><label>visible</label>'
                          '<stages IsNull="true"><li><label>ignored stage</label></li></stages>'
                          '</ThingDef>', {'Item.label': 'visible'})

    def test_null_list_container_has_no_translatable_items(self):
        self.assert_modes('<RulePackDef><defName>Rules</defName><rulesStrings IsNull="TRUE">'
                          '<li>ignored rule</li></rulesStrings></RulePackDef>', {})

    def test_null_list_item_keeps_following_item_index(self):
        # ListFromXml still adds the null result, so the next item stays index 1.
        self.assert_modes('<RulePackDef><defName>Rules</defName><rulesStrings>'
                          '<li IsNull="true">ignored rule</li><li>visible rule</li>'
                          '</rulesStrings></RulePackDef>', {'Rules.rulesStrings.1': 'visible rule'})

    def test_null_inherited_field_is_excluded_without_hiding_other_parent_fields(self):
        self.assert_modes('<ThingDef Name="Base" Abstract="True"><label IsNull="true">ignored</label>'
                          '<description>inherited description</description></ThingDef>'
                          '<ThingDef ParentName="Base"><defName>Child</defName></ThingDef>',
                          {'Child.description': 'inherited description'})

    def test_null_object_item_does_not_reserve_duplicate_translation_handle(self):
        from rimworld_translator.schema import FieldSpec, TypeSpec, TranslationSchema
        schema = TranslationSchema({
            'ThingDef': TypeSpec('ThingDef', fields={'comps': FieldSpec('Example.Comp', is_list=True)}),
            'Example.Comp': TypeSpec('Example.Comp', fields={
                'name': FieldSpec('System.String', attributes=('NoTranslateAttribute', 'TranslationHandleAttribute')),
                'label': FieldSpec('System.String')})})
        self.assert_modes('<ThingDef><defName>Item</defName><comps>'
                          '<li IsNull="true"><name>shared</name><label>ignored</label></li>'
                          '<li><name>shared</name><label>visible</label></li></comps></ThingDef>',
                          {'Item.comps.shared.label': 'visible'}, schema=schema)

    def test_null_handle_field_uses_index_without_duplicating_another_items_handle(self):
        from rimworld_translator.schema import FieldSpec, TypeSpec, TranslationSchema
        schema = TranslationSchema({
            'ThingDef': TypeSpec('ThingDef', fields={'comps': FieldSpec('Example.Comp', is_list=True)}),
            'Example.Comp': TypeSpec('Example.Comp', fields={
                'name': FieldSpec('System.String', attributes=('NoTranslateAttribute', 'TranslationHandleAttribute')),
                'label': FieldSpec('System.String')})})
        self.assert_modes('<ThingDef><defName>Item</defName><comps>'
                          '<li><name IsNull="TRUE">shared</name><label>indexed</label></li>'
                          '<li><name>shared</name><label>named</label></li></comps></ThingDef>',
                          {'Item.comps.0.label': 'indexed', 'Item.comps.shared.label': 'named'}, schema=schema)

    def test_null_body_part_label_does_not_become_postload_translation_handle(self):
        from rimworld_translator.schema import FieldSpec, TypeSpec, TranslationSchema
        schema = TranslationSchema({
            'BodyDef': TypeSpec('BodyDef', fields={'corePart': FieldSpec('Verse.BodyPartRecord')}),
            'Verse.BodyPartRecord': TypeSpec('Verse.BodyPartRecord', fields={
                'def': FieldSpec('Verse.BodyPartDef', attributes=('TranslationHandleAttribute',)),
                'customLabel': FieldSpec('System.String'),
                'untranslatedCustomLabel': FieldSpec('System.String',
                    attributes=('UnsavedAttribute', 'TranslationHandleAttribute'), handle_priority=100),
                'parts': FieldSpec('Verse.BodyPartRecord', is_list=True)})})
        self.assert_modes('<BodyDef><defName>Body</defName><corePart><def>Core</def><parts>'
                          '<li><def>Hand</def><customLabel IsNull="true">ignored</customLabel><parts>'
                          '<li><def>Finger</def><customLabel>finger</customLabel></li>'
                          '</parts></li></parts></corePart></BodyDef>',
                          {'Body.corePart.parts.Hand.parts.finger.customLabel': 'finger'}, schema=schema)

    def test_null_attribute_patch_suppresses_target_text_without_claiming_foreign_text(self):
        self.assert_modes('<ThingDef><defName>External</defName><label>foreign label</label>'
                          '<description>foreign description</description></ThingDef>',
                          {'External.labelShort': 'target short label'},
                          '<Operation Class="PatchOperationReplace"><xpath>Defs/ThingDef/description</xpath>'
                          '<value><description>target description</description></value></Operation>'
                          '<Operation Class="PatchOperationAttributeSet"><xpath>Defs/ThingDef/description</xpath>'
                          '<attribute>IsNull</attribute><value>true</value></Operation>'
                          '<Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef</xpath>'
                          '<value><labelShort>target short label</labelShort></value></Operation>', foreign=True)


if __name__ == '__main__':
    unittest.main()

"""Plain string fields do not inherit list/Def-reference MayRequire semantics."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod
from rimworld_translator.schema import FieldSpec, TypeSpec, TranslationSchema


class ScalarRequirementTests(unittest.TestCase):
    versions = ('1.3', '1.4', '1.5', '1.6', '1.9', '1.10')

    def setUp(self):
        self.addCleanup(self.clear_memory)
        self.clear_memory()

    @staticmethod
    def clear_memory():
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def assert_scan(self, body, expected, *, patch='', foreign=False):
        schema = TranslationSchema({
            'ThingDef': TypeSpec('ThingDef', fields={
                'label': FieldSpec('System.String'),
                'description': FieldSpec('System.String'),
                'labels': FieldSpec('System.String', is_list=True),
                'comps': FieldSpec('Example.Comp', is_list=True)}),
            'Example.Comp': TypeSpec('Example.Comp', fields={
                'name': FieldSpec('System.String', attributes=('NoTranslateAttribute', 'TranslationHandleAttribute')),
                'label': FieldSpec('System.String')})})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, context = root / 'source', root / 'context'
            source.mkdir()
            context.mkdir()
            def write(base, relative, text):
                path = base / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')
            write(context if foreign else source, 'Defs/items.xml', '<Defs>' + body + '</Defs>')
            if patch:
                write(source, 'Patches/items.xml', '<Patch>' + patch + '</Patch>')
            before = {p: p.read_bytes() for p in root.rglob('*.xml')}
            for version in self.versions:
                for active in (None, [], ['test.extra']):
                    for mode in ('uncached', 'sqlite-first', 'memory', 'sqlite-restored'):
                        with self.subTest(version=version, active=active, mode=mode):
                            if mode in ('uncached', 'sqlite-restored'):
                                self.clear_memory()
                            result = scan_mod(source, game_version=version, active_mods=active, schema=schema,
                                              context_sources=[context] if foreign else [],
                                              cache_path=None if mode == 'uncached' else root / 'cache.sqlite')
                            self.assertEqual({e.key: e.english for e in result.entries}, expected(active))
                            if foreign:
                                self.assertTrue(all(e.source_file == 'Patches/items.xml' for e in result.entries))
                            if mode == 'memory':
                                self.assertEqual(result.stats['memory_hits'], 1 + bool(patch))
                            if mode == 'sqlite-restored':
                                self.assertEqual(result.stats['parsed_files'], 0)
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*.xml')})

    def test_string_field_requirement_attributes_do_not_remove_loaded_text(self):
        self.assert_scan('<ThingDef><defName>Item</defName>'
                         '<label MayRequire="test.extra">plain label</label>'
                         '<description MayRequireAnyOf="test.extra,test.other">plain description</description>'
                         '</ThingDef>',
                         lambda active: {'Item.label': 'plain label', 'Item.description': 'plain description'})

    def test_list_item_conditions_remain_effective_and_null_still_wins(self):
        self.assert_scan('<ThingDef><defName>Item</defName>'
                         '<label IsNull="true" MayRequire="test.extra">ignored</label>'
                         '<labels><li MayRequire="test.extra">conditional list text</li>'
                         '<li>always list text</li></labels></ThingDef>',
                         lambda active: {'Item.labels.0': 'conditional list text', 'Item.labels.1': 'always list text'}
                         if active else {'Item.labels.0': 'always list text'})

    def test_scalar_requirements_do_not_disagree_with_string_translation_handle(self):
        self.assert_scan('<ThingDef><defName>Item</defName><comps>'
                         '<li MayRequire="test.extra"><name>shared</name><label>conditional item</label></li>'
                         '<li><name MayRequire="test.extra">shared</name><label MayRequire="test.extra">first</label></li>'
                         '<li><name>shared</name><label>second</label></li>'
                         '</comps></ThingDef>',
                         lambda active: {'Item.comps.shared-0.label': 'conditional item',
                                         'Item.comps.shared-1.label': 'first', 'Item.comps.shared-2.label': 'second'}
                         if active else {'Item.comps.shared-0.label': 'first', 'Item.comps.shared-1.label': 'second'})

    def test_patch_added_scalar_remains_target_owned_when_requirement_is_inactive(self):
        self.assert_scan('<ThingDef><defName>External</defName><label>foreign label</label></ThingDef>',
                         lambda active: {'External.description': 'target description'}, foreign=True,
                         patch='<Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef</xpath>'
                         '<value><description MayRequire="test.extra">target description</description></value>'
                         '</Operation>')


if __name__ == '__main__':
    unittest.main()

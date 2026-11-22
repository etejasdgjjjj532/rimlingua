"""Def-level XML nulls are evaluated before object loading and inheritance."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod


class NullDefinitionTests(unittest.TestCase):
    versions = ('1.3', '1.4', '1.5', '1.6', '1.9', '1.10')

    def setUp(self):
        self.clear_memory()
        self.addCleanup(self.clear_memory)

    @staticmethod
    def clear_memory():
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def assert_extracted(self, body, expected, patch='', foreign=False, catalog=''):
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
            if catalog:
                write(source, 'Languages/English/DefInjected/ThingDef/items.xml',
                      '<LanguageData>' + catalog + '</LanguageData>')
            before = {p: p.read_bytes() for p in root.rglob('*.xml')}
            for version in self.versions:
                for mode in ('uncached', 'sqlite-first', 'memory', 'sqlite-restored'):
                    with self.subTest(version=version, mode=mode):
                        if mode in ('uncached', 'sqlite-restored'):
                            self.clear_memory()
                        result = scan_mod(source, game_version=version,
                                          context_sources=[context] if foreign else [],
                                          cache_path=None if mode == 'uncached' else root / 'cache.sqlite')
                        self.assertEqual({e.key: e.english for e in result.entries}, expected)
                        if mode == 'memory':
                            self.assertEqual(result.stats['memory_hits'], 1 + bool(patch) + bool(catalog))
                        if mode == 'sqlite-restored':
                            self.assertEqual(result.stats['parsed_files'], 0)
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*.xml')})

    def test_null_def_suppresses_all_fields_with_exact_null_attribute(self):
        self.assert_extracted(
            '<ThingDef IsNull="TrUe"><defName>Null</defName><label>ignored</label>'
            '<description>ignored too</description></ThingDef>'
            '<ThingDef IsNull="false"><defName>False</defName><label>visible false</label></ThingDef>'
            '<ThingDef isNull="true"><defName>Case</defName><label>visible case</label></ThingDef>'
            '<ThingDef IsNull=" true "><defName>Space</defName><label>visible spaces</label></ThingDef>',
            {'False.label': 'visible false', 'Case.label': 'visible case', 'Space.label': 'visible spaces'})

    def test_null_child_def_does_not_load_inherited_or_own_text(self):
        self.assert_extracted(
            '<ThingDef Name="Base" Abstract="True"><label>inherited label</label></ThingDef>'
            '<ThingDef ParentName="Base" IsNull="true"><defName>Null</defName>'
            '<description>own text</description></ThingDef>'
            '<ThingDef ParentName="Base"><defName>Visible</defName></ThingDef>',
            {'Visible.label': 'inherited label'})

    def test_null_named_parent_remains_available_as_inheritance_template(self):
        # ObjectFromXml checks the original child before resolving its parent XML.
        self.assert_extracted(
            '<ThingDef Name="Base" IsNull="true"><defName>Null</defName><label>template</label></ThingDef>'
            '<ThingDef ParentName="Base"><defName>Visible</defName></ThingDef>',
            {'Visible.label': 'template'})

    def test_null_root_patch_suppresses_target_addition_to_foreign_def(self):
        self.assert_extracted(
            '<ThingDef><defName>External</defName><label>foreign text</label></ThingDef>', {},
            '<Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef</xpath>'
            '<value><description>target text</description></value></Operation>'
            '<Operation Class="PatchOperationAttributeSet"><xpath>Defs/ThingDef</xpath>'
            '<attribute>IsNull</attribute><value>true</value></Operation>', foreign=True)

    def test_catalog_unresolved_candidate_is_not_promoted_to_schema_match(self):
        # A catalog can describe dynamically produced fields: retain its existing
        # review-only unresolved classification even when a static Def is null.
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / 'Defs').mkdir()
            (source / 'Defs/items.xml').write_text(
                '<Defs><ThingDef IsNull="true"><defName>Null</defName><label>ignored</label></ThingDef></Defs>')
            folder = source / 'Languages/English/DefInjected/ThingDef'
            folder.mkdir(parents=True)
            (folder / 'items.xml').write_text('<LanguageData><Null.label>catalog candidate</Null.label></LanguageData>')
            result = scan_mod(source)
            self.assertEqual(len(result.entries), 1)
            entry = result.entries[0]
            self.assertEqual((entry.key, entry.english, entry.confidence, entry.review),
                             ('Null.label', 'catalog candidate', 'catalog', True))
            self.assertEqual(result.stats['catalog_matches'], 0)


if __name__ == '__main__':
    unittest.main()

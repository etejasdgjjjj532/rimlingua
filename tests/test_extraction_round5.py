"""English DefInjected catalogs retain the top-level Def type in subfolders."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod


class NestedDefInjectedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)

    def xml(self, relative, content):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def test_nested_catalog_matches_existing_def_without_false_type_candidate(self):
        self.xml('Defs/items.xml', '<Defs><ThingDef><defName>Desk</defName><label>writing desk</label></ThingDef></Defs>')
        self.xml('Languages/English/DefInjected/ThingDef/Furniture/items.xml',
                 '<LanguageData><Desk.label>writing desk</Desk.label></LanguageData>')

        result = scan_mod(self.source)

        self.assertEqual([(entry.id, entry.english) for entry in result.entries],
                         [('DefInjected:ThingDef:Desk.label', 'writing desk')])
        self.assertEqual(result.stats['catalog_matches'], 1)
        self.assertIn('Existing English catalog match', result.entries[0].evidence)

    def test_unresolved_nested_catalog_keeps_actual_def_type_and_review(self):
        self.xml('Languages/English/DefInjected/ThingDef/Furniture/Small/items.xml',
                 '<LanguageData><Desk.customText>ready to write</Desk.customText></LanguageData>')

        result = scan_mod(self.source)

        self.assertEqual([(entry.id, entry.english, entry.review) for entry in result.entries],
                         [('DefInjected:ThingDef:Desk.customText', 'ready to write', True)])

    def test_folder_named_definjected_is_not_a_legacy_flat_catalog(self):
        self.xml('Languages/English/DefInjected/ThingDef/DefInjected/items.xml',
                 '<LanguageData><Desk.customText>ready to write</Desk.customText></LanguageData>')

        result = scan_mod(self.source)

        self.assertEqual([entry.group for entry in result.entries], ['ThingDef'])
        self.assertFalse(any(item['code'] == 'legacy-catalog' for item in result.diagnostics))

    def test_top_level_and_legacy_catalog_compatibility(self):
        self.xml('Languages/English/DefInjected/ThingDef/items.xml',
                 '<LanguageData><Desk.label>writing desk</Desk.label></LanguageData>')
        self.xml('Languages/English/DefInjected/RecipeDef.xml',
                 '<LanguageData><MakeDesk.label>make a desk</MakeDesk.label></LanguageData>')

        result = scan_mod(self.source)

        self.assertEqual({entry.id for entry in result.entries},
                         {'DefInjected:ThingDef:Desk.label', 'DefInjected:RecipeDef:MakeDesk.label'})
        self.assertEqual(sum(item['code'] == 'legacy-catalog' for item in result.diagnostics), 1)

    def test_nested_catalog_uses_selected_version_content_root(self):
        self.xml('LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6></loadFolders>')
        self.xml('1.6/Languages/English/DefInjected/ThingDef/Furniture/items.xml',
                 '<LanguageData><Desk.customText>current desk</Desk.customText></LanguageData>')
        self.xml('1.5/Languages/English/DefInjected/ThingDef/Furniture/items.xml',
                 '<LanguageData><Desk.customText>old desk</Desk.customText></LanguageData>')

        result = scan_mod(self.source, game_version='1.6')

        self.assertEqual([(entry.id, entry.english) for entry in result.entries],
                         [('DefInjected:ThingDef:Desk.customText', 'current desk')])

    def test_nested_keyed_catalog_retains_keyed_group(self):
        self.xml('Languages/English/Keyed/Furniture/items.xml',
                 '<LanguageData><DeskReady>ready to write</DeskReady></LanguageData>')

        result = scan_mod(self.source)

        self.assertEqual([(entry.id, entry.english) for entry in result.entries],
                         [('Keyed:Keyed:DeskReady', 'ready to write')])


if __name__ == '__main__':
    unittest.main()

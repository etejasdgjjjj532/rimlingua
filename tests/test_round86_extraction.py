"""CE bipod matching tags are not display text, even when typed as strings."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


class BipodMatchingTagTests(unittest.TestCase):
    def test_catalog_without_clr_evidence_cannot_restore_exact_bipod_tag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / 'Languages/English/DefInjected/CombatExtended.BipodCategoryDef/bipods.xml'
            catalog.parent.mkdir(parents=True)
            catalog.write_text('<LanguageData>'
                               '<Probe.bipod_id>Bipod_Token</Probe.bipod_id>'
                               '<Probe.label>Visible label</Probe.label>'
                               '<Probe.bipod_idCaption>Visible caption</Probe.bipod_idCaption>'
                               '</LanguageData>', encoding='utf-8')
            result = scan_mod(root, schema=TranslationSchema())
            self.assertEqual({entry.key for entry in result.entries},
                             {'Probe.label', 'Probe.bipod_idCaption'})
            self.assertEqual([item['entry_id'] for item in result.diagnostics
                              if item['code'] == 'non-localizable-field'],
                             ['DefInjected:CombatExtended.BipodCategoryDef:Probe.bipod_id'])

    def test_declaring_owner_excludes_matching_tag_and_catalog_reentry(self):
        schema = TranslationSchema({
            'Verse.Def': TypeSpec('Verse.Def', fields={
                'label': FieldSpec('System.String'),
                'description': FieldSpec('System.String')}),
            'CombatExtended.BipodCategoryDef': TypeSpec(
                'CombatExtended.BipodCategoryDef', base='Verse.Def', fields={
                    'bipod_id': FieldSpec('System.String')}),
            'Example.DerivedBipod': TypeSpec(
                'Example.DerivedBipod', base='CombatExtended.BipodCategoryDef'),
            'Example.CaptionDef': TypeSpec(
                'Example.CaptionDef', base='CombatExtended.BipodCategoryDef', fields={
                    'bipod_id': FieldSpec('System.String')})})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Defs').mkdir()
            source = root / 'Defs' / 'bipods.xml'
            source.write_text(
                '<Defs><CombatExtended.BipodCategoryDef>'
                '<defName>bipodMagnumMG_LCL</defName><label>Magnum MG</label>'
                '<bipod_id>Bipod_LCL_MagMG</bipod_id></CombatExtended.BipodCategoryDef>'
                '<Example.DerivedBipod><defName>Derived</defName>'
                '<description>Visible bipod description</description>'
                '<bipod_id>Bipod_Derived</bipod_id></Example.DerivedBipod>'
                '<Example.CaptionDef><defName>Caption</defName>'
                '<bipod_id>Visible bipod caption</bipod_id></Example.CaptionDef></Defs>',
                encoding='utf-8')
            catalog = root / 'Languages/English/DefInjected/Example.DerivedBipod/bipods.xml'
            catalog.parent.mkdir(parents=True)
            catalog.write_text('<LanguageData><Derived.bipod_id>Bipod_Derived</Derived.bipod_id>'
                               '</LanguageData>', encoding='utf-8')
            before = source.read_bytes(), catalog.read_bytes()
            result = scan_mod(root, schema=schema)
            self.assertEqual({entry.key: entry.english for entry in result.entries}, {
                'bipodMagnumMG_LCL.label': 'Magnum MG',
                'Derived.description': 'Visible bipod description',
                'Caption.bipod_id': 'Visible bipod caption'})
            self.assertEqual({item['entry_id'] for item in result.diagnostics
                              if item['code'] == 'non-localizable-field'}, {
                'DefInjected:CombatExtended.BipodCategoryDef:bipodMagnumMG_LCL.bipod_id',
                'DefInjected:Example.DerivedBipod:Derived.bipod_id'})
            self.assertEqual((source.read_bytes(), catalog.read_bytes()), before)

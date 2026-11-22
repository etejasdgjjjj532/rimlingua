"""Review evidence for unknown XML lists remains unverified and source-owned."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


class UnknownListReviewTests(unittest.TestCase):
    def test_unknown_list_preserves_loaded_index_owner_and_bounded_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Defs').mkdir()
            long_text = 'Unverified body ' * 400
            source = root / 'Defs' / 'probe.xml'
            source.write_text(
                '<Defs><Example.Def><defName>Probe</defName><label>Visible label</label>'
                '<tooltipLines><li MayRequire="missing.mod">Excluded body</li>'
                '<li IsNull="True">Null body</li><li>  </li><li>42</li><li>'
                + long_text + '</li></tooltipLines><privateLines><li>Private body</li>'
                '</privateLines><numbers><li>7</li></numbers></Example.Def></Defs>')
            before = source.read_bytes()
            schema = TranslationSchema({'Example.Def': TypeSpec('Example.Def', fields={
                'label': FieldSpec('System.String'),
                'privateLines': FieldSpec('System.String', ('NoTranslateAttribute',), is_list=True),
                'numbers': FieldSpec('System.Int32', is_list=True)})})
            result = scan_mod(root, schema=schema, active_mods=[])
            unknown = [d for d in result.diagnostics if d['code'] == 'unknown-field']
            self.assertEqual([d.get('field_path') for d in unknown],
                             ['Probe.tooltipLines.2', 'Probe.tooltipLines.3'])
            self.assertEqual([d['source_text'] for d in unknown], ['42', long_text[:4096]])
            self.assertEqual(unknown[1]['source_text_length'], len(long_text))
            self.assertTrue(unknown[1]['source_text_truncated'])
            self.assertFalse(unknown[0]['source_text_truncated'])
            for diagnostic in unknown:
                self.assertEqual(diagnostic['owner_type'], 'Example.Def')
                self.assertEqual(diagnostic['source_file'], 'Defs/probe.xml')
                self.assertEqual(diagnostic['safety'], 'unverified')
                self.assertEqual(diagnostic['entry_id'], '')
            self.assertEqual({entry.key for entry in result.entries}, {'Probe.label'})
            self.assertEqual(source.read_bytes(), before)

    def test_dependency_list_is_not_claimed_but_target_patch_item_is_reviewable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, dependency = root / 'target', root / 'dependency'
            (target / 'Defs').mkdir(parents=True)
            (target / 'Patches').mkdir()
            (dependency / 'Defs').mkdir(parents=True)
            (dependency / 'Defs' / 'base.xml').write_text(
                '<Defs><Example.Def Name="ForeignBase" Abstract="True"><tooltipLines>'
                '<li>Dependency body</li></tooltipLines></Example.Def></Defs>')
            (target / 'Defs' / 'child.xml').write_text(
                '<Defs><Example.Def ParentName="ForeignBase"><defName>Child</defName>'
                '<label>Visible label</label></Example.Def></Defs>')
            (target / 'Patches' / 'add.xml').write_text(
                '<Patch><Operation Class="PatchOperationAdd">'
                '<xpath>Defs/Example.Def[@Name="ForeignBase"]/tooltipLines</xpath>'
                '<value><li>Target patch body</li></value></Operation></Patch>')
            schema = TranslationSchema({'Example.Def': TypeSpec('Example.Def', fields={
                'label': FieldSpec('System.String')})})
            result = scan_mod(target, schema=schema, context_sources=[dependency])
            unknown = [d for d in result.diagnostics if d['code'] == 'unknown-field']
            self.assertEqual(len(unknown), 1)
            self.assertEqual(unknown[0]['field_path'], 'Child.tooltipLines.1')
            self.assertEqual(unknown[0]['source_text'], 'Target patch body')
            self.assertEqual(unknown[0]['source_file'], 'Patches/add.xml')
            self.assertEqual({entry.key for entry in result.entries}, {'Child.label'})


class CombatExtendedCasingContractsTests(unittest.TestCase):
    def test_exact_declaring_owner_excludes_def_references_and_catalog_reintroduction(self):
        string = lambda: FieldSpec('System.String')
        schema = TranslationSchema({
            'Verse.ThingDef': TypeSpec('Verse.ThingDef', fields={
                'label': string(), 'projectile': FieldSpec('CombatExtended.ProjectilePropertiesCE')}),
            'CombatExtended.ProjectilePropertiesCE': TypeSpec(
                'CombatExtended.ProjectilePropertiesCE', fields={
                    'casingMoteDefname': string(), 'casingFilthDefname': string()}),
            'Example.Derived': TypeSpec('Example.Derived',
                                        base='CombatExtended.ProjectilePropertiesCE'),
            'Example.Visible': TypeSpec('Example.Visible',
                                        base='CombatExtended.ProjectilePropertiesCE', fields={
                                            'casingMoteDefname': string(), 'casingFilthDefname': string()})})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Defs').mkdir()
            (root / 'Defs' / 'probe.xml').write_text(
                '<Defs><ThingDef><defName>Shell</defName><label>Visible shell label</label>'
                '<projectile Class="Example.Derived"><casingMoteDefname>Fleck_Casing</casingMoteDefname>'
                '<casingFilthDefname>Filth_Casing</casingFilthDefname></projectile></ThingDef>'
                '<ThingDef><defName>Visible</defName><projectile Class="Example.Visible">'
                '<casingMoteDefname>Visible casing caption</casingMoteDefname>'
                '<casingFilthDefname>Visible filth caption</casingFilthDefname>'
                '</projectile></ThingDef></Defs>')
            catalog = root / 'Languages/English/DefInjected/ThingDef/probe.xml'
            catalog.parent.mkdir(parents=True)
            catalog.write_text('<LanguageData>'
                               '<Shell.projectile.casingMoteDefname>Fleck_Casing</Shell.projectile.casingMoteDefname>'
                               '</LanguageData>')
            result = scan_mod(root, schema=schema)
            self.assertEqual({entry.key for entry in result.entries}, {
                'Shell.label', 'Visible.projectile.casingMoteDefname',
                'Visible.projectile.casingFilthDefname'})
            rejected = {d['entry_id'] for d in result.diagnostics
                        if d['code'] == 'non-localizable-field'}
            self.assertEqual(rejected, {
                'DefInjected:ThingDef:Shell.projectile.casingMoteDefname',
                'DefInjected:ThingDef:Shell.projectile.casingFilthDefname'})

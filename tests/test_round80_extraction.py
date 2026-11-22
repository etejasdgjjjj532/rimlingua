"""Q6 diagnostics preserve evidence without promoting unverified XML fields."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


class UnknownFieldEvidenceTests(unittest.TestCase):
    def scan(self, body, schema):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'Defs' / 'unknown.xml'
            source.parent.mkdir()
            source.write_text(body, encoding='utf-8')
            before = source.read_bytes()
            result = scan_mod(root, schema=schema)
            self.assertEqual(source.read_bytes(), before)
            return result

    def assert_unverified_evidence(self, result, key, owner, text):
        matches = [item for item in result.diagnostics
                   if item['code'] == 'unknown-field' and item.get('field_path') == key]
        self.assertEqual(len(matches), 1, result.diagnostics)
        diagnostic = matches[0]
        self.assertEqual(diagnostic['owner_type'], owner)
        self.assertEqual(diagnostic['source_text'], text)
        self.assertEqual(diagnostic['source_file'], 'Defs/unknown.xml')
        self.assertEqual(diagnostic['safety'], 'unverified')
        self.assertEqual(diagnostic['entry_id'], '')
        self.assertTrue(diagnostic['suggestion'])
        self.assertNotIn(key, {entry.key for entry in result.entries})

    def test_known_owner_missing_field_retains_review_evidence(self):
        schema = TranslationSchema({'Example.Def': TypeSpec('Example.Def', fields={
            'label': FieldSpec('System.String')})})
        result = self.scan('<Defs><Example.Def><defName>Probe</defName>'
                           '<label>visible label</label><tooltipText>Gain speed &amp; accuracy</tooltipText>'
                           '</Example.Def></Defs>', schema)
        self.assert_unverified_evidence(result, 'Probe.tooltipText', 'Example.Def',
                                        'Gain speed & accuracy')
        self.assertEqual({entry.key for entry in result.entries}, {'Probe.label'})

    def test_unknown_owner_retains_nonstandard_text_without_creating_entry(self):
        result = self.scan('<Defs><Example.UnknownDef><defName>Probe</defName>'
                           '<label>visible label</label><tooltipText>  Visible\ntext  </tooltipText>'
                           '<runtimeToken>Internal_Ref</runtimeToken>'
                           '</Example.UnknownDef></Defs>', TranslationSchema())
        self.assert_unverified_evidence(result, 'Probe.tooltipText', 'Example.UnknownDef',
                                        '  Visible\ntext  ')
        self.assert_unverified_evidence(result, 'Probe.runtimeToken', 'Example.UnknownDef', 'Internal_Ref')
        self.assertEqual({entry.key for entry in result.entries}, {'Probe.label'})

    def test_unknown_evidence_bounds_large_source_without_hiding_size(self):
        text = 'serialized token ' * 1000
        result = self.scan('<Defs><Example.UnknownDef><defName>Probe</defName><payload>'
                           + text + '</payload></Example.UnknownDef></Defs>', TranslationSchema())
        diagnostic = next(item for item in result.diagnostics if item['code'] == 'unknown-field')
        self.assertEqual(diagnostic['source_text'], text[:4096])
        self.assertEqual(diagnostic['source_text_length'], len(text))
        self.assertTrue(diagnostic['source_text_truncated'])
        self.assertEqual(result.entries, [])

    def test_patch_unknown_evidence_does_not_include_dependency_only_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, dependency = root / 'target', root / 'dependency'
            (target / 'Patches').mkdir(parents=True)
            (dependency / 'Defs').mkdir(parents=True)
            (dependency / 'Defs' / 'foreign.xml').write_text(
                '<Defs><Example.UnknownDef><defName>Foreign</defName>'
                '<privateToken>dependency only</privateToken></Example.UnknownDef></Defs>')
            (target / 'Patches' / 'add.xml').write_text(
                '<Patch><Operation Class="PatchOperationAdd">'
                '<xpath>Defs/Example.UnknownDef[defName="Foreign"]</xpath>'
                '<value><tooltipText>Target patch wording</tooltipText></value>'
                '</Operation></Patch>')
            result = scan_mod(target, schema=TranslationSchema(), context_sources=[dependency])
            diagnostics = [item for item in result.diagnostics if item['code'] == 'unknown-field']
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(diagnostics[0]['field_path'], 'Foreign.tooltipText')
            self.assertEqual(diagnostics[0]['source_file'], 'Patches/add.xml')
            self.assertEqual(diagnostics[0]['source_text'], 'Target patch wording')
            self.assertEqual(result.entries, [])

    def test_target_inheriting_dependency_does_not_claim_dependency_unknown_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, dependency = root / 'target', root / 'dependency'
            (target / 'Defs').mkdir(parents=True)
            (dependency / 'Defs').mkdir(parents=True)
            (dependency / 'Defs' / 'base.xml').write_text(
                '<Defs><Example.UnknownDef Name="ForeignBase" Abstract="True">'
                '<runtimeToken>dependency only</runtimeToken></Example.UnknownDef></Defs>')
            (target / 'Defs' / 'child.xml').write_text(
                '<Defs><Example.UnknownDef ParentName="ForeignBase"><defName>Child</defName>'
                '<tooltipText>Target own wording</tooltipText></Example.UnknownDef></Defs>')
            result = scan_mod(target, schema=TranslationSchema(), context_sources=[dependency])
            diagnostics = [item for item in result.diagnostics if item['code'] == 'unknown-field']
            self.assertEqual([item['field_path'] for item in diagnostics], ['Child.tooltipText'])
            self.assertEqual(diagnostics[0]['source_file'], 'Defs/child.xml')


class HoldoutGD3FieldContractsTests(unittest.TestCase):
    def test_internal_dispatch_asset_and_price_tokens_are_not_translation_entries(self):
        string = lambda: FieldSpec('System.String')
        schema = TranslationSchema({
            'GD3.MechanoidScriptDef': TypeSpec('GD3.MechanoidScriptDef', fields={
                'label': string(), 'priceKind': string(), 'branch': string(),
                'scriptTree': FieldSpec('GD3.ScriptTree', is_list=True)}),
            'GD3.ScriptTree': TypeSpec('GD3.ScriptTree', fields={
                'title': string(), 'dialogue': string(), 'graphic': string(),
                'buttons': FieldSpec('GD3.ScriptButton', is_list=True)}),
            'GD3.ScriptButton': TypeSpec('GD3.ScriptButton', fields={
                'text': string(), 'action': string(), 'branch': string()}),
            'Example.VisibleDef': TypeSpec('Example.VisibleDef', fields={
                'action': string(), 'graphic': string(), 'priceKind': string(), 'branch': string()})})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Defs').mkdir()
            (root / 'Defs' / 'probe.xml').write_text(
                '<Defs><GD3.MechanoidScriptDef><defName>Story</defName><label>visible label</label>'
                '<priceKind>Primary</priceKind><branch>WillMilitorDie</branch><scriptTree><li><title>Visible title</title>'
                '<dialogue>Visible dialogue</dialogue><graphic>Pawn/BLancer_south</graphic>'
                '<buttons><li><text>Visible continue button</text><action>Continue</action><branch>Exact_Branch</branch></li></buttons>'
                '</li></scriptTree></GD3.MechanoidScriptDef>'
                '<Example.VisibleDef><defName>Visible</defName><action>Visible action</action>'
                '<graphic>Visible graphic caption</graphic><priceKind>Visible price caption</priceKind><branch>Visible branch caption</branch>'
                '</Example.VisibleDef></Defs>')
            catalog = root / 'Languages/English/DefInjected/GD3.MechanoidScriptDef/probe.xml'
            catalog.parent.mkdir(parents=True)
            catalog.write_text('<LanguageData><Story.scriptTree.0.buttons.0.action>Continue</Story.scriptTree.0.buttons.0.action></LanguageData>')
            result = scan_mod(root, schema=schema)
            self.assertEqual({entry.key for entry in result.entries}, {
                'Story.label', 'Story.scriptTree.0.title', 'Story.scriptTree.0.dialogue',
                'Story.scriptTree.0.buttons.0.text', 'Visible.action', 'Visible.graphic', 'Visible.priceKind', 'Visible.branch'})
            rejected = [item for item in result.diagnostics if item['code'] == 'non-localizable-field']
            self.assertEqual(len(rejected), 5)

"""Issue #1: typed strings still need owner and field semantics."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


def sos2_schema():
    string = lambda: FieldSpec('System.String')
    strings = lambda: FieldSpec('System.String', is_list=True)
    fields = {
        'SaveOurShip2.ShipDef': {'bigString': string(), 'core': FieldSpec('SaveOurShip2.ShipShape')},
        'SaveOurShip2.ShipShape': {'shapeOrDef': string()},
        'SaveOurShip2.NavyDef': {'colorPrimary': string(), 'colorSecondary': string()},
        'StorytellerDef': {'comps': FieldSpec('RimWorld.StorytellerCompProperties', is_list=True)},
        'RimWorld.StorytellerCompProperties': {'enableIfAnyModActive': strings(), 'disableIfAnyModActive': strings()},
        'ThingDef': {'comps': FieldSpec('Verse.CompProperties', is_list=True)},
        'SaveOurShip2.CompProps_ResearchUnlock': {'unlock': string()},
        'SaveOurShip2.CompProps_Unfold': {'graphicPathAlt': string()},
        'RuleDef': {'resolvers': FieldSpec('RimWorld.BaseGen.SymbolResolver', is_list=True)},
        'SaveOurShip2.SymbolResolver_ShipDebrisRoom': {'interior': string()},
        'ScenarioDef': {'scenario': FieldSpec('RimWorld.Scenario')},
        'RimWorld.Scenario': {'surfaceLayer': FieldSpec('RimWorld.ScenPart_PlanetLayer')},
        'RimWorld.ScenPart_PlanetLayer': {'tag': string()},
        'Verse.HediffDef': {'tags': strings()}, 'Verse.RecipeDef': {'incompatibleWithHediffTags': strings()},
        'ResearchProjectDef': {'generalRules': FieldSpec('Verse.Grammar.RulePack')},
        'Verse.Grammar.RulePack': {'rulesStrings': strings()},
        # Identical field names in an unrelated owner are not evidence of unsafe data.
        'Example.TextDef': {'bigString': string(), 'tags': strings(), 'unlock': string(), 'interior': string()},
    }
    for name, spec in fields.items():
        spec.update(label=string(), description=string())
    return TranslationSchema({name: TypeSpec(name, fields=spec) for name, spec in fields.items()})


class FieldSemanticsExtractionTests(unittest.TestCase):
    body = '''<Defs>
<SaveOurShip2.ShipDef><defName>Ship</defName><label>ship label</label><description>ship description</description><bigString>1,2,0,?|3,4,0,A</bigString><core><shapeOrDef>ShipConsoleTactical</shapeOrDef></core></SaveOurShip2.ShipDef>
<SaveOurShip2.NavyDef><defName>Navy</defName><label>navy label</label><colorPrimary>Structure_Black</colorPrimary><colorSecondary>Structure_Red</colorSecondary></SaveOurShip2.NavyDef>
<StorytellerDef><defName>Story</defName><comps><li><enableIfAnyModActive><li>Ludeon.RimWorld.Ideology</li></enableIfAnyModActive><disableIfAnyModActive><li>example.package</li></disableIfAnyModActive><description>story description</description></li></comps></StorytellerDef>
<ThingDef><defName>Thing</defName><comps><li Class="SaveOurShip2.CompProps_ResearchUnlock"><unlock>ArchotechUplink</unlock><label>unlock display label</label></li><li Class="SaveOurShip2.CompProps_Unfold"><graphicPathAlt>Things/Ship/Tube</graphicPathAlt><description>component description</description></li></comps></ThingDef>
<RuleDef><defName>Rule</defName><resolvers><li Class="SaveOurShip2.SymbolResolver_ShipDebrisRoom"><interior>interior_diningRoom</interior><description>room description</description></li></resolvers></RuleDef>
<ScenarioDef><defName>Scenario</defName><scenario><surfaceLayer><tag>Surface</tag><label>surface display label</label></surfaceLayer></scenario></ScenarioDef>
<HediffDef><defName>Hediff</defName><tags><li>ArmorGland</li></tags><label>hediff display label</label></HediffDef>
<RecipeDef><defName>Recipe</defName><incompatibleWithHediffTags><li>ArmorGland</li></incompatibleWithHediffTags><description>recipe description</description></RecipeDef>
<ResearchProjectDef><defName>Research</defName><generalRules><rulesStrings><li>subject-&gt;starship engineering [PAWN_nameDef]</li></rulesStrings></generalRules></ResearchProjectDef>
<Example.TextDef><defName>Text</defName><bigString>visible long prose</bigString><tags><li>visible tag caption</li></tags><unlock>unlock this text</unlock><interior>inside text</interior></Example.TextDef>
</Defs>'''
    expected = {
        'Ship.label', 'Ship.description', 'Navy.label', 'Story.comps.0.description',
        'Thing.comps.0.label', 'Thing.comps.1.description', 'Rule.resolvers.0.description',
        'Scenario.scenario.surfaceLayer.label', 'Hediff.label', 'Recipe.description',
        'Research.generalRules.rulesStrings.0', 'Text.bigString', 'Text.tags.0', 'Text.unlock', 'Text.interior'}

    def test_all_audited_internal_categories_are_diagnostics_not_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Defs').mkdir()
            source = root / 'Defs/probe.xml'
            source.write_text(self.body, encoding='utf-8')
            before = source.read_bytes()
            result = scan_mod(root, schema=sos2_schema())
            self.assertEqual({entry.key for entry in result.entries}, self.expected)
            diagnostics = [item for item in result.diagnostics if item['code'] == 'non-localizable-field']
            self.assertEqual(len(diagnostics), 12)
            self.assertTrue(all(item['entry_id'].startswith('DefInjected:') for item in diagnostics))
            self.assertEqual(source.read_bytes(), before)

    def test_english_catalog_cannot_reintroduce_known_unsafe_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / 'Languages/English/DefInjected/SaveOurShip2.ShipDef/probe.xml'
            catalog.parent.mkdir(parents=True)
            catalog.write_text('<LanguageData><Ship.bigString>1,2,0,?</Ship.bigString>'
                               '<Ship.label>visible ship</Ship.label></LanguageData>')
            result = scan_mod(root, schema=sos2_schema())
            self.assertEqual({entry.key for entry in result.entries}, {'Ship.label'})


class ForbiddenCatalogReentryTests(unittest.TestCase):
    def test_catalog_cannot_reintroduce_resolved_attribute_excluded_subtrees(self):
        schema = TranslationSchema({
            'ThingDef': TypeSpec('ThingDef', fields={
                'secret': FieldSpec('System.String', attributes=('NoTranslateAttribute',)),
                'cached': FieldSpec('System.String', attributes=('UnsavedAttribute',)),
                'privateData': FieldSpec('Example.Data', attributes=('NoTranslateAttribute',)),
                'label': FieldSpec('System.String')}),
            'Example.Data': TypeSpec('Example.Data', fields={'description': FieldSpec('System.String')})})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Defs').mkdir()
            (root / 'Defs/probe.xml').write_text('<Defs><ThingDef><defName>Ship</defName><secret>token</secret>'
                                               '<cached>cache</cached><privateData><description>private config</description>'
                                               '</privateData><label>visible</label></ThingDef></Defs>')
            catalog = root / 'Languages/English/DefInjected/ThingDef/probe.xml'
            catalog.parent.mkdir(parents=True)
            catalog.write_text('<LanguageData><Ship.secret>token</Ship.secret><Ship.cached>cache</Ship.cached>'
                               '<Ship.privateData.description>private config</Ship.privateData.description>'
                               '<Ship.label>visible</Ship.label></LanguageData>')
            result = scan_mod(root, schema=schema)
            self.assertEqual({entry.key for entry in result.entries}, {'Ship.label'})

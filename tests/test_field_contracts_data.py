"""Known internal field contracts live in a data file; the judgement is unchanged (backlog item 8)."""
import json
import unittest
from importlib import resources

from rimworld_translator import field_semantics
from rimworld_translator.field_semantics import nonlocalizable_reason

OWNED = [
    ('SaveOurShip2.ShipDef', 'Ship.bigString', 'Serialized ship layout, not display text'),
    ('SaveOurShip2.ShipShape', 'Ship.parts.3.shapeOrDef', 'Ship shape / Def reference'),
    ('SaveOurShip2.NavyDef', 'Navy.colorSecondary', 'Named palette reference'),
    ('RimWorld.StorytellerCompProperties', 'Teller.comps.0.enableIfAnyModActive.1', 'MOD package-ID condition'),
    ('SaveOurShip2.CompProps_ResearchUnlock', 'Gun.comps.2.unlock', 'Research unlock identifier'),
    ('SaveOurShip2.SymbolResolver_ShipRoomTriangle2', 'Room.resolvers.0.interior', 'Interior resolver identifier'),
    ('RimWorld.ScenPart_PlanetLayer', 'Scen.scenario.parts.0.tag', 'Scenario planet-layer matching tag'),
    ('Verse.HediffDef', 'Flu.tags.0', 'Hediff compatibility matching tag'),
    ('GD3.ScriptButton', 'Script.buttons.0.action', 'Script control-flow dispatch identifier'),
    ('CombatExtended.ProjectilePropertiesCE', 'Bullet.projectile.casingFilthDefname', 'Casing filth ThingDef reference'),
    ('CombatExtended.BipodCategoryDef', 'Bipod.bipod_id', 'Bipod weapon-tag matching identifier'),
    ('Verse.ThingDef', 'Gun.label', ''),
]
LEGACY = [
    ('CombatExtended.BipodCategoryDef', 'Bipod.bipod_id', 'Bipod weapon-tag matching identifier'),
    ('SaveOurShip2.ShipDef', 'Ship.bigString', 'Serialized ship layout, not display text'),
    ('SaveOurShip2.ShipDef', 'Ship.core.shapeOrDef', 'Ship shape / Def reference'),
    ('SaveOurShip2.ShipDef', 'Ship.core.other', ''),
    ('SaveOurShip2.NavyDef', 'Navy.colorPrimary', 'Named palette reference'),
    ('StorytellerDef', 'Teller.comps.0.disableIfAnyModActive.2', 'MOD package-ID condition'),
    ('RimWorld.StorytellerDef', 'Teller.comps.0.enableIfAnyModActive.0', 'MOD package-ID condition'),
    ('StorytellerDef', 'Teller.comps.0.enableIfAnyModActive', ''),
    ('ThingDef', 'Gun.comps.1.unlock', 'Research unlock identifier; legacy CLR owner requires verification'),
    ('Verse.ThingDef', 'Gun.comps.1.graphicPathAlt', 'Texture asset path; legacy CLR owner requires verification'),
    ('ThingDef', 'Gun.comps.1.label', ''),
    ('RuleDef', 'Room.resolvers.3.interior', 'Interior resolver identifier; legacy CLR owner requires verification'),
    ('ScenarioDef', 'Scen.scenario.surfaceLayer.tag', 'Scenario planet-layer matching tag'),
    ('HediffDef', 'Flu.tags.0', 'Hediff compatibility matching tag'),
    ('Verse.RecipeDef', 'Cure.incompatibleWithHediffTags.1', 'Hediff compatibility matching tag'),
    ('RecipeDef', 'Cure.label', ''),
]


class FieldContractDataTests(unittest.TestCase):
    def test_owned_contracts(self):
        for owner, key, reason in OWNED:
            with self.subTest(owner=owner, key=key):
                self.assertEqual(nonlocalizable_reason('DefInjected', 'Any', key, owner_type=owner), reason)

    def test_legacy_path_contracts(self):
        for group, key, reason in LEGACY:
            with self.subTest(group=group, key=key):
                self.assertEqual(nonlocalizable_reason('DefInjected', group, key), reason)

    def test_attributes_and_other_kinds(self):
        self.assertTrue(nonlocalizable_reason('DefInjected', 'X', 'A.b', attributes=('Verse.NoTranslateAttribute',)))
        self.assertEqual(nonlocalizable_reason('Keyed', 'Keyed', 'Ship.bigString'), '')

    def test_tables_come_from_the_data_file(self):
        data = json.loads(resources.files('rimworld_translator').joinpath('assets/field_contracts.json')
                          .read_text(encoding='utf-8'))
        self.assertEqual(len(data['owned']), 23)
        self.assertTrue(data['legacy'])
        self.assertEqual(field_semantics.contracts()['owned'][('GD3.ScriptTree', 'graphic')],
                         'Script portrait texture asset path')


if __name__ == '__main__':
    unittest.main()

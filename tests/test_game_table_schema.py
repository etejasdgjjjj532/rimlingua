"""The field table read from the user's own game: scans of another version still know game fields by owning class.

The table is never shipped. These tests use a small hand-written table with the real class and field names
(RimWorld 1.6.4871, docs/audits/2026-11-16-game-text-fields), and the installed game when there is one.
"""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.platforms import app_cache_directory, discover_installations
from rimworld_translator.schema import (FieldSpec, TranslationSchema, TypeSpec, game_table_schema,
                                        schema_from_assemblies, schema_from_game_table)

S, MUST, MAY, NO = 'System.String', ('MustTranslateAttribute',), ('MayTranslateAttribute',), ('NoTranslateAttribute',)


def field(type_name=S, attrs=(), is_list=False):
    return FieldSpec(type_name, attrs, is_list)


def table_data():
    """Class -> [base, {field: [type, attributes, is_list]}] in the cache's own format."""
    def row(spec):
        return [spec.type_name, list(spec.attributes), int(spec.is_list)]
    classes = {
        'Verse.Editable': ('System.Object', {}),
        'Verse.Def': ('Verse.Editable', {'defName': field(attrs=NO), 'label': field(attrs=MUST), 'description': field(attrs=MUST),
                                         'descriptionHyperlinks': field('Verse.DefHyperlink', (), True)}),
        'Verse.BuildableDef': ('Verse.Def', {}),
        'Verse.ThingDef': ('Verse.BuildableDef', {'graphicData': field('Verse.GraphicData'),
                                                   'comps': field('Verse.CompProperties', (), True)}),
        'Verse.GraphicData': ('System.Object', {'texPath': field(attrs=NO)}),
        'RimWorld.IncidentDef': ('Verse.Def', {'letterLabel': field(attrs=MUST), 'letterText': field(attrs=MUST)}),
        'Verse.HediffDef': ('Verse.Def', {'labelNoun': field(attrs=MUST), 'stages': field('Verse.HediffStage', (), True),
                                          'comps': field('Verse.HediffCompProperties', (), True)}),
        'Verse.HediffStage': ('System.Object', {'label': field(attrs=MUST)}),
        'Verse.HediffCompProperties': ('System.Object', {}),
        'Verse.HediffCompProperties_TendDuration': ('Verse.HediffCompProperties',
                                                    {'labelTendedWell': field(), 'labelTendedWellInner': field()}),
        'RimWorld.FactionDef': ('Verse.Def', {'leaderTitle': field(attrs=MUST), 'pawnsPlural': field(attrs=MUST)}),
        'RimWorld.BackstoryDef': ('Verse.Def', {'baseDesc': field(attrs=MAY), 'title': field(attrs=MUST),
                                                'titleShort': field(attrs=MUST)}),
    }
    return {'rimworld_version': '1.6.4871 rev598', 'assembly_sha256': 'fixture-table',
            'types': {name: [base, {key: row(spec) for key, spec in fields.items()}] for name, (base, fields) in classes.items()},
            'def_names': ['Sand', 'Gravel', 'Steel'], 'keyed_keys': ['Yes', 'No']}


def builtin_game_schema():
    return schema_from_game_table(table_data())


class GameTableSchemaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / 'source'

    def write(self, defs: str):
        files = {'About/About.xml': '<ModMetaData><packageId>test.builtin</packageId><supportedVersions><li>1.6</li>'
                                    '</supportedVersions></ModMetaData>',
                 'Defs/Defs.xml': f'<Defs>{defs}</Defs>'}
        for relative, content in files.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')

    def keys(self, schema):
        return {entry.key for entry in scan_mod(self.source, schema=schema).entries}

    def test_table_records_its_game_version_and_known_text_fields(self):
        schema = builtin_game_schema()
        self.assertRegex(schema.builtin_version, r'^1\.6\.\d+')
        for owner, names in {'RimWorld.IncidentDef': ('letterText', 'letterLabel'), 'Verse.HediffDef': ('labelNoun',),
                             'RimWorld.FactionDef': ('pawnsPlural', 'leaderTitle'),
                             'RimWorld.BackstoryDef': ('baseDesc', 'title', 'titleShort')}.items():
            for name in names:
                self.assertTrue(schema.find_type(owner).fields[name].translatable, f'{owner}.{name}')
        tend = schema.find_type('Verse.HediffCompProperties_TendDuration').fields
        self.assertTrue(tend['labelTendedWell'].translatable and tend['labelTendedWellInner'].translatable)

    def test_field_is_matched_with_its_owner_not_by_name_alone(self):
        # letterText belongs to IncidentDef. The same tag on a ThingDef is not a ThingDef field and is not extracted.
        self.write('<IncidentDef><defName>Storm</defName><label>storm</label><letterLabel>Storm coming</letterLabel>'
                   '<letterText>A violent storm is about to hit the colony.</letterText></IncidentDef>'
                   '<ThingDef><defName>Rock</defName><label>rock</label>'
                   '<letterText>A violent storm is about to hit the colony.</letterText></ThingDef>')
        keys = self.keys(builtin_game_schema())
        self.assertLessEqual({'Storm.label', 'Storm.letterLabel', 'Storm.letterText', 'Rock.label'}, keys)
        self.assertNotIn('Rock.letterText', keys)
        # Without the table only the short name list applied, and the incident letter was lost.
        self.assertNotIn('Storm.letterText', self.keys(None))

    def test_nested_objects_follow_field_types_and_class_attributes(self):
        self.write('<HediffDef><defName>Burn</defName><label>burn</label><labelNoun>a burn</labelNoun>'
                   '<stages><li><label>minor</label></li></stages>'
                   '<comps><li Class="HediffCompProperties_TendDuration"><labelTendedWell>bandaged</labelTendedWell>'
                   '<labelTendedWellInner>sutured</labelTendedWellInner></li></comps></HediffDef>')
        keys = self.keys(builtin_game_schema())
        self.assertLessEqual({'Burn.labelNoun', 'Burn.stages.0.label', 'Burn.comps.0.labelTendedWell',
                              'Burn.comps.0.labelTendedWellInner'}, keys)

    def test_no_translate_fields_of_game_classes_stay_out(self):
        self.write('<ThingDef><defName>Lamp</defName><label>lamp</label><description>A warm lamp for the room.</description>'
                   '<descriptionHyperlinks><li><def>Steel</def></li></descriptionHyperlinks>'
                   '<graphicData><texPath>Things/Lamp</texPath></graphicData></ThingDef>')
        self.assertEqual(self.keys(builtin_game_schema()), {'Lamp.label', 'Lamp.description'})

    def test_mod_class_extending_a_game_def_inherits_that_defs_fields(self):
        self.write('<My.FactionDefPlus><defName>Raiders</defName><label>raiders</label>'
                   '<pawnsPlural>raiders</pawnsPlural><leaderTitle>warlord</leaderTitle>'
                   '<motto>Take what the rim will not give.</motto><internalTag>RaidersTag</internalTag>'
                   '</My.FactionDefPlus>')
        schema = builtin_game_schema()
        schema.types['My.FactionDefPlus'] = TypeSpec('My.FactionDefPlus', 'RimWorld.FactionDef', {
            'motto': FieldSpec('System.String', ('MustTranslateAttribute',)),
            'internalTag': FieldSpec('System.String', ('NoTranslateAttribute',))})
        self.assertTrue(schema.chain_complete('My.FactionDefPlus'))
        self.assertEqual(schema.field_owner('My.FactionDefPlus', 'leaderTitle'), 'RimWorld.FactionDef')
        self.assertEqual(self.keys(schema), {'Raiders.label', 'Raiders.pawnsPlural', 'Raiders.leaderTitle', 'Raiders.motto'})
        # The MOD's DLL alone knows neither the base class nor these two fields.
        alone = self.keys(TranslationSchema({'My.FactionDefPlus': schema.types['My.FactionDefPlus']}))
        self.assertFalse({'Raiders.pawnsPlural', 'Raiders.leaderTitle'} & alone)

    def test_unreadable_mod_class_is_read_as_the_def_it_is_named_after(self):
        # The subclass's assembly is missing; its name still says which game Def it extends.
        self.write('<Other.AlienBackstoryDef><defName>Drifter</defName><title>drifter</title>'
                   '<titleShort>drifter</titleShort><baseDesc>[PAWN_nameDef] drifted between stations.</baseDesc>'
                   '</Other.AlienBackstoryDef>')
        self.assertLessEqual({'Drifter.title', 'Drifter.titleShort', 'Drifter.baseDesc'}, self.keys(builtin_game_schema()))

    def test_game_def_names_in_unattributed_fields_are_references_without_the_game(self):
        # A MOD class lists terrain by Def name in a plain string list. Sand and Gravel are the game's own Defs,
        # which no file of the MOD defines; only the shipped name list can tell they are references.
        self.write('<My.BiomeRuleDef><defName>Shore</defName><label>shore rule</label>'
                   '<allowedTerrains><li>Sand</li><li>Gravel</li></allowedTerrains>'
                   '<notes><li>Sand here drifts inland.</li></notes></My.BiomeRuleDef>')
        schema = builtin_game_schema()
        self.assertIn('Sand', schema.known_defs)
        self.assertIn('Yes', schema.known_keyed)
        schema.types['My.BiomeRuleDef'] = TypeSpec('My.BiomeRuleDef', 'Verse.Def', {
            'allowedTerrains': FieldSpec('System.String', (), True), 'notes': FieldSpec('System.String', (), True)})
        keys = self.keys(schema)
        self.assertEqual(keys, {'Shore.label', 'Shore.notes.0'})
        # The same class with no name list keeps the single plain words as possible labels.
        bare = TranslationSchema(dict(schema.types))
        self.assertIn('Shore.allowedTerrains.0', self.keys(bare))

    def test_a_label_spelled_like_a_game_def_name_is_still_a_label(self):
        self.write('<ThingDef><defName>MySteelBlock</defName><label>Steel</label></ThingDef>')
        self.assertEqual(self.keys(builtin_game_schema()), {'MySteelBlock.label'})

    def test_own_fields_of_an_unreadable_def_class_fall_back_to_the_known_text_names(self):
        # Source repositories ship no DLL. CombatExtended.AmmoCategoryDef then stands in as Def, which has no
        # labelShort; the field is the class's own and is still one of the names RimWorld uses for shown text.
        self.write('<CombatExtended.AmmoCategoryDef><defName>IncendiaryAP</defName><label>incendiary AP</label>'
                   '<labelShort>AP-I</labelShort><bulletTag>IncendiaryRound</bulletTag>'
                   '</CombatExtended.AmmoCategoryDef>')
        keys = self.keys(builtin_game_schema())
        self.assertEqual(keys, {'IncendiaryAP.label', 'IncendiaryAP.labelShort'})

    def test_numbers_and_def_references_in_unknown_fields_are_not_listed_for_review(self):
        # statBases and descriptionHyperlinks are read by custom loaders, so their children are not CLR fields.
        # Stat values and Def names there can never be wording; a sentence in an unknown field still is listed.
        self.write('<ThingDef><defName>Lamp</defName><label>lamp</label>'
                   '<statBases><Mass>2.5</Mass><Flammability>1</Flammability></statBases>'
                   '<descriptionHyperlinks><ThingDef>Steel</ThingDef></descriptionHyperlinks>'
                   '<modNote>Glows warmly at night.</modNote></ThingDef>')
        result = scan_mod(self.source, schema=builtin_game_schema())
        listed = [item['field_path'] for item in result.diagnostics if item['code'] == 'unknown-field']
        self.assertEqual(listed, ['Lamp.modNote'])

    def test_each_call_returns_an_independent_schema(self):
        first = builtin_game_schema()
        first.types['My.Added'] = TypeSpec('My.Added')
        self.assertNotIn('My.Added', builtin_game_schema().types)

    def test_assemblies_are_layered_over_the_table(self):
        base = builtin_game_schema()
        merged = schema_from_assemblies([], base=base)
        self.assertIs(merged, base)
        self.assertEqual(merged.builtin_version, base.builtin_version)
        self.assertFalse(schema_from_assemblies([]).builtin_version)

    def test_cached_table_is_read_back_without_a_game(self):
        with tempfile.TemporaryDirectory() as folder:
            data = table_data()
            data['assembly_sha256'] = 'from-cache'
            (Path(folder) / 'abc.json.gz').write_bytes(gzip.compress(json.dumps(data).encode()))
            schema = game_table_schema(Path(folder), [])
            self.assertEqual(schema.builtin_version, '1.6.4871 rev598')
            self.assertIn('Sand', schema.known_defs)
            self.assertIsNone(game_table_schema(Path(folder) / 'empty', []))
            self.assertIsNone(game_table_schema(None, []))

    def test_without_cache_or_game_there_is_no_table(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(game_table_schema(Path(folder), [Path(folder) / 'NoGameHere']))

    def test_cache_folder_follows_each_platforms_convention(self):
        home = Path('/home/user')
        self.assertEqual(app_cache_directory('linux', home, {}), home / '.cache/rimworld-translation-editor')
        self.assertEqual(app_cache_directory('linux', home, {'XDG_CACHE_HOME': '/x'}), Path('/x/rimworld-translation-editor'))
        self.assertEqual(app_cache_directory('win32', home, {'LOCALAPPDATA': 'C:/L'}), Path('C:/L/RimWorldTranslationEditor/cache'))
        self.assertEqual(app_cache_directory('darwin', home, {}), home / 'Library/Caches/RimWorldTranslationEditor')

    def test_table_built_from_the_installed_game_matches_the_fixture_classes(self):
        games = discover_installations()
        if not games:
            self.skipTest('no RimWorld installation')
        with tempfile.TemporaryDirectory() as folder:
            first = game_table_schema(Path(folder), [games[0].root])
            self.assertTrue((next(Path(folder).glob('*.json.gz'))).is_file())
            again = game_table_schema(Path(folder), [])        # now from the cache alone
            self.assertEqual(first.builtin_version, again.builtin_version)
            self.assertLessEqual(set(builtin_game_schema().types), set(first.types))
            for owner in ('RimWorld.IncidentDef', 'Verse.HediffDef', 'RimWorld.FactionDef', 'RimWorld.BackstoryDef'):
                self.assertTrue(first.find_type(owner).fields)
            self.assertIn('Sand', first.known_defs)


if __name__ == '__main__':
    unittest.main()

"""Extraction accuracy items (generic rules, never MOD names)."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec

MUST = ('MustTranslateAttribute',)
MAY = ('MayTranslateAttribute',)


def def_schema(**extra_fields):
    fields = {'label': FieldSpec('System.String', MUST), 'description': FieldSpec('System.String', MUST),
              'defName': FieldSpec('System.String')}
    types = {'Verse.Def': TypeSpec('Verse.Def', fields=fields),
             'Verse.ThingDef': TypeSpec('Verse.ThingDef', 'Verse.Def', extra_fields)}
    return TranslationSchema(types)


class ScanCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / 'source'
        self.write('About/About.xml', '<ModMetaData><packageId>test.source</packageId><supportedVersions><li>1.6</li>'
                   '</supportedVersions></ModMetaData>')
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def keys(self, result):
        return {entry.key: entry for entry in result.entries}

    def codes(self, result):
        return [d['code'] for d in result.diagnostics]


class AssumedActiveTests(ScanCase):
    """L1/L2: with an unknown active-MOD list, installed DLCs and found prerequisites count as loaded."""

    def test_dlc_gated_def_is_kept_when_the_dlc_is_assumed_active(self):
        self.write('Defs/a.xml', '<Defs><ThingDef MayRequire="Ludeon.RimWorld.Royalty"><defName>Crown</defName>'
                   '<label>crown</label></ThingDef></Defs>')
        result = scan_mod(self.source, schema=def_schema(), assumed_active=['ludeon.rimworld.royalty'])
        self.assertIn('Crown.label', self.keys(result))
        self.assertIn('conditional-assumed', self.codes(result))

    def test_def_gated_on_an_absent_mod_stays_out(self):
        self.write('Defs/a.xml', '<Defs><ThingDef MayRequire="other.mod"><defName>Compat</defName>'
                   '<label>compat</label></ThingDef></Defs>')
        result = scan_mod(self.source, schema=def_schema(), assumed_active=['ludeon.rimworld.royalty'])
        self.assertNotIn('Compat.label', self.keys(result))

    def test_if_mod_not_active_folder_loads_when_that_mod_is_not_assumed(self):
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li>/</li><li IfModNotActive="other.pharmacy">Pharmacy</li>'
                   '<li IfModActive="other.pharmacy">Compat</li></v1.6></loadFolders>')
        self.write('Pharmacy/Defs/a.xml', '<Defs><ThingDef><defName>Pill</defName><label>pill</label></ThingDef></Defs>')
        self.write('Compat/Defs/a.xml', '<Defs><ThingDef><defName>Bridge</defName><label>bridge</label></ThingDef></Defs>')
        result = scan_mod(self.source, schema=def_schema(), assumed_active=[])
        self.assertIn('Pill.label', self.keys(result))
        self.assertNotIn('Bridge.label', self.keys(result))
        self.assertEqual(result.stats['active_mods'], None)

    def test_the_source_itself_counts_as_active(self):
        self.write('Defs/a.xml', '<Defs><ThingDef MayRequire="test.source"><defName>Own</defName>'
                   '<label>own</label></ThingDef></Defs>')
        result = scan_mod(self.source, schema=def_schema(), assumed_active=[])
        self.assertIn('Own.label', self.keys(result))

    def test_without_assumption_the_old_unknown_behaviour_remains(self):
        self.write('Defs/a.xml', '<Defs><ThingDef MayRequire="Ludeon.RimWorld.Royalty"><defName>Crown</defName>'
                   '<label>crown</label></ThingDef></Defs>')
        result = scan_mod(self.source, schema=def_schema())
        self.assertNotIn('Crown.label', self.keys(result))
        self.assertIn('conditional-context', self.codes(result))

    def test_explicit_profile_wins_over_the_assumption(self):
        self.write('Defs/a.xml', '<Defs><ThingDef MayRequire="Ludeon.RimWorld.Royalty"><defName>Crown</defName>'
                   '<label>crown</label></ThingDef></Defs>')
        result = scan_mod(self.source, active_mods=[], schema=def_schema(), assumed_active=['ludeon.rimworld.royalty'])
        self.assertNotIn('Crown.label', self.keys(result))


def rule_schema():
    """Grammar rules as the game declares them: keyword and path carry MayTranslate."""
    types = def_schema().types
    types['Verse.RulePackDef'] = TypeSpec('Verse.RulePackDef', 'Verse.Def', {'rulePack': FieldSpec('Verse.Grammar.RulePack')})
    types['Verse.Grammar.RulePack'] = TypeSpec('Verse.Grammar.RulePack', fields={
        'rulesRaw': FieldSpec('Verse.Grammar.Rule', is_list=True)})
    types['Verse.Grammar.Rule'] = TypeSpec('Verse.Grammar.Rule', fields={'keyword': FieldSpec('System.String', MAY)})
    types['Verse.Grammar.Rule_File'] = TypeSpec('Verse.Grammar.Rule_File', 'Verse.Grammar.Rule', {
        'path': FieldSpec('System.String', MAY)})
    types['Verse.Grammar.Rule_String'] = TypeSpec('Verse.Grammar.Rule_String', 'Verse.Grammar.Rule', {
        'output': FieldSpec('System.String', MAY)})
    return TranslationSchema(types)


class MayTranslateValueShapeTests(ScanCase):
    """O1: MayTranslate permits translation; it does not make a symbol or a file path wording."""

    def scan_rules(self):
        self.write('Defs/a.xml', '<Defs><RulePackDef><defName>Namer</defName><rulePack><rulesRaw>'
                   '<li Class="Rule_File"><keyword>EldarListA</keyword><path>Eldar_Names/Parts1</path></li>'
                   '<li Class="Rule_String"><keyword>name</keyword><output>the brave one</output></li>'
                   '</rulesRaw></rulePack></RulePackDef></Defs>')
        return scan_mod(self.source, schema=rule_schema())

    def test_identifier_keyword_and_file_path_are_internal(self):
        result = self.scan_rules()
        keys = self.keys(result)
        self.assertNotIn('Namer.rulePack.rulesRaw.0.keyword', keys)
        self.assertNotIn('Namer.rulePack.rulesRaw.0.path', keys)
        kinds = {d['entry_id'].rsplit('.', 1)[-1]: d['value_kind'] for d in result.diagnostics
                 if d['code'] == 'internal-value'}
        self.assertEqual(kinds, {'keyword': 'identifier', 'path': 'path'})

    def test_wording_in_may_translate_fields_stays(self):
        keys = self.keys(self.scan_rules())
        self.assertIn('Namer.rulePack.rulesRaw.1.output', keys)
        # A plain word could be a symbol or a word; it stays a target, with the weaker evidence noted.
        self.assertIn('Namer.rulePack.rulesRaw.1.keyword', keys)

    def test_must_translate_is_still_trusted(self):
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>Mk2_Gun</label></ThingDef></Defs>')
        self.assertIn('Gun.label', self.keys(scan_mod(self.source, schema=def_schema())))


class GridValueTests(ScanCase):
    """Comma-separated map grids are data, never wording, whatever the field is called."""

    def test_grid_rows_of_a_string_list_are_internal(self):
        schema = def_schema(terrainGrid=FieldSpec('System.String', is_list=True))
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Base</defName><label>base</label><terrainGrid>'
                   '<li>.,.,Concrete,Concrete,.</li><li>.,.,.,.,.</li></terrainGrid></ThingDef></Defs>')
        result = scan_mod(self.source, schema=schema)
        self.assertEqual(set(self.keys(result)), {'Base.label'})

    def test_grid_of_an_unknown_field_is_not_listed_for_review(self):
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Base</defName><label>base</label><layout>'
                   '<roofGrid><li>.,.,Roof,Roof,.</li></roofGrid></layout></ThingDef></Defs>')
        result = scan_mod(self.source, schema=def_schema())
        self.assertNotIn('unknown-field', self.codes(result))

    def test_comma_separated_prose_is_still_text(self):
        schema = def_schema(note=FieldSpec('System.String'))
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Base</defName><note>Apples, pears, plums</note>'
                   '</ThingDef></Defs>')
        self.assertIn('Base.note', self.keys(scan_mod(self.source, schema=schema)))


class TokenListTests(ScanCase):
    """O2: an unattributed List<string> of single words used as matching tokens."""

    def test_single_word_items_of_an_unattributed_list_are_internal(self):
        schema = def_schema(allowedBiomes=FieldSpec('System.String', is_list=True))
        # Real scans carry the game's Def name list; without it a game Def name and a label look alike
        # (test_game_table_schema keeps such words for review then).
        schema.known_defs = frozenset({'Steel'})
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Fish</defName><label>fish</label><allowedBiomes>'
                   '<li>Cold</li><li>Warm</li></allowedBiomes></ThingDef></Defs>')
        result = scan_mod(self.source, schema=schema)
        self.assertEqual(set(self.keys(result)), {'Fish.label'})

    def core_context(self):
        core = self.source.parent / 'Core'
        (core / 'About').mkdir(parents=True)
        # The game's own Core About.xml has no <name>.
        (core / 'About/About.xml').write_text('<ModMetaData><packageId>Ludeon.RimWorld</packageId>'
                                              '</ModMetaData>', encoding='utf-8')
        (core / 'Defs').mkdir()
        (core / 'Defs/a.xml').write_text('<Defs><ThingDef><defName>Steel</defName></ThingDef></Defs>', encoding='utf-8')
        return [core]

    def test_the_installed_games_core_as_context_also_supplies_the_name_list(self):
        schema = def_schema(allowedBiomes=FieldSpec('System.String', is_list=True))
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Fish</defName><label>fish</label><allowedBiomes>'
                   '<li>Cold</li></allowedBiomes></ThingDef></Defs>')
        result = scan_mod(self.source, schema=schema, context_sources=self.core_context())
        self.assertEqual(set(self.keys(result)), {'Fish.label'})

    def test_the_mods_own_translation_of_the_key_keeps_the_word(self):
        schema = def_schema(conversationTopics=FieldSpec('System.String', is_list=True))
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Node</defName><label>node</label><conversationTopics>'
                   '<li>engineering</li></conversationTopics></ThingDef></Defs>')
        self.write('Languages/German/DefInjected/ThingDef/a.xml',
                   '<LanguageData><Node.conversationTopics.0>Technik</Node.conversationTopics.0></LanguageData>')
        result = scan_mod(self.source, schema=schema, context_sources=self.core_context())
        self.assertIn('Node.conversationTopics.0', self.keys(result))

    def test_display_named_lists_and_phrases_stay(self):
        schema = def_schema(names=FieldSpec('System.String', is_list=True), notes=FieldSpec('System.String', is_list=True))
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Fish</defName><names><li>Nemo</li></names>'
                   '<notes><li>Swims fast</li></notes></ThingDef></Defs>')
        self.assertEqual(set(self.keys(scan_mod(self.source, schema=schema))), {'Fish.names.0', 'Fish.notes.0'})


class ComparedOnlyFieldTests(ScanCase):
    """Item 2: a one-word value of a field its own assembly only compares (or never reads) is internal."""

    def scan_with_il(self, value, compared):
        from unittest.mock import patch
        schema = def_schema()
        schema.types['Mod.DiseaseDef'] = TypeSpec('Mod.DiseaseDef', 'Verse.Def',
                                                  {'classification': FieldSpec('System.String')})
        self.write('Assemblies/Mod.dll', 'metadata only; never executed')
        self.write('Defs/a.xml', f'<Defs><Mod.DiseaseDef><defName>Flu</defName><label>flu</label>'
                   f'<classification>{value}</classification></Mod.DiseaseDef></Defs>')
        evidence = {'declared': sorted(compared), 'uses': {}, 'unresolved': [], 'complete': True}
        with patch('rimworld_translator.il_candidates.assembly_field_evidence', return_value=evidence), \
                patch('rimworld_translator.il_candidates.compared_only_from_evidence', return_value=compared):
            return scan_mod(self.source, schema=schema)

    def test_unreadable_assembly_voids_the_evidence(self):
        from unittest.mock import patch
        schema = def_schema()
        schema.types['Mod.DiseaseDef'] = TypeSpec('Mod.DiseaseDef', 'Verse.Def',
                                                  {'classification': FieldSpec('System.String')})
        self.write('Assemblies/Mod.dll', 'metadata only; never executed')
        self.write('Defs/a.xml', '<Defs><Mod.DiseaseDef><defName>Flu</defName><label>flu</label>'
                   '<classification>Respiratory</classification></Mod.DiseaseDef></Defs>')
        with patch('rimworld_translator.il_candidates.assembly_field_evidence', side_effect=ValueError('bad')), \
                patch('rimworld_translator.il_candidates.compared_only_from_evidence',
                      return_value={'Mod.DiseaseDef.classification'}) as merged:
            result = scan_mod(self.source, schema=schema)
        self.assertIn('Flu.classification', self.keys(result))
        merged.assert_not_called()

    def test_single_word_is_internal(self):
        result = self.scan_with_il('Respiratory', {'Mod.DiseaseDef.classification'})
        self.assertNotIn('Flu.classification', self.keys(result))
        reasons = [d['message'] for d in result.diagnostics if d['code'] == 'internal-value']
        self.assertTrue(any('compare' in message for message in reasons))

    def test_phrase_stays_text(self):
        result = self.scan_with_il('A respiratory illness', {'Mod.DiseaseDef.classification'})
        self.assertIn('Flu.classification', self.keys(result))

    def test_without_il_evidence_the_word_stays(self):
        self.assertIn('Flu.classification', self.keys(self.scan_with_il('Respiratory', set())))


class DuplicateKeyTests(ScanCase):
    """L3 and the catalog folder mismatch: one key, one entry."""

    def test_catalog_folder_named_without_namespace_matches_the_def(self):
        # The game resolves a DefInjected folder name as a type name, with or without its namespace.
        schema = def_schema()
        schema.types['Mod.DiseaseDef'] = TypeSpec('Mod.DiseaseDef', 'Verse.Def')
        self.write('Defs/a.xml', '<Defs><Mod.DiseaseDef><defName>Flu</defName><label>flu</label></Mod.DiseaseDef></Defs>')
        self.write('Languages/English/DefInjected/DiseaseDef/a.xml', '<LanguageData><Flu.label>flu</Flu.label></LanguageData>')
        result = scan_mod(self.source, schema=schema)
        self.assertEqual([e.id for e in result.entries], ['DefInjected:Mod.DiseaseDef:Flu.label'])
        self.assertIn('Existing English catalog match', result.entries[0].evidence)

    def test_identical_duplicate_def_keeps_one_usable_entry(self):
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label></ThingDef></Defs>')
        self.write('Defs/b.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label></ThingDef></Defs>')
        result = scan_mod(self.source, schema=def_schema())
        entries = [e for e in result.entries if e.key == 'Gun.label']
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].blocked)
        self.assertIn('duplicate-identical', self.codes(result))

    def test_different_duplicate_texts_stay_blocked(self):
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label></ThingDef></Defs>')
        self.write('Defs/b.xml', '<Defs><ThingDef><defName>Gun</defName><label>rifle</label></ThingDef></Defs>')
        result = scan_mod(self.source, schema=def_schema())
        self.assertTrue(self.keys(result)['Gun.label'].blocked)
        self.assertIn('duplicate', self.codes(result))

    def test_identical_duplicate_keyed_key_keeps_one_usable_entry(self):
        self.write('Languages/English/Keyed/a.xml', '<LanguageData><Hello>Hello</Hello></LanguageData>')
        self.write('Languages/English/Keyed/b.xml', '<LanguageData><Hello>Hello</Hello></LanguageData>')
        result = scan_mod(self.source, schema=def_schema())
        self.assertFalse(self.keys(result)['Hello'].blocked)


class MissingPrerequisiteReviewTests(ScanCase):
    """Item 5: a parent in a missing prerequisite does not put the Def's own name and description under review."""

    def scan_child(self):
        schema = def_schema(note=FieldSpec('System.String'))
        self.write('Defs/a.xml', '<Defs><ThingDef ParentName="FrameworkBase"><defName>Gun</defName><label>gun</label>'
                   '<description>A gun.</description><note>Some note text</note></ThingDef></Defs>')
        return self.keys(scan_mod(self.source, schema=schema))

    def test_own_must_translate_name_and_description_stay_ordinary(self):
        entries = self.scan_child()
        self.assertFalse(entries['Gun.label'].review)
        self.assertFalse(entries['Gun.description'].review)

    def test_without_field_metadata_the_name_stays_ordinary(self):
        self.write('Defs/a.xml', '<Defs><ThingDef ParentName="FrameworkBase"><defName>Gun</defName><label>gun</label>'
                   '</ThingDef></Defs>')
        self.assertFalse(self.keys(scan_mod(self.source))['Gun.label'].review)

    def test_other_fields_still_need_review(self):
        self.assertTrue(self.scan_child()['Gun.note'].review)


class LoadAliasTests(ScanCase):
    """Item 7: XML names a field by its LoadAlias (NameTriple first/nick/last); the game's DefInjected lookup does too."""

    def schema(self):
        from rimworld_translator.schema import load_alias  # noqa: F401  (decoder exists)
        schema = def_schema()
        schema.types['Mod.BioDef'] = TypeSpec('Mod.BioDef', 'Verse.Def', {'name': FieldSpec('Verse.NameTriple')})
        schema.types['Verse.NameTriple'] = TypeSpec('Verse.NameTriple', 'Verse.Name', {
            'firstInt': FieldSpec('System.String', aliases=('first',)),
            'nickInt': FieldSpec('System.String', aliases=('nick',))})
        return schema

    def test_aliased_fields_are_extracted_under_the_xml_name(self):
        self.write('Defs/a.xml', '<Defs><Mod.BioDef><defName>Bio1</defName><name><first>Chii</first><nick>Chi</nick>'
                   '</name></Mod.BioDef></Defs>')
        result = scan_mod(self.source, schema=self.schema())
        self.assertIn('Bio1.name.first', self.keys(result))
        self.assertIn('Bio1.name.nick', self.keys(result))
        self.assertNotIn('unknown-field', self.codes(result))

    def test_alias_blob_decoding(self):
        from rimworld_translator.schema import load_alias
        self.assertEqual(load_alias(b'\x01\x00\x05first\x00\x00'), 'first')
        self.assertEqual(load_alias(b'\x01\x00\xff\x00\x00'), '')
        self.assertEqual(load_alias(b'\x02\x00'), '')


class UnresolvedClassDisplayFieldTests(ScanCase):
    """Item 7: a Def whose class is unreadable still shows text in fields named and shaped like wording."""

    def scan_unknown(self, body):
        self.write('Defs/a.xml', f'<Defs><Other.CameraDef><defName>Cam</defName><label>camera</label>{body}'
                   '</Other.CameraDef></Defs>')
        return scan_mod(self.source, schema=def_schema())

    def test_help_text_and_messages_with_words_are_extracted(self):
        result = self.scan_unknown('<helpText>The map is a grid of tiles.</helpText><endMessage>The stars returned'
                                   '</endMessage><shortLabel>large box</shortLabel>')
        keys = self.keys(result)
        for key in ('Cam.helpText', 'Cam.endMessage', 'Cam.shortLabel'):
            self.assertIn(key, keys)
            self.assertEqual(keys[key].confidence, 'heuristic')

    def test_variants_of_known_text_fields_take_single_words(self):
        # L4: old HAR backstories (AlienRace.BackstoryDef) without the framework DLL: titleShort is title + Short.
        keys = self.keys(self.scan_unknown('<title>Marine</title><titleShort>Marine</titleShort>'
                                           '<titleFemale>Marine</titleFemale><titleTex>Things/Marine</titleTex>'))
        self.assertIn('Cam.titleShort', keys)
        self.assertIn('Cam.titleFemale', keys)
        self.assertNotIn('Cam.titleTex', keys)

    def test_single_tokens_and_other_names_stay_diagnostics(self):
        keys = self.keys(self.scan_unknown('<helpText>Cam_Help</helpText><workerClass>A.B</workerClass>'))
        self.assertNotIn('Cam.helpText', keys)
        self.assertNotIn('Cam.workerClass', keys)

    def test_display_named_list_items_with_words_are_extracted(self):
        keys = self.keys(self.scan_unknown('<names><li>machine gun</li><li>MG_42</li></names>'))
        self.assertIn('Cam.names.0', keys)
        self.assertNotIn('Cam.names.1', keys)


class EntryReasonTests(ScanCase):
    """Item 10: every entry says, in machine-readable codes, why it is a translation target."""

    def test_reason_codes(self):
        schema = def_schema(note=FieldSpec('System.String'), hint=FieldSpec('System.String', MAY))
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label><note>Loud</note>'
                   '<hint>Aim first</hint></ThingDef></Defs>')
        self.write('Languages/English/Keyed/k.xml', '<LanguageData><Hello>Hello</Hello></LanguageData>')
        self.write('Languages/Japanese/DefInjected/ThingDef/a.xml', '<LanguageData><Gun.label>銃</Gun.label></LanguageData>')
        keys = self.keys(scan_mod(self.source, schema=schema))
        self.assertEqual(keys['Gun.label'].reasons, ['must-translate', 'own-translation'])
        self.assertEqual(keys['Gun.note'].reasons, ['string-field', 'shape:ambiguous'])
        self.assertEqual(keys['Gun.hint'].reasons, ['may-translate'])
        self.assertEqual(keys['Hello'].reasons, ['keyed'])

    def test_heuristic_and_catalog_reasons(self):
        self.write('Defs/a.xml', '<Defs><Other.CameraDef><defName>Cam</defName><label>camera</label>'
                   '<helpText>Move the camera around.</helpText></Other.CameraDef></Defs>')
        self.write('Languages/English/DefInjected/ThingDef/a.xml',
                   '<LanguageData><Ghost.label>ghost</Ghost.label></LanguageData>')
        keys = self.keys(scan_mod(self.source, schema=def_schema()))
        self.assertEqual(keys['Cam.helpText'].reasons, ['field-name'])
        self.assertEqual(keys['Ghost.label'].reasons, ['english-catalog'])

    def test_official_patterns_add_a_reason(self):
        from rimworld_translator.extraction import mark_official
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label></ThingDef></Defs>')
        result = scan_mod(self.source, schema=def_schema())
        mark_official(result.entries, {('ThingDef', 'label', 'label')})
        self.assertEqual(self.keys(result)['Gun.label'].reasons, ['must-translate', 'official-pattern'])

    def test_reasons_survive_a_project_round_trip_and_old_projects_load(self):
        import json
        from rimworld_translator.core import Project
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label></ThingDef></Defs>')
        project = Project.create(self.source, scan_mod(self.source, schema=def_schema()))
        path = self.source.parent / 'work/project.json'
        path.parent.mkdir()
        project.save(path)
        self.assertEqual(Project.load(path).entries[0].reasons, ['must-translate'])
        data = json.loads(path.read_text(encoding='utf-8'))
        for entry in data['entries']:
            del entry['reasons']
        path.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(Project.load(path).entries[0].reasons, [])

    def test_invalid_reasons_are_rejected(self):
        import json
        from rimworld_translator.core import Project
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label></ThingDef></Defs>')
        path = self.source.parent / 'work/project.json'
        path.parent.mkdir()
        Project.create(self.source, scan_mod(self.source, schema=def_schema())).save(path)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['entries'][0]['reasons'] = [3]
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            Project.load(path)


class IncrementalRescanTests(ScanCase):
    """Backlog 9: a rescan reuses what did not change and says what it reused."""

    def setUp(self):
        super().setUp()
        self.cache = self.source.parent / 'cache/index.sqlite'
        self.write('Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label></ThingDef></Defs>')
        self.write('Defs/b.xml', '<Defs><ThingDef><defName>Axe</defName><label>axe</label></ThingDef></Defs>')

    def rescan(self, **options):
        extraction._TREE_CACHE.clear()  # a new session: only the on-disk cache remains
        extraction._TREE_CACHE_BYTES = 0
        return scan_mod(self.source, cache_path=self.cache, schema=def_schema(), **options)

    def test_unchanged_mod_reuses_the_whole_result(self):
        first = self.rescan()
        self.assertFalse(first.stats['reuse']['result_reused'])
        second = self.rescan()
        self.assertTrue(second.stats['reuse']['result_reused'])
        self.assertEqual([(e.id, e.english, e.reasons) for e in second.entries],
                         [(e.id, e.english, e.reasons) for e in first.entries])
        self.assertIn('reused', ' '.join(second.warnings))

    def test_one_changed_file_is_the_only_one_read_again(self):
        self.rescan()
        self.write('Defs/b.xml', '<Defs><ThingDef><defName>Axe</defName><label>battle axe</label></ThingDef></Defs>')
        result = self.rescan()
        self.assertFalse(result.stats['reuse']['result_reused'])
        self.assertEqual(result.stats['reuse']['files_parsed'], 1)
        self.assertEqual(result.stats['reuse']['files_reused'], 1)
        self.assertEqual(self.keys(result)['Axe.label'].english, 'battle axe')

    def test_another_context_is_not_reused(self):
        self.rescan()
        self.assertFalse(self.rescan(assumed_active=['ludeon.rimworld.royalty']).stats['reuse']['result_reused'])
        self.assertFalse(self.rescan(game_version='1.5').stats['reuse']['result_reused'])

    def test_assembly_evidence_is_reused_by_content(self):
        from unittest.mock import patch
        self.write('Assemblies/Mod.dll', 'metadata only; never executed')
        empty = {'declared': [], 'uses': {}, 'unresolved': [], 'complete': True}
        with patch('rimworld_translator.il_candidates.assembly_field_evidence', return_value=empty) as compared, \
                patch('rimworld_translator.il_candidates.inspect_translate_calls', return_value=[]) as calls:
            self.rescan()
            self.write('Defs/b.xml', '<Defs><ThingDef><defName>Axe</defName><label>hatchet</label></ThingDef></Defs>')
            result = self.rescan()
        self.assertEqual((compared.call_count, calls.call_count), (1, 1))
        self.assertEqual(result.stats['reuse']['assemblies_reused'], 1)

    def test_without_a_cache_nothing_is_claimed(self):
        result = scan_mod(self.source, schema=def_schema())
        self.assertFalse(result.stats['reuse']['result_reused'])


if __name__ == '__main__':
    unittest.main()

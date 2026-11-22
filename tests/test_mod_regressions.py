"""Regressions justified by the real MOD corpus audit."""
from pathlib import Path
from dataclasses import asdict
import hashlib
import json
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


class ModRegressionTests(unittest.TestCase):
    def test_unreadable_assembly_metadata_does_not_abort_own_xml_extraction(self):
        from rimworld_translator.schema import schema_from_assemblies
        # Exact 131-byte LFS pointer seen in the acquired MapReroll v1.3
        # source archive, plus arbitrary invalid/truncated PE input.
        pointer = (b'version https://git-lfs.github.com/spec/v1\n'
                   b'oid sha256:e89e9768476dfd0ca81a04315c3106e60c74149e5337a816fe1ed347b392a732\n'
                   b'size 122368\n')
        for data in (pointer, b'not an assembly', b'MZ' + bytes(64)):
            with self.subTest(data=data[:16]), tempfile.TemporaryDirectory() as temp:
                source = Path(temp)
                (source / 'Assemblies').mkdir()
                assembly = source / 'Assemblies/MapReroll.dll'
                assembly.write_bytes(data)
                (source / 'Defs').mkdir()
                (source / 'Defs/item.xml').write_text(
                    '<Defs><ThingDef><defName>A</defName><label>valid item</label></ThingDef></Defs>',
                    encoding='utf-8')
                keyed = source / 'Languages/English/Keyed/menu.xml'
                keyed.parent.mkdir(parents=True)
                keyed.write_text('<LanguageData><MapRerollLabel>Re-roll map</MapRerollLabel></LanguageData>',
                                 encoding='utf-8')
                schema = schema_from_assemblies([assembly], source / 'metadata-cache')
                self.assertEqual(schema.assemblies, [])
                self.assertEqual(len(schema.warnings), 1)
                self.assertIn('MapReroll.dll', schema.warnings[0])
                result = scan_mod(source, schema=schema)
                self.assertEqual({e.id: e.english for e in result.entries}, {
                    'DefInjected:ThingDef:A.label': 'valid item',
                    'Keyed:Keyed:MapRerollLabel': 'Re-roll map'})
                self.assertTrue(any(d['code'] == 'metadata' for d in result.diagnostics))
                self.assertEqual(assembly.read_bytes(), data)

    def test_translation_handle_priority_reads_ecma_named_property(self):
        from rimworld_translator.schema import translation_handle_priority
        # Actual game blob: prolog, named-count=1, PROPERTY, I4,
        # SerString("Priority"), then little-endian Int32(100).
        self.assertEqual(translation_handle_priority(
            bytes.fromhex('010001005408085072696f7269747964000000'),
            bytes.fromhex('200001')), 100)
        self.assertEqual(translation_handle_priority(
            bytes.fromhex('010001005408085072696f72697479fbffffff'),
            bytes.fromhex('200001')), -5)
        self.assertEqual(translation_handle_priority(
            bytes.fromhex('01000000'), bytes.fromhex('200001')), 0)
        self.assertEqual(translation_handle_priority(
            bytes.fromhex('0100640000000000'), bytes.fromhex('20010108')), 100)
        self.assertEqual(translation_handle_priority(
            bytes.fromhex('0100010054080850'), bytes.fromhex('200001')), 0)

    def test_vehicle_framework_metadata_ignores_unloaded_unrelated_member_signatures(self):
        # Real Vehicle Framework metadata has MemberRef rows whose Signature
        # is lazily absent in dnfile. Those rows are unrelated to translation
        # handle attributes and must not discard the rest of the assembly.
        from rimworld_translator.schema import schema_from_assemblies
        root = Path(__file__).resolve().parents[1]
        assemblies = list((root / 'artifacts/mod-100-audit/corpus').glob(
            'SmashPhil__Vehicle-Framework-*/Vehicle-Framework-*/1.6/Assemblies/Vehicles.dll'))
        if not assemblies:
            self.skipTest('Frozen Vehicle Framework metadata fixture unavailable')
        with tempfile.TemporaryDirectory() as temp:
            schema = schema_from_assemblies(assemblies, Path(temp))
        self.assertTrue(any(name.endswith('.AerialVehicleArrivalModeDef') for name in schema.types))
        self.assertFalse(any("NoneType' object has no attribute 'value" in warning
                             for warning in schema.warnings))

    def test_untranslated_handle_copies_its_sibling_field_for_any_class(self):
        schema = TranslationSchema({
            'ThingDef': TypeSpec('ThingDef', fields={'records': FieldSpec('Example.Record', is_list=True)}),
            'Example.Record': TypeSpec('Example.Record', fields={
                'name': FieldSpec('System.String', attributes=('TranslationHandleAttribute',)),
                'customLabel': FieldSpec('System.String'),
                'untranslatedCustomLabel': FieldSpec('System.String',
                    attributes=('UnsavedAttribute', 'TranslationHandleAttribute'), handle_priority=100)})})
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / 'Defs').mkdir()
            (source / 'Defs/item.xml').write_text(
                '<Defs><ThingDef><defName>A</defName><records><li>'
                '<name>stable</name><customLabel>shown label</customLabel>'
                '</li></records></ThingDef></Defs>', encoding='utf-8')
            result = scan_mod(source, schema=schema)
            self.assertEqual({e.key: e.english for e in result.entries}, {
                'A.records.shown_label.name': 'stable', 'A.records.shown_label.customLabel': 'shown label'})

    def test_body_part_duplicate_custom_labels_keep_loaded_list_handle_suffixes(self):
        schema = TranslationSchema({
            'Verse.BodyDef': TypeSpec('Verse.BodyDef', fields={'corePart': FieldSpec('Verse.BodyPartRecord')}),
            'Verse.BodyPartRecord': TypeSpec('Verse.BodyPartRecord', fields={
                'parts': FieldSpec('Verse.BodyPartRecord', is_list=True),
                'customLabel': FieldSpec('System.String'),
                'untranslatedCustomLabel': FieldSpec('System.String',
                    attributes=('UnsavedAttribute', 'TranslationHandleAttribute'), handle_priority=100)})})
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / 'Defs').mkdir()
            (source / 'Defs/body.xml').write_text(
                '<Defs><BodyDef><defName>A</defName><corePart><parts>'
                '<li MayRequire="absent.mod"><customLabel>left sensor</customLabel></li>'
                '<li><customLabel>left sensor</customLabel></li>'
                '<li><customLabel>left-sensor</customLabel></li>'
                '<li><customLabel>left sensor</customLabel></li>'
                '</parts></corePart></BodyDef></Defs>', encoding='utf-8')
            result = scan_mod(source, schema=schema, active_mods=set())
            self.assertEqual({e.key: e.english for e in result.entries}, {
                'A.corePart.parts.left_sensor-0.customLabel': 'left sensor',
                'A.corePart.parts.leftsensor.customLabel': 'left-sensor',
                'A.corePart.parts.left_sensor-1.customLabel': 'left sensor'})

    def test_legacy_metadata_cache_cannot_override_named_handle_priority(self):
        # Read-only integration against the user's installed engine; no DLL is
        # executed or copied into the repository. CI without RimWorld skips it.
        from rimworld_translator.schema import schema_from_assemblies
        from rimworld_translator.platforms import discover_installations
        assembly = next((path for game in discover_installations()
                         for path in game.root.glob('*_Data/Managed/Assembly-CSharp.dll')), None)
        if assembly is None:
            self.skipTest('Installed RimWorld metadata fixture unavailable')
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            legacy = TypeSpec('Verse.BodyPartRecord', fields={
                'untranslatedCustomLabel': FieldSpec('System.String',
                    attributes=('UnsavedAttribute', 'TranslationHandleAttribute'),
                    handle_priority=139722753)})
            digest = hashlib.sha256(assembly.read_bytes()).hexdigest()
            previous_cache = cache / (digest + '.json')
            previous_cache.write_text(json.dumps({legacy.name: asdict(legacy)}), encoding='utf-8')
            previous_bytes = previous_cache.read_bytes()
            schema = schema_from_assemblies([assembly], cache)
            self.assertEqual(schema.fields_for('Verse.BodyPartRecord')
                             ['untranslatedCustomLabel'].handle_priority, 100)
            self.assertEqual(previous_cache.read_bytes(), previous_bytes)
            # The reindexed schema contains real adjacent fields, not the
            # stale single-field payload; the new cache can be read again.
            self.assertIn('customLabel', schema.fields_for('Verse.BodyPartRecord'))
            cached = schema_from_assemblies([assembly], cache)
            self.assertEqual(cached.fields_for('Verse.BodyPartRecord')
                             ['untranslatedCustomLabel'].handle_priority, 100)

    def test_body_part_postload_label_is_the_preferred_translation_handle(self):
        # Installed Glitterworld BodyDef catalog and BodyPartRecord.PostLoad IL
        # establish this handle independently of XML's absent runtime field.
        schema = TranslationSchema({
            'Verse.BodyDef': TypeSpec('Verse.BodyDef', fields={
                'corePart': FieldSpec('Verse.BodyPartRecord')}),
            'Verse.BodyPartRecord': TypeSpec('Verse.BodyPartRecord', fields={
                'def': FieldSpec('Verse.BodyPartDef', attributes=('TranslationHandleAttribute',)),
                'parts': FieldSpec('Verse.BodyPartRecord', is_list=True),
                'customLabel': FieldSpec('System.String', attributes=('MustTranslateAttribute',)),
                'untranslatedCustomLabel': FieldSpec('System.String',
                    attributes=('UnsavedAttribute', 'TranslationHandleAttribute'), handle_priority=100)}),
            'Verse.BodyPartDef': TypeSpec('Verse.BodyPartDef', base='Verse.Def'),
            'Verse.Def': TypeSpec('Verse.Def')})
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / 'Defs').mkdir()
            (source / 'Defs/body.xml').write_text(
                '<Defs><BodyDef><defName>BlackApocriton</defName><corePart><parts>'
                '<li><def>MechanicalNeck</def><parts><li><def>MechanicalHead</def><parts>'
                '<li><def>HearingSensor</def><customLabel>left hearing sensor</customLabel></li>'
                '<li><def>HearingSensor</def><customLabel>right hearing sensor</customLabel></li>'
                '</parts></li></parts></li></parts></corePart></BodyDef></Defs>', encoding='utf-8')
            result = scan_mod(source, schema=schema)
            self.assertEqual({e.key: e.english for e in result.entries}, {
                'BlackApocriton.corePart.parts.MechanicalNeck.parts.MechanicalHead.parts.left_hearing_sensor.customLabel': 'left hearing sensor',
                'BlackApocriton.corePart.parts.MechanicalNeck.parts.MechanicalHead.parts.right_hearing_sensor.customLabel': 'right hearing sensor'})

    def test_body_part_catalog_import_matches_canonical_source_keys(self):
        from rimworld_translator.core import Project
        from rimworld_translator.workflow import preview_import
        schema = TranslationSchema({
            'Verse.BodyDef': TypeSpec('Verse.BodyDef', fields={'corePart': FieldSpec('Verse.BodyPartRecord')}),
            'Verse.BodyPartRecord': TypeSpec('Verse.BodyPartRecord', fields={
                'parts': FieldSpec('Verse.BodyPartRecord', is_list=True),
                'def': FieldSpec('Verse.BodyPartDef', attributes=('TranslationHandleAttribute',)),
                'customLabel': FieldSpec('System.String'),
                'untranslatedCustomLabel': FieldSpec('System.String',
                    attributes=('UnsavedAttribute', 'TranslationHandleAttribute'), handle_priority=100)}),
            'Verse.BodyPartDef': TypeSpec('Verse.BodyPartDef', base='Verse.Def'),
            'Verse.Def': TypeSpec('Verse.Def')})
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / 'Defs').mkdir()
            (source / 'Defs/body.xml').write_text(
                '<Defs><BodyDef><defName>A</defName><corePart><parts><li>'
                '<def>HearingSensor</def><customLabel>left hearing sensor</customLabel>'
                '</li></parts></corePart></BodyDef></Defs>', encoding='utf-8')
            catalog = source / 'Languages/ChineseSimplified/DefInjected/BodyDef/body.xml'
            catalog.parent.mkdir(parents=True)
            catalog.write_text('<LanguageData>'
                '<A.corePart.parts.left_hearing_sensor.customLabel>左听觉传感器</A.corePart.parts.left_hearing_sensor.customLabel>'
                '</LanguageData>', encoding='utf-8')
            project = Project.create(source, scan_mod(source, schema=schema), ['ChineseSimplified'])
            preview = preview_import(project, catalog, language='ChineseSimplified')
            self.assertEqual(preview.unknown, [])
            self.assertEqual([(c.id, c.after) for c in preview.changes], [
                ('DefInjected:BodyDef:A.corePart.parts.left_hearing_sensor.customLabel', '左听觉传感器')])
            self.assertTrue(all(not e.japanese for e in project.entries))

    def test_uncapped_diagnostics_retain_all_distinct_warnings_and_event_count(self):
        # Large installed MODs exceeded the UI cap; audit callers need each
        # unique location while repeated warning events remain separately counted.
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / 'Defs').mkdir()
            fields = ''.join(f'<unknown{i}>value</unknown{i}>' for i in range(1502))
            (source / 'Defs/items.xml').write_text(
                '<Defs><ThingDef><defName>A</defName><label>item</label>' + fields +
                '<unknownList><li>a</li><li>b</li><li>c</li></unknownList>' +
                '<numbers><li>1</li><li>2</li><li>3</li></numbers>' +
                '</ThingDef></Defs>', encoding='utf-8')
            schema = TranslationSchema({'ThingDef': TypeSpec('ThingDef', fields={
                'label': FieldSpec('System.String'),
                'numbers': FieldSpec('System.Int32', is_list=True)})})
            capped = scan_mod(source, schema=schema)
            self.assertEqual(len(capped.diagnostics), 1500)
            # Unknown list items now retain separate review evidence. Known
            # numeric list items still produce three events at one location.
            self.assertEqual(capped.warning_count, 1508)
            self.assertIn('6 additional distinct warnings omitted', capped.warnings[-1])
            complete = scan_mod(source, schema=schema, diagnostic_limit=None)
            self.assertEqual(len(complete.diagnostics), 1506)
            self.assertEqual(len(complete.warnings), 1506)
            self.assertEqual(complete.warning_count, 1508)
            self.assertEqual(complete.entries, capped.entries)
            self.assertTrue(any(d['message'].endswith('A.unknown1501')
                                for d in complete.diagnostics))
            list_items = [d for d in complete.diagnostics
                          if d.get('field_path', '').startswith('A.unknownList.')]
            self.assertEqual([d['field_path'] for d in list_items],
                             ['A.unknownList.0', 'A.unknownList.1', 'A.unknownList.2'])
            self.assertEqual([d['source_text'] for d in list_items], ['a', 'b', 'c'])
            for diagnostic in list_items:
                self.assertEqual(diagnostic['code'], 'unknown-field')
                self.assertEqual(diagnostic['owner_type'], 'ThingDef')
                self.assertEqual(diagnostic['source_file'], 'Defs/items.xml')
                self.assertEqual(diagnostic['safety'], 'unverified')
                self.assertEqual(diagnostic['entry_id'], '')
            skipped = [d for d in complete.diagnostics if d['code'] == 'list-skipped']
            self.assertEqual(len(skipped), 1)
            self.assertTrue(skipped[0]['message'].endswith('A.numbers'))
            self.assertFalse(any('warnings omitted' in w for w in complete.warnings))


if __name__ == '__main__':
    unittest.main()

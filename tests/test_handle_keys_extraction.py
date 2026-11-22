"""List items whose translation handle the game copies from a sibling field (HediffStage.untranslatedLabel)."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec

HANDLE = ('UnsavedAttribute', 'TranslationHandleAttribute')


def schema(builtin_version=''):
    return TranslationSchema({
        'HediffDef': TypeSpec('HediffDef', fields={'stages': FieldSpec('Verse.HediffStage', is_list=True)}),
        'Verse.HediffStage': TypeSpec('Verse.HediffStage', fields={
            'label': FieldSpec('System.String', attributes=('MustTranslateAttribute',)),
            'extraTooltip': FieldSpec('System.String', attributes=('MustTranslateAttribute',)),
            'inner': FieldSpec('Example.Inner'),
            'untranslatedLabel': FieldSpec('System.String', attributes=HANDLE, handle_priority=100)}),
        'Example.Inner': TypeSpec('Example.Inner', fields={
            'label': FieldSpec('System.String', attributes=('MustTranslateAttribute',))})},
        builtin_version=builtin_version)


class SiblingCopyHandleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'Defs').mkdir()
        (self.source / 'About/About.xml').write_text(
            '<ModMetaData><packageId>test.handle.keys</packageId><supportedVersions><li>1.4</li><li>1.6</li>'
            '</supportedVersions></ModMetaData>', encoding='utf-8')
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def scan(self, stages, version='1.6', types=None):
        (self.source / 'Defs/drug.xml').write_text(
            '<Defs><HediffDef><defName>Drug</defName><stages>' + stages + '</stages></HediffDef></Defs>',
            encoding='utf-8')
        result = scan_mod(self.source, game_version=version, schema=types or schema())
        return {entry.key: entry for entry in result.entries}

    def test_stage_label_uses_label_as_handle(self):
        entries = self.scan('<li><label>Initial</label></li><li><label>Withdrawal</label></li>')
        self.assertEqual(set(entries), {'Drug.stages.Initial.label', 'Drug.stages.Withdrawal.label'})
        self.assertEqual(entries['Drug.stages.Initial.label'].legacy_keys,
                         ['DefInjected:HediffDef:Drug.stages.0.label'])
        self.assertEqual(entries['Drug.stages.Withdrawal.label'].legacy_keys,
                         ['DefInjected:HediffDef:Drug.stages.1.label'])

    def test_duplicate_stage_labels_get_suffixes_and_distinct_legacy_keys(self):
        entries = self.scan('<li><label>Worse</label></li><li><label>Worse</label></li>')
        self.assertEqual(set(entries), {'Drug.stages.Worse-0.label', 'Drug.stages.Worse-1.label'})
        self.assertEqual(entries['Drug.stages.Worse-0.label'].legacy_keys, ['DefInjected:HediffDef:Drug.stages.0.label'])
        self.assertEqual(entries['Drug.stages.Worse-1.label'].legacy_keys, ['DefInjected:HediffDef:Drug.stages.1.label'])

    def test_missing_or_empty_label_falls_back_to_index(self):
        entries = self.scan('<li><extraTooltip>one</extraTooltip></li>'
                            '<li><label IsNull="true">ignored</label><extraTooltip>two</extraTooltip></li>'
                            '<li><label>...</label><extraTooltip>three</extraTooltip></li>')
        for index, key in enumerate(('Drug.stages.0.extraTooltip', 'Drug.stages.1.extraTooltip',
                                     'Drug.stages.2.extraTooltip')):
            with self.subTest(key=key):
                self.assertIn(key, entries)
                self.assertEqual(entries[key].legacy_keys, [])

    def test_nested_field_under_handle_item_has_legacy_path_with_index(self):
        entries = self.scan('<li><label>Initial</label><inner><label>deep</label></inner></li>')
        entry = entries['Drug.stages.Initial.inner.label']
        self.assertEqual(entry.legacy_keys, ['DefInjected:HediffDef:Drug.stages.0.inner.label'])

    def test_english_catalog_with_index_key_is_a_match_not_a_second_entry(self):
        catalog = self.source / 'Languages/English/DefInjected/HediffDef'
        catalog.mkdir(parents=True)
        (catalog / 'Drug.xml').write_text(
            '<LanguageData><Drug.stages.0.label>Initial</Drug.stages.0.label></LanguageData>', encoding='utf-8')
        entries = self.scan('<li><label>Initial</label></li>')
        self.assertEqual(set(entries), {'Drug.stages.Initial.label'})
        self.assertIn('Existing English catalog match', entries['Drug.stages.Initial.label'].evidence)

    def test_version_gate_keeps_index_keys_for_unverified_table(self):
        stages = '<li><label>Initial</label></li>'
        unverified = self.scan(stages, version='1.4', types=schema('1.6'))
        self.assertEqual(set(unverified), {'Drug.stages.0.label'})
        self.assertEqual(unverified['Drug.stages.0.label'].legacy_keys, [])
        same_version = self.scan(stages, version='1.6', types=schema('1.6'))
        self.assertEqual(set(same_version), {'Drug.stages.Initial.label'})
        installed = self.scan(stages, version='1.4', types=schema(''))
        self.assertEqual(set(installed), {'Drug.stages.Initial.label'})


def comp_schema():
    # compClass is a TranslationHandle the comp's constructor sets; XML usually leaves it out.
    return TranslationSchema({
        'ThingDef': TypeSpec('ThingDef', fields={'comps': FieldSpec('Verse.CompProperties', is_list=True)}),
        'Verse.CompProperties': TypeSpec('Verse.CompProperties', fields={
            'compClass': FieldSpec('System.Type', attributes=('TranslationHandleAttribute',), handle_priority=100)}),
        'Example.ReloadProps': TypeSpec('Example.ReloadProps', fields={
            'compClass': FieldSpec('System.Type', attributes=('TranslationHandleAttribute',), handle_priority=100),
            'chargeNoun': FieldSpec('System.String', attributes=('MustTranslateAttribute',)),
            'cooldownGerund': FieldSpec('System.String', attributes=('MustTranslateAttribute',))})})


class CatalogHandleForUnknownHandleTests(unittest.TestCase):
    """The comp's class name is the game's key segment, but only the MOD's English catalog states it."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'Defs').mkdir()
        (self.source / 'About/About.xml').write_text(
            '<ModMetaData><packageId>test.comp.handles</packageId><supportedVersions><li>1.6</li>'
            '</supportedVersions></ModMetaData>', encoding='utf-8')
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def scan(self, catalog):
        (self.source / 'Defs/pod.xml').write_text(
            '<Defs><ThingDef><defName>Pod</defName><comps><li Class="Example.ReloadProps">'
            '<chargeNoun>missile</chargeNoun><cooldownGerund>reloading</cooldownGerund>'
            '</li></comps></ThingDef></Defs>', encoding='utf-8')
        folder = self.source / 'Languages/English/DefInjected/ThingDef'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'pod.xml').write_text('<LanguageData>' + catalog + '</LanguageData>', encoding='utf-8')
        result = scan_mod(self.source, game_version='1.6', schema=comp_schema())
        return {entry.key: entry for entry in result.entries}

    def test_catalog_handle_replaces_the_index_key_of_the_same_item(self):
        entries = self.scan('<Pod.comps.CompReload.chargeNoun>missile</Pod.comps.CompReload.chargeNoun>')
        self.assertEqual(set(entries), {'Pod.comps.CompReload.chargeNoun', 'Pod.comps.CompReload.cooldownGerund'})
        self.assertEqual(entries['Pod.comps.CompReload.chargeNoun'].legacy_keys,
                         ['DefInjected:ThingDef:Pod.comps.0.chargeNoun'])
        self.assertEqual(entries['Pod.comps.CompReload.cooldownGerund'].legacy_keys,
                         ['DefInjected:ThingDef:Pod.comps.0.cooldownGerund'])
        self.assertIn('Existing English catalog match', entries['Pod.comps.CompReload.chargeNoun'].evidence)
        self.assertEqual(entries['Pod.comps.CompReload.chargeNoun'].confidence, 'schema')

    def test_catalog_key_equal_to_the_old_index_key_is_a_match(self):
        entries = self.scan('<Pod.comps.CompReload.chargeNoun>missile</Pod.comps.CompReload.chargeNoun>'
                            '<Pod.comps.0.cooldownGerund>reloading</Pod.comps.0.cooldownGerund>')
        self.assertEqual(set(entries), {'Pod.comps.CompReload.chargeNoun', 'Pod.comps.CompReload.cooldownGerund'})

    def test_a_handle_that_would_collide_renames_nothing(self):
        # An earlier catalog line already holds the target key of a sibling: keep the item whole on its index.
        entries = self.scan('<Pod.comps.CompReload.cooldownGerund>cooling</Pod.comps.CompReload.cooldownGerund>'
                            '<Pod.comps.CompReload.chargeNoun>missile</Pod.comps.CompReload.chargeNoun>')
        self.assertIn('Pod.comps.0.chargeNoun', entries)
        self.assertIn('Pod.comps.0.cooldownGerund', entries)
        self.assertEqual(entries['Pod.comps.0.chargeNoun'].legacy_keys, [])

    def test_different_text_keeps_both_entries(self):
        entries = self.scan('<Pod.comps.CompReload.chargeNoun>rocket</Pod.comps.CompReload.chargeNoun>')
        self.assertIn('Pod.comps.0.chargeNoun', entries)
        self.assertIn('Pod.comps.CompReload.chargeNoun', entries)


if __name__ == '__main__':
    unittest.main()

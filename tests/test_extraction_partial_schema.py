"""A MOD class whose game base class is unreadable keeps the inherited label/description."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


class PartialSchemaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / 'source'
        files = {
            'About/About.xml': '<ModMetaData><packageId>test.partial</packageId><supportedVersions><li>1.6</li>'
                               '</supportedVersions></ModMetaData>',
            'Defs/Custom.xml': '<Defs><My.ResearchStepDef><defName>StepOne</defName><label>first step</label>'
                               '<description>Build the first reactor part.</description>'
                               '<stepNote>Needs a workbench nearby.</stepNote><internalTag>StepOneTag</internalTag>'
                               '</My.ResearchStepDef></Defs>',
        }
        for relative, content in files.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')

    def keys(self, schema):
        return {entry.key for entry in scan_mod(self.source, schema=schema).entries}

    def test_chain_complete_distinguishes_missing_game_base(self):
        own = TypeSpec('My.ResearchStepDef', 'Verse.Def', {'stepNote': FieldSpec('System.String', ('MustTranslateAttribute',))})
        partial = TranslationSchema({'My.ResearchStepDef': own})
        self.assertFalse(partial.chain_complete('My.ResearchStepDef'))
        full = TranslationSchema({'My.ResearchStepDef': own, 'Verse.Def': TypeSpec('Verse.Def', 'System.Object', {
            'label': FieldSpec('System.String'), 'description': FieldSpec('System.String')})})
        self.assertTrue(full.chain_complete('My.ResearchStepDef'))
        self.assertFalse(partial.chain_complete('Not.Loaded'))

    def test_inherited_label_and_description_survive_a_mod_only_schema(self):
        own = TypeSpec('My.ResearchStepDef', 'Verse.Def', {
            'stepNote': FieldSpec('System.String', ('MustTranslateAttribute',)),
            'internalTag': FieldSpec('System.String', ('NoTranslateAttribute',))})
        keys = self.keys(TranslationSchema({'My.ResearchStepDef': own}))
        self.assertIn('StepOne.label', keys)
        self.assertIn('StepOne.description', keys)
        self.assertIn('StepOne.stepNote', keys)          # the MOD's own attributed field still comes from the schema
        self.assertNotIn('StepOne.internalTag', keys)    # and its NoTranslate field stays excluded

    def test_complete_schema_does_not_fall_back_to_names(self):
        # With the whole chain readable, a field the classes do not declare is not guessed from its name.
        own = TypeSpec('My.ResearchStepDef', 'Verse.Def', {'stepNote': FieldSpec('System.String')})
        base = TypeSpec('Verse.Def', 'System.Object', {'label': FieldSpec('System.String')})
        keys = self.keys(TranslationSchema({'My.ResearchStepDef': own, 'Verse.Def': base}))
        self.assertIn('StepOne.label', keys)
        self.assertNotIn('StepOne.description', keys)


if __name__ == '__main__':
    unittest.main()

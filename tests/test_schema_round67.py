"""A CLR field's declaring owner survives inheritance and simple-name XML aliases."""
import unittest

from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


class FieldOwnershipTests(unittest.TestCase):
    def test_declaring_owner_is_not_replaced_by_subclass_or_alias(self):
        schema = TranslationSchema({
            'RimWorld.StorytellerCompProperties': TypeSpec('RimWorld.StorytellerCompProperties', fields={
                'enableIfAnyModActive': FieldSpec('System.String', is_list=True)}),
            'RimWorld.StorytellerCompProperties_RandomQuest': TypeSpec(
                'RimWorld.StorytellerCompProperties_RandomQuest', 'RimWorld.StorytellerCompProperties', {
                    'description': FieldSpec('System.String')})})
        self.assertTrue(callable(getattr(schema, 'field_owner', None)), 'declaring owner lookup is missing')
        self.assertEqual(schema.field_owner('StorytellerCompProperties_RandomQuest', 'enableIfAnyModActive'),
                         'RimWorld.StorytellerCompProperties')
        self.assertEqual(schema.field_owner('StorytellerCompProperties_RandomQuest', 'description'),
                         'RimWorld.StorytellerCompProperties_RandomQuest')
        self.assertEqual(schema.field_owner('Missing', 'description'), '')
        self.assertEqual(schema.field_owner('StorytellerCompProperties_RandomQuest', 'missing'), '')

    def test_cycles_and_ambiguous_owner_aliases_are_not_guessed(self):
        schema = TranslationSchema({
            'A': TypeSpec('A', 'B'), 'B': TypeSpec('B', 'A'),
            'First.Shared': TypeSpec('First.Shared', fields={'label': FieldSpec('System.String')}),
            'Other.Shared': TypeSpec('Other.Shared', fields={'label': FieldSpec('System.String')})})
        self.assertTrue(callable(getattr(schema, 'field_owner', None)), 'declaring owner lookup is missing')
        self.assertEqual(schema.field_owner('A', 'unknown'), '')
        self.assertEqual(schema.field_owner('Shared', 'label'), '')


class EntryFieldSemanticsTests(unittest.TestCase):
    def test_saved_entry_clr_evidence_preserves_unrelated_owner_text(self):
        from rimworld_translator import field_semantics
        from rimworld_translator.core import Entry
        self.assertTrue(callable(getattr(field_semantics, 'entry_nonlocalizable_reason', None)),
                        'saved-entry semantics helper is missing')
        entry = Entry('DefInjected:ThingDef:Thing.comps.0.unlock', 'DefInjected', 'ThingDef',
                      'Thing.comps.0.unlock', 'unlock display text', 'Defs/probe.xml')
        self.assertTrue(field_semantics.entry_nonlocalizable_reason(entry))
        entry.evidence = ['CLR Example.VisibleComp.unlock: MustTranslateAttribute']
        self.assertEqual(field_semantics.entry_nonlocalizable_reason(entry), '')
        entry.evidence = ['CLR SaveOurShip2.CompProps_ResearchUnlock.unlock: string field']
        self.assertTrue(field_semantics.entry_nonlocalizable_reason(entry))
        entry.kind = 'Keyed'
        self.assertEqual(field_semantics.entry_nonlocalizable_reason(entry), '')

    def test_all_four_declaring_room_resolvers_exclude_internal_symbol(self):
        from rimworld_translator.field_semantics import nonlocalizable_reason
        for owner in ('SymbolResolver_ShipDebrisRoom', 'SymbolResolver_ShipRoom',
                      'SymbolResolver_ShipRoomTriangle1', 'SymbolResolver_ShipRoomTriangle2'):
            with self.subTest(owner=owner):
                self.assertTrue(nonlocalizable_reason('DefInjected', 'RuleDef', 'Room.resolvers.0.interior',
                                                      owner_type='SaveOurShip2.' + owner))

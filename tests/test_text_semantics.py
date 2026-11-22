import unittest

from rimworld_translator.text_semantics import INTERNAL, classify_value, field_leaf


class ClassifyValueTests(unittest.TestCase):
    def kind(self, text, field='', **names):
        return classify_value(text, field, **names).kind

    def test_sentences_and_multiword_labels_are_display(self):
        for text in ('Increases melee damage by 10%.', 'Power mode', '{0} has been wounded', 'Q: why?'):
            self.assertEqual(self.kind(text, 'description'), 'display', text)

    def test_asset_paths_are_internal(self):
        for text in ('UI/Icons/Thing', 'Things/Item/Shadow_south', 'a/b'):
            self.assertEqual(self.kind(text, 'anything'), 'path', text)

    def test_web_addresses_are_internal(self):
        for text in ('https://ludeon.com/forums/index.php?topic=37323', 'http://example.com',
                     'steam://url/CommunityFilePage/123', 'www.example.com/page'):
            self.assertIn(self.kind(text, 'linkUrl'), INTERNAL, text)
        # A sentence that mentions an address is still text to translate.
        self.assertEqual(self.kind('See https://example.com for details', 'description'), 'display')

    def test_structured_tokens_are_identifiers(self):
        for text in ('Some_Key_name', 'camelCaseValue', 'PascalTwoWords', 'ns.sub.key'):
            self.assertIn(self.kind(text, 'anything'), INTERNAL, text)

    def test_hyphenated_and_numbered_words_are_not_assumed_internal(self):
        for text in ('left-sensor', 'anti-armor', 'Mk2', 'AK47'):
            self.assertEqual(self.kind(text, 'label'), 'ambiguous', text)

    def test_plain_word_is_ambiguous_unless_field_name_says_lookup(self):
        self.assertEqual(self.kind('Hunter', 'label'), 'ambiguous')
        self.assertEqual(self.kind('Hunter', 'workTags'), 'identifier')
        self.assertEqual(self.kind('Hunter', 'iconTex'), 'identifier')

    def test_names_that_exist_in_the_scanned_content_are_references(self):
        self.assertEqual(self.kind('Foo_Bar', 'x', keyed={'Foo_Bar'}), 'reference')
        self.assertEqual(self.kind('MyThing', 'x', defs={'MyThing'}), 'reference')
        self.assertEqual(self.kind('Silver', 'allowedStuff', defs={'Silver'}), 'reference')
        # Display text is not written exactly like a Def name, so a lowercase label stays text.
        self.assertEqual(self.kind('silver', 'label', defs={'Silver'}), 'ambiguous')

    def test_def_name_equality_does_not_hide_labels_in_display_named_fields(self):
        self.assertEqual(self.kind('Easy', 'label', defs={'Easy'}), 'ambiguous')
        self.assertEqual(self.kind('Mood', 'headerTip', defs={'Mood'}), 'ambiguous')
        # A structured token is still a name even in a label field.
        self.assertEqual(self.kind('Easy_Mode', 'label', defs={'Easy_Mode'}), 'reference')
        self.assertEqual(self.kind('Cannibal', 'traits', defs={'Cannibal'}), 'reference')

    def test_debug_fields_are_never_player_text(self):
        self.assertEqual(self.kind('Wounds - pre apparel', 'debugLabel'), 'identifier')

    def test_non_ascii_and_numbers_are_display(self):
        for text in ('日本語', 'Ж', '{0}%'):
            self.assertEqual(self.kind(text, 'label'), 'display', text)

    def test_def_reference_field_names_mark_plain_words_as_references(self):
        for field in ('ResourceDefName', 'workDef', 'allowedDefs', 'thingDefNames'):
            self.assertEqual(self.kind('Jade', field), 'identifier', field)
        self.assertEqual(self.kind('Jade', 'label'), 'ambiguous')

    def test_values_without_any_letter_or_digit_are_data(self):
        for text in ('.,.,.,', '.,.\n,.,'):
            self.assertEqual(self.kind(text, 'roofGrid'), 'identifier', text)
        # Numbers can be shown to the player, so they stay candidates.
        for text in ('100%', '0.5:1'):
            self.assertEqual(self.kind(text, 'label'), 'display', text)

    def test_short_comma_lists_are_not_grids(self):
        # Roman numerals and thousands separators are wording; only real grid structure is layout data.
        for text in ('I,II,III', '1,000,000', 'Mon,Tue,Wed'):
            for field in ('label', 'description', 'note'):
                self.assertNotEqual(self.kind(text, field), 'data', (text, field))

    def test_display_named_fields_are_never_grids(self):
        text = '.,.,Roof,Roof,.,.\n.,.,.,.,.,.'
        self.assertNotEqual(self.kind(text, 'label'), 'data')
        self.assertNotEqual(self.kind(text, 'description'), 'data')

    def test_real_grids_stay_data(self):
        for text in ('.,.,Roof,Roof,.', 'A,B,C,D,E', '.,.,Roof\n.,Roof,Roof'):
            self.assertEqual(self.kind(text, 'terrainGrid'), 'data', text)

    def test_type_like_field_names_mark_plain_words_as_lookup_values(self):
        for field in ('policyClass', 'allowedPawnKinds', 'onMissingResource', 'workType', 'stuff'):
            self.assertEqual(self.kind('Support', field), 'identifier', field)
        self.assertEqual(self.kind('Support', 'label'), 'ambiguous')

    def test_field_leaf_skips_list_indexes(self):
        self.assertEqual(field_leaf('Def.comps.0.tags.3'), 'tags')
        self.assertEqual(field_leaf('Def.label'), 'label')
        self.assertEqual(field_leaf('Def'), '')


if __name__ == '__main__':
    unittest.main()

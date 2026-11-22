"""RulesStrings grammar identifiers remain source-exact while prose is translated."""
import unittest

from rimworld_translator.core import Entry
from rimworld_translator.qa import qa_entry


def rule(english='subject->starship structural engineering', **kwargs):
    values = dict(id='DefInjected:ResearchProjectDef:ShipBasics.generalRules.rulesStrings.0',
                  kind='DefInjected', group='ResearchProjectDef',
                  key='ShipBasics.generalRules.rulesStrings.0', english=english,
                  source_file='1.6/Defs/ResearchProjectDefs/ResearchProjects_Ship.xml')
    values.update(kwargs)
    return Entry(**values)


class GrammarPrefixRound67Tests(unittest.TestCase):
    def test_changed_identifier_is_blocking(self):
        issues = qa_entry(rule(), '主題->宇宙船の構造工学')
        self.assertTrue(any(i.code == 'rules_prefix' and i.severity == 'error' for i in issues))

    def test_removed_identifier_or_separator_is_blocking(self):
        for translation in ('宇宙船の構造工学', '->宇宙船の構造工学', 'subject宇宙船の構造工学'):
            with self.subTest(translation=translation):
                self.assertTrue(any(i.code == 'rules_prefix' and i.severity == 'error'
                                    for i in qa_entry(rule(), translation)))

    def test_prefix_is_exact_including_case_and_spacing(self):
        entry = rule('subject(p=0.5) ->a ship')
        for translation in ('subject(p=0.5)->船', 'Subject(p=0.5) ->船', ' subject(p=0.5) ->船'):
            with self.subTest(translation=translation):
                self.assertTrue(any(i.code == 'rules_prefix' for i in qa_entry(entry, translation)))
        self.assertEqual(qa_entry(entry, 'subject(p=0.5) ->船'), [])

    def test_valid_rhs_preserves_grammar_tokens_and_existing_placeholders(self):
        entry = rule('subject->[PAWN_nameDef] visits [Community] {0}')
        self.assertEqual(qa_entry(entry, 'subject->[PAWN_nameDef] は [Community] を訪ねる {0}'), [])
        self.assertTrue(any(i.code == 'placeholders' and i.severity == 'error'
                            for i in qa_entry(entry, 'subject->[PAWN_nameDef] は [Community] を訪ねる')))

    def test_grammar_tokens_cannot_be_removed_or_renamed(self):
        entry = rule('subject->[PAWN_nameDef] visits [Community]')
        for translation in ('subject->[PAWN_nameDef] が訪問', 'subject->[人物] は [Community] を訪問'):
            with self.subTest(translation=translation):
                self.assertTrue(any(i.code == 'grammar_tokens' and i.severity == 'error'
                                    for i in qa_entry(entry, translation)))

    def test_general_arrows_other_kinds_and_nearby_fields_are_not_grammar(self):
        for entry in (rule(kind='Keyed'), rule(kind='Strings'),
                      rule(key='ShipBasics.description'), rule(key='ShipBasics.rulesStringsExtra.0'),
                      rule(key='ShipBasics.rulesStrings'), rule(english='ordinary prose')):
            with self.subTest(kind=entry.kind, key=entry.key, english=entry.english):
                self.assertEqual(qa_entry(entry, '翻訳文'), [])
        self.assertEqual(qa_entry(rule(), 'subject->宇宙船の構造工学'), [])
        self.assertEqual(qa_entry(rule(), ''), [])

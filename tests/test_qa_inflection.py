import unittest

from rimworld_translator.core import Entry
from rimworld_translator.qa import qa_entry


def entry(english, kind='Keyed', key='K'):
    return Entry(id=f'{kind}:g:{key}', kind=kind, group='g', key=key, english=english, source_file='x.xml')


class InflectionTokenTests(unittest.TestCase):
    def issues(self, english, translation, **kw):
        return {(i.code, i.severity) for i in qa_entry(entry(english, **kw), translation)}

    def test_dropping_pronoun_and_gender_wording_is_only_a_warning(self):
        self.assertEqual(self.issues('{0} lost {0_possessive} arm.', '{0}は腕を失った。'), {('inflection_dropped', 'warning')})
        self.assertEqual(self.issues('{0} says {1_pronoun} agrees.', '{0}は同意した。'), {('inflection_dropped', 'warning')})
        self.assertEqual(self.issues('{0_gender ? he : she} agreed {1}.', '{1}に同意した。'), {('inflection_dropped', 'warning')})

    def test_dropping_a_name_or_number_is_still_an_error(self):
        self.assertIn(('placeholders', 'error'), self.issues('{0} lost {0_possessive} arm.', '腕を失った。'))
        self.assertIn(('placeholders', 'error'), self.issues('{0} met {1}.', '{0}は会った。'))

    def test_adding_a_token_the_source_lacks_is_an_error(self):
        self.assertIn(('placeholders', 'error'), self.issues('{0} agreed.', '{0}は{1_pronoun}に同意した。'))


if __name__ == '__main__':
    unittest.main()

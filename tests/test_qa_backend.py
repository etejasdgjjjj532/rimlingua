"""Chapter 3/4 checks: token helper, length hints, style and the pre-export check."""
import unittest

from rimworld_translator import qa
from rimworld_translator.core import Entry, Project


def entry(key, english, japanese='', kind='Keyed', group='Keyed'):
    return Entry(f'{kind}:{group}:{key}', kind, group, key, english, 'Main.xml', japanese)


def project(entries):
    return Project('/nonexistent/source', 'Example', 'local.translation.qa', 'author.original', ['1.6'], entries, [])


class TokenHelperTests(unittest.TestCase):
    def test_required_tokens_in_source_order(self):
        self.assertEqual(qa.required_tokens('<color=red>{0}</color> hits [PAWN_nameDef]\\n{1}'),
                         ['<color=red>', '{0}', '</color>', '[PAWN_nameDef]', '\\n', '{1}'])

    def test_missing_tokens_counts_repeats(self):
        item = entry('A', '{0} and {0} at [PAWN_nameDef]')
        self.assertEqual(qa.missing_tokens(item, '{0}と[PAWN_nameDef]'), ['{0}'])
        self.assertEqual(qa.missing_tokens(item, '{0}と{0}と[PAWN_nameDef]'), [])


class LengthHintTests(unittest.TestCase):
    def test_short_label_gets_a_width_limit(self):
        label = entry('Gun.label', 'gun', kind='DefInjected', group='ThingDef')
        hint = qa.length_hint(label, 'とても長い名前の銃です')
        self.assertTrue(hint.over)
        self.assertEqual(hint.width, 22)
        self.assertFalse(qa.length_hint(label, '銃').over)

    def test_descriptions_have_no_hint(self):
        self.assertIsNone(qa.length_hint(entry('Gun.description', 'A long description of a gun.',
                                               kind='DefInjected', group='ThingDef'), '説明'))

    def test_display_width_counts_full_width_as_two(self):
        self.assertEqual(qa.display_width('aあＡｱ'), 1 + 2 + 2 + 1)


class ExtraCheckTests(unittest.TestCase):
    def codes(self, item, text):
        return [issue.code for issue in qa.qa_extra(item, text)]

    def test_width_mixing(self):
        self.assertIn('width_mixing', self.codes(entry('A', 'Level 3'), 'レベル３と4'))
        self.assertIn('halfwidth_kana', self.codes(entry('A', 'Gun'), 'ｶﾞﾝ'))
        self.assertEqual(self.codes(entry('A', 'Level 3'), 'レベル3'), [])

    def test_same_as_source(self):
        self.assertIn('same_as_source', self.codes(entry('A', 'Fire at will'), 'Fire at will'))
        self.assertNotIn('same_as_source', self.codes(entry('A', 'OK'), 'OK'))
        self.assertNotIn('same_as_source', self.codes(entry('A', '{0}%'), '{0}%'))


class ProjectCheckTests(unittest.TestCase):
    def test_sentence_ending_minority_is_flagged(self):
        rows = [entry(f'D{n}', f'Sentence number {n}.', f'文{n}です。') for n in range(4)]
        rows.append(entry('Odd', 'Odd sentence.', '変な文'))
        issues = qa.sentence_style_issues(project(rows))
        self.assertEqual([issue.entry_id for issue in issues if issue.code == 'sentence_ending'], ['Keyed:Keyed:Odd'])

    def test_polite_and_plain_style_minority_is_flagged(self):
        rows = [entry(f'D{n}', f'It works {n}.', f'動きます{n}。') for n in range(4)]
        rows.append(entry('Plain', 'It works.', '動く。'))
        issues = qa.sentence_style_issues(project(rows))
        self.assertEqual([issue.entry_id for issue in issues if issue.code == 'style_mixing'], ['Keyed:Keyed:Plain'])

    def test_untranslated_rows_lists_empty_and_copied_english(self):
        rows = [entry('A', 'Fire at will', 'Fire at will'), entry('B', 'Hold'), entry('C', 'Go', '行け')]
        self.assertEqual([item.id for item in qa.untranslated_rows(project(rows))],
                         ['Keyed:Keyed:A', 'Keyed:Keyed:B'])

    def test_outdated_rows_are_changed_sources_with_old_text(self):
        rows = [entry('A', 'New text', '古い訳'), entry('B', 'Same', '同じ')]
        rows[0].changed, rows[0].previous_english = True, 'Old text'
        self.assertEqual([item.id for item in qa.outdated_rows(project(rows))], ['Keyed:Keyed:A'])


class ReviewRuleTests(unittest.TestCase):
    def test_a_row_with_a_qa_error_cannot_be_marked_reviewed(self):
        item = project([entry('A', 'Hit {0}', '命中')])
        with self.assertRaisesRegex(ValueError, 'プレースホルダー'):
            item.mark_reviewed('Keyed:Keyed:A')
        self.assertFalse(item.entries[0].reviewed)

    def test_reviewed_rows_that_now_have_errors_are_reported(self):
        item = project([entry('A', 'Hit {0}', '命中')])
        item.entries[0].reviewed = True
        self.assertEqual([issue.entry_id for issue in qa.reviewed_with_errors(item)], ['Keyed:Keyed:A'])


class PreflightTests(unittest.TestCase):
    def test_preflight_collects_everything_and_blocks_on_errors(self):
        rows = [entry('A', 'Hit {0}', '命中'), entry('B', 'Hold'), entry('C', 'Go', '行け')]
        report = qa.preflight(project(rows))
        self.assertFalse(report.ok)
        self.assertEqual([issue.entry_id for issue in report.errors], ['Keyed:Keyed:A'])
        self.assertEqual([item.id for item in report.untranslated], ['Keyed:Keyed:B'])
        self.assertIn('Japanese', report.languages)

    def test_preflight_passes_clean_project(self):
        report = qa.preflight(project([entry('C', 'Go', '行け')]))
        self.assertTrue(report.ok)
        self.assertEqual(report.errors, [])


if __name__ == '__main__':
    unittest.main()

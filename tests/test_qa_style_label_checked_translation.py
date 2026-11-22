"""The style-mixing message must describe the translation that was checked, not entry.japanese."""
import unittest

from rimworld_translator import qa
from rimworld_translator.core import Entry, Project


def entry(key, english, japanese=''):
    return Entry(f'Keyed:Keyed:{key}', 'Keyed', 'Keyed', key, english, 'Main.xml', japanese)


class StyleLabelTests(unittest.TestCase):
    def test_label_uses_the_checked_non_current_language(self):
        rows = [entry(f'D{n}', f'It works {n}.') for n in range(4)]
        rows.append(entry('Odd', 'It works.', japanese='です。'))  # the current language says polite
        project = Project('/nonexistent/source', 'Example', 'local.translation.qa', 'author.original', ['1.6'], rows, [],
                          language='Japanese', languages=['Japanese', 'German'])
        project.translations['German'] = {f'Keyed:Keyed:D{n}': f'Es geht {n}です。' for n in range(4)}
        project.translations['German']['Keyed:Keyed:Odd'] = 'Es geht。'  # plain in the checked language
        issues = [i for i in qa.sentence_style_issues(project, 'German') if i.code == 'style_mixing']
        self.assertEqual([i.entry_id for i in issues], ['Keyed:Keyed:Odd'])
        self.assertIn('この訳はだ・である調', issues[0].message)


if __name__ == '__main__':
    unittest.main()

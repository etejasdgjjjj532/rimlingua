import unittest
from pathlib import Path

from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator import qa


def entry(english, translation=""):
    return Entry("Keyed:Keyed:Hello", "Keyed", "Keyed", "Hello", english, "Main.xml", translation)


class QaTests(unittest.TestCase):
    def test_placeholder_counts_are_checked_including_repeated_tokens(self):
        issues = qa.qa_entry(entry("{name} sees {name}: {0:N2}", "{name} が見る: {0:N2}"))
        self.assertTrue(any(issue.code == "placeholders" and issue.severity == "error" for issue in issues))
        self.assertEqual(qa.qa_entry(entry("{name} sees {name}: {0:N2}", "{0:N2}: {name} と {name}")), [])

    def test_markup_balance_nested_order_and_source_attributes_are_checked(self):
        source = "<color=#ff0000><b>Danger</b></color>"
        for translated in ["<color=#ff0000><b>危険</color></b>", "<color=#ff0000>危険", "<color=#00ff00><b>危険</b></color>"]:
            with self.subTest(translated=translated):
                issues = qa.qa_entry(entry(source, translated))
                self.assertTrue(any(issue.code == "markup" and issue.severity == "error" for issue in issues))
        self.assertEqual(qa.qa_entry(entry(source, '<color="#ff0000"><b>危険</b></color>')), [])

    def test_paired_rich_text_tag_cannot_be_replaced_by_a_self_closing_tag(self):
        issues = qa.qa_entry(entry("<b>Danger</b>", "<b/>危険"))
        self.assertTrue(any(issue.code == "markup" and issue.severity == "error" for issue in issues))

    def test_plain_angle_text_is_not_mistaken_for_rich_text(self):
        self.assertEqual(qa.qa_entry(entry("gun", "銃 <試験> & 弾")), [])

    def test_untranslated_entries_are_not_blocked(self):
        self.assertEqual(qa.qa_entry(entry("<color=red>{0}</color>", "")), [])

    def test_escape_and_actual_newline_changes_are_warnings(self):
        issues = qa.qa_entry(entry("First\\nSecond\nThird", "一番目 二番目 三番目"))
        self.assertEqual({issue.code for issue in issues}, {"escapes", "newlines"})
        self.assertTrue(all(issue.severity == "warning" for issue in issues))

    def test_whitespace_and_obvious_truncation_warn_without_blocking(self):
        issues = qa.qa_entry(entry("This description explains several different details and requires the player to read an entire paragraph.", " x "))
        self.assertEqual({issue.code for issue in issues}, {"whitespace", "truncation"})
        self.assertTrue(all(issue.severity == "warning" for issue in issues))

    def test_glossary_source_matches_case_insensitively_at_word_boundaries(self):
        glossary = {"gun": "銃"}
        issues = qa.qa_entry(entry("A GUN is here", "鉄砲がここにある"), glossary=glossary)
        self.assertTrue(any(issue.code == "glossary" and issue.suggestion == "銃" for issue in issues))
        self.assertEqual(qa.qa_entry(entry("gunpowder and gunner", "火薬と射手"), glossary=glossary), [])
        self.assertEqual(qa.qa_entry(entry("A gun is here", "この銃はここにある"), glossary=glossary), [])

    def test_korean_glossary_terms_can_occur_without_separating_spaces(self):
        self.assertEqual(qa.qa_entry(entry("A gun is here", "이총은여기에있습니다"), glossary={"gun": "총"}), [])

    def test_same_source_with_different_translations_surfaces_all_entries(self):
        first = entry("gun", "銃")
        second = Entry("Keyed:Keyed:Other", "Keyed", "Keyed", "Other", "gun", "Main.xml", "鉄砲")
        project = Project.create(Path("/tmp"), Scan(entries=[first, second]))
        issues = qa.qa_project(project)
        inconsistent = [issue for issue in issues if issue.code == "inconsistent_translation"]
        self.assertEqual({issue.entry_id for issue in inconsistent}, {first.id, second.id})
        self.assertTrue(all(issue.severity == "warning" for issue in inconsistent))

    def test_duplicate_long_translations_warn_but_different_short_labels_do_not(self):
        first = entry("This is the description of the first building and its abilities.", "最初の建物の説明です。")
        second = Entry("Keyed:Keyed:Other", "Keyed", "Keyed", "Other", "This explains a different building with a different function.", "Main.xml", "最初の建物の説明です。")
        project = Project.create(Path("/tmp"), Scan(entries=[first, second]))
        issues = qa.qa_project(project)
        self.assertEqual({issue.entry_id for issue in issues if issue.code == "duplicate_translation"}, {first.id, second.id})
        first, second = project.entries
        first.english, second.english = "cargo", "goods"
        first.japanese = second.japanese = "物資"
        self.assertEqual(qa.qa_project(project), [])


if __name__ == "__main__":
    unittest.main()

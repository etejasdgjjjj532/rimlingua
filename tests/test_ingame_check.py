"""Numbered test translations and the game's translation report parser for the in-game check tool."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry
from rimworld_translator.qa import qa_entry
from tools import ingame_check as check


def entry(key, english, kind='DefInjected', **flags):
    return Entry(f'{kind}:ThingDef:{key}', kind, 'ThingDef', key, english, 'Defs/a.xml', **flags)


class NumberedTranslationTests(unittest.TestCase):
    def assert_qa_clean(self, item, text):
        errors = [i for i in qa_entry(item, text) if i.severity == 'error']
        self.assertEqual(errors, [], text)

    def test_plain_text_becomes_the_marker(self):
        self.assertEqual(check.numbered_translation(entry('Gun.label', 'laser gun'), 1), '訳00001')

    def test_placeholders_follow_the_marker(self):
        item = entry('Gun.ingestCommandString', 'Apply {0} to {PAWN_nameDef}')
        text = check.numbered_translation(item, 2)
        self.assertEqual(text, '訳00002 {0} {PAWN_nameDef}')
        self.assert_qa_clean(item, text)

    def test_grammar_rule_keeps_its_left_side_and_tokens(self):
        item = Entry('DefInjected:RulePackDef:N.rulePack.rulesStrings.0', 'DefInjected', 'RulePackDef',
                     'N.rulePack.rulesStrings.0', 'name->[adj] [noun] of doom', 'Defs/r.xml')
        text = check.numbered_translation(item, 3)
        self.assertEqual(text, 'name->訳00003 [adj] [noun]')
        self.assert_qa_clean(item, text)

    def test_rich_text_tags_stay_balanced(self):
        item = entry('Gun.description', '<color=#ff0000>Hot</color> food')
        text = check.numbered_translation(item, 4)
        self.assertEqual(text, '訳00004 <color=#ff0000> </color>')
        self.assert_qa_clean(item, text)

    def test_edge_whitespace_and_line_breaks_are_kept(self):
        item = entry('Gun.description', ' first\nsecond ')
        self.assertEqual(check.numbered_translation(item, 5), ' 訳00005\n ')

    def test_fill_skips_rows_that_cannot_be_exported(self):
        rows = [entry('A.label', 'a'), entry('B.label', 'b', blocked=True),
                entry('C.label', 'c', excluded=True), entry('D.label', 'd')]
        markers = check.fill_numbered(rows, start=10)
        self.assertEqual([r.japanese for r in rows], ['訳00010', '', '', '訳00011'])
        self.assertEqual(markers, {'訳00010': rows[0].id, '訳00011': rows[3].id})


REPORT = """Translation report for Japanese

========== General load errors (0) ==========

========== Def-injected translations load errors (2) ==========
Couldn't inject Gun.tools.0.label into Verse.ThingDef (Weapons.xml): Field tools does not exist.
Found no Verse.ThingDef named Old to match Old.label (Weapons.xml)

========== Def-injected translations missing (1) ==========
ThingDef: Gun.verbs.0.label 'shoot'

========== Argument count mismatches (may or may not be incorrect) (1) ==========
GunKey (Keys.xml:3)
  - 'Fire {0}'
  - '撃つ'

========== Keyed translations matching English (maybe ok) (0) ==========
"""


class TranslationReportTests(unittest.TestCase):
    def test_sections_are_split_by_title_with_counts(self):
        sections = check.parse_translation_report(REPORT)
        self.assertEqual(sections['Def-injected translations load errors'],
                         ["Couldn't inject Gun.tools.0.label into Verse.ThingDef (Weapons.xml): Field tools does not exist.",
                          'Found no Verse.ThingDef named Old to match Old.label (Weapons.xml)'])
        self.assertEqual(sections['Def-injected translations missing'], ["ThingDef: Gun.verbs.0.label 'shoot'"])
        self.assertEqual(sections['General load errors'], [])

    def test_multi_line_items_stay_together(self):
        sections = check.parse_translation_report(REPORT)
        self.assertEqual(sections['Argument count mismatches (may or may not be incorrect)'],
                         ["GunKey (Keys.xml:3)\n  - 'Fire {0}'\n  - '撃つ'"])

    def test_new_items_exclude_the_vanilla_baseline(self):
        baseline = {'Def-injected translations missing': ["ThingDef: Gun.verbs.0.label 'shoot'"]}
        new = check.new_report_items(check.parse_translation_report(REPORT), baseline)
        self.assertNotIn('Def-injected translations missing', new)
        self.assertEqual(len(new['Def-injected translations load errors']), 2)


class DllOptInTests(unittest.TestCase):
    def mod(self, root, package, dll=True):
        (root / 'About').mkdir(parents=True)
        (root / 'About/About.xml').write_text(f'<ModMetaData><packageId>{package}</packageId></ModMetaData>')
        if dll:
            (root / 'Assemblies').mkdir()
            (root / 'Assemblies/x.dll').write_bytes(b'never executed')
        return root

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_folder_named_like_harmony_still_needs_opt_in(self):
        source = self.mod(self.root / 'MyHarmonyPatches', 'someone.patches')
        dep = self.mod(self.root / '2009463077-lookalike', 'someone.framework')
        found = check.unapproved_dlls(source, [dep])
        self.assertEqual(sorted(found), [str(dep), str(source)])

    def test_harmony_prerequisite_is_approved_by_package_id(self):
        source = self.mod(self.root / 'source', 'someone.mod', dll=False)
        harmony = self.mod(self.root / 'whatever', 'brrainz.harmony')
        self.assertEqual(check.unapproved_dlls(source, [harmony]), {})

    def test_source_claiming_harmony_is_not_approved(self):
        source = self.mod(self.root / 'source', 'brrainz.harmony')
        self.assertEqual(list(check.unapproved_dlls(source, [])), [str(source)])


if __name__ == '__main__':
    unittest.main()

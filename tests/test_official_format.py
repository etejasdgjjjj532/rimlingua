"""Interop with RimWorld's own translation file format: EN comments, whole-list translations, official packs."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Entry, Project, english_comment, export_mod, scan_mod
from rimworld_translator.official_translations import official_index
from rimworld_translator.workflow import preview_import


def parse_with_comments(path: Path) -> ET.Element:
    return ET.parse(path, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))).getroot()


class EnglishCommentTests(unittest.TestCase):
    def test_matches_the_game_cleaner_format(self):
        self.assertEqual(english_comment('a\nb'), ' EN: a\\nb ')
        self.assertEqual(english_comment('x -- y---z'), ' EN: x - - y- - -z ')
        self.assertNotIn('--', english_comment('----'))


class ProjectTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Example</name><packageId>author.example</packageId>'
                   '<supportedVersions><li>1.6</li></supportedVersions></ModMetaData>')
        self.write('Defs/Defs.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label>'
                   '<description>Fires -- loudly.\nTwice.</description></ThingDef>'
                   '<RulePackDef><defName>Talk</defName><rulePack><rulesStrings>'
                   '<li>r->hello</li><li>r->bye</li></rulesStrings></rulePack></RulePackDef></Defs>')
        self.project = Project.create(self.source, scan_mod(self.source))

    def write(self, relative, text, base=None):
        path = (base or self.source) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def entry(self, key):
        return next(entry for entry in self.project.entries if entry.key == key)

    def test_export_writes_en_comment_before_each_entry(self):
        self.entry('Gun.label').japanese = '銃'
        self.entry('Gun.description').japanese = '大きな音で撃つ。'
        export_mod(self.project, self.root / 'mod')
        root = parse_with_comments(self.root / 'mod/Languages/Japanese/DefInjected/ThingDef/Translations.xml')
        nodes = list(root)
        self.assertEqual([node.tag for node in nodes[1::2]], ['Gun.label', 'Gun.description'])
        self.assertTrue(all(node.tag is ET.Comment for node in nodes[0::2]))
        self.assertEqual(nodes[0].text, ' EN: gun ')
        self.assertEqual(nodes[2].text, english_comment(self.entry('Gun.description').english))

    def test_whole_list_translation_is_imported_by_position(self):
        self.assertIn('Talk.rulePack.rulesStrings.1', {entry.key for entry in self.project.entries})
        incoming = self.write('Languages/Japanese/DefInjected/RulePackDef/Talk.xml',
                              '<LanguageData><!-- EN: x --><Talk.rulePack.rulesStrings>'
                              '<li>r->こんにちは</li><li>r->さよなら</li></Talk.rulePack.rulesStrings></LanguageData>',
                              base=self.root / 'incoming')
        preview = preview_import(self.project, incoming.parent.parent.parent.parent.parent)
        changed = {change.id.rsplit(':', 1)[1]: change.after for change in preview.changes}
        self.assertEqual(changed, {'Talk.rulePack.rulesStrings.0': 'r->こんにちは', 'Talk.rulePack.rulesStrings.1': 'r->さよなら'})
        self.assertEqual(preview.warnings, [])

    def test_grammar_rules_are_matched_by_rule_name_not_position(self):
        self.write('Defs/Defs.xml', '<Defs><RulePackDef><defName>Talk</defName><rulePack><rulesStrings>'
                   '<li>greet->hello</li><li>leave->bye</li><li>greet->hi</li></rulesStrings></rulePack></RulePackDef></Defs>')
        self.project = Project.create(self.source, scan_mod(self.source))
        incoming = self.write('Japanese/DefInjected/RulePackDef/Talk.xml',
                              '<LanguageData><Talk.rulePack.rulesStrings><li>leave->さよなら</li><li>greet->こんにちは</li>'
                              '<li>greet->やあ</li><li>extra->追加</li></Talk.rulePack.rulesStrings></LanguageData>',
                              base=self.root / 'incoming')
        preview = preview_import(self.project, incoming)
        changed = {change.id.rsplit('.', 1)[1]: change.after for change in preview.changes}
        self.assertEqual(changed, {'0': 'greet->こんにちは', '1': 'leave->さよなら', '2': 'greet->やあ'})
        self.assertTrue(any('対応のない訳 1 項目' in warning for warning in preview.warnings))

    def test_old_rep_syntax_is_imported(self):
        incoming = self.write('Japanese/DefInjected/ThingDef/Gun.xml',
                              '<LanguageData><rep><path>Gun.label</path><trans>銃</trans></rep></LanguageData>',
                              base=self.root / 'incoming')
        preview = preview_import(self.project, incoming)
        self.assertEqual([(change.id, change.after) for change in preview.changes], [(self.entry('Gun.label').id, '銃')])

    def test_non_li_children_and_todo_are_not_imported(self):
        incoming = self.write('Japanese/DefInjected/ThingDef/Gun.xml',
                              '<LanguageData><Gun.label>TODO</Gun.label>'
                              '<Gun.description><b>x</b></Gun.description></LanguageData>', base=self.root / 'incoming')
        preview = preview_import(self.project, incoming)
        self.assertEqual(preview.changes, [])
        self.assertTrue(any('li 以外' in warning for warning in preview.warnings))


class OfficialIndexTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.game = Path(temp.name)
        files = {
            'DefInjected/ThingDef/Items.xml':
                '<LanguageData><!-- EN: steel --><Steel.label>鋼鉄</Steel.label>'
                '<!-- EN: wood --><WoodLog.label>TODO</WoodLog.label>'
                '<!-- EN:\n    <li>r->hi</li>\n    <li>r->yo</li>\n  --><Talk.rulePack.rulesStrings>'
                '<li>r->やあ</li><li>r->よう</li></Talk.rulePack.rulesStrings></LanguageData>',
            'Keyed/Misc.xml': '<LanguageData><!-- EN: Cancel --><Cancel>キャンセル</Cancel>'
                              '<!-- EN: Line\\nTwo --><Two>二\\n行</Two></LanguageData>',
        }
        languages = self.game / 'Data/Core/Languages'
        languages.mkdir(parents=True)
        with tarfile.open(languages / 'Japanese (日本語).tar', 'w') as archive:
            for name, text in files.items():
                data = text.encode('utf-8')
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def test_suggests_by_key_then_by_english(self):
        index = official_index(self.game, 'Japanese')
        same_key = Entry('a', 'DefInjected', 'ThingDef', 'Steel.label', 'steel', 'f')
        same_english = Entry('b', 'DefInjected', 'ThingDef', 'MySteel.label', 'steel', 'f')
        updated_source = Entry('c', 'DefInjected', 'ThingDef', 'Steel.label', 'hardened steel', 'f')
        self.assertEqual(index.suggest(same_key), ['鋼鉄'])
        self.assertEqual(index.suggest(same_english), ['鋼鉄'])
        self.assertEqual(index.suggest(updated_source), [])

    def test_lists_placeholders_and_newlines(self):
        index = official_index(self.game, 'Japanese')
        rule = Entry('d', 'DefInjected', 'RulePackDef', 'Talk.rulePack.rulesStrings.1', 'r->yo', 'f')
        self.assertEqual(index.suggest(rule), ['r->よう'])
        self.assertEqual(index.suggest(Entry('e', 'DefInjected', 'ThingDef', 'WoodLog.label', 'wood', 'f')), [])
        self.assertEqual(index.suggest(Entry('f', 'Keyed', 'Keyed', 'Two', 'Line\nTwo', 'f')), ['二\\n行'])

    def test_field_patterns_of_translated_def_fields(self):
        from rimworld_translator.official_translations import official_field_patterns
        self.assertEqual(official_field_patterns(self.game, 'Japanese'),
                         {('ThingDef', 'label', 'label'), ('ThingDef', 'rulePack', 'rulesStrings')})
        self.assertEqual(official_field_patterns(None, 'Japanese'), frozenset())

    def test_missing_game_gives_empty_index(self):
        self.assertEqual(official_index(None, 'Japanese').entries, 0)
        self.assertEqual(official_index(self.game, 'French').entries, 0)


if __name__ == '__main__':
    unittest.main()

"""Translations a found prerequisite MOD already ships, offered read-only for rows that refer to the same keys."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry
from rimworld_translator.prerequisite_translations import read_prerequisite_translations
from rimworld_translator.scan_context import Prerequisite


def entry(kind, group, key):
    return Entry(f'{kind}:{group}:{key}', kind, group, key, 'English', 'x.xml')


class PrerequisiteTranslationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.lib = Path(temporary.name) / 'lib'
        base = self.lib / 'Languages/Japanese (日本語)'
        (base / 'DefInjected/ThingDef').mkdir(parents=True)
        (base / 'Keyed').mkdir()
        (base / 'DefInjected/ThingDef/a.xml').write_text(
            '<LanguageData><Gun.label>銃</Gun.label><Gun.description>強い銃</Gun.description>'
            '<Gun.tools><li>柄</li><li>銃身</li></Gun.tools><Empty.label></Empty.label><Todo.label>TODO</Todo.label></LanguageData>', encoding='utf-8')
        (base / 'Keyed/k.xml').write_text('<LanguageData><Lib_Open>開く</Lib_Open></LanguageData>', encoding='utf-8')
        other = self.lib / 'Languages/English/Keyed'
        other.mkdir(parents=True)
        (other / 'k.xml').write_text('<LanguageData><Lib_Open>Open</Lib_Open></LanguageData>')
        self.found = [Prerequisite('sample.lib', 'Sample Lib', folder=self.lib)]

    def read(self, language='Japanese'):
        return read_prerequisite_translations(self.found, language, '1.6')

    def test_same_key_is_offered_with_the_mod_name(self):
        hits = self.read().lookup(entry('DefInjected', 'ThingDef', 'Gun.label'))
        self.assertEqual((hits[0].mod, hits[0].text, hits[0].same_def), ('Sample Lib', '銃', False))
        self.assertTrue(all(h.same_def for h in hits[1:]))

    def test_list_items_use_their_index_keys(self):
        hits = self.read().lookup(entry('DefInjected', 'ThingDef', 'Gun.tools.1'))
        self.assertEqual(hits[0].text, '銃身')
        self.assertFalse(hits[0].same_def)

    def test_keyed_matches_on_the_key_alone(self):
        hits = self.read().lookup(entry('Keyed', 'Keyed', 'Lib_Open'))
        self.assertEqual([h.text for h in hits], ['開く'])

    def test_other_fields_of_the_same_def_are_offered_second(self):
        hits = self.read().lookup(entry('DefInjected', 'ThingDef', 'Gun.verbs'))
        self.assertTrue(hits)
        self.assertTrue(all(h.same_def for h in hits))
        self.assertIn('Gun.label', [h.key for h in hits])

    def test_a_different_def_type_with_the_same_name_does_not_match(self):
        self.assertEqual(self.read().lookup(entry('DefInjected', 'RecipeDef', 'Gun.label')), [])

    def test_empty_and_todo_values_are_skipped(self):
        index = self.read()
        self.assertEqual(index.lookup(entry('DefInjected', 'ThingDef', 'Empty.label')), [])
        self.assertEqual(index.lookup(entry('DefInjected', 'ThingDef', 'Todo.label')), [])

    def test_only_the_project_language_is_read(self):
        self.assertEqual(self.read('French').lookup(entry('Keyed', 'Keyed', 'Lib_Open')), [])
        self.assertEqual(self.read('Japanese').count, 5)

    def test_found_prerequisites_without_language_folders_give_an_empty_index(self):
        empty = Path(self.lib.parent / 'empty')
        empty.mkdir()
        index = read_prerequisite_translations([Prerequisite('x.y', 'Y', folder=empty)], 'Japanese', '1.6')
        self.assertEqual(index.count, 0)
        self.assertEqual(index.lookup(entry('Keyed', 'Keyed', 'Lib_Open')), [])


if __name__ == '__main__':
    unittest.main()

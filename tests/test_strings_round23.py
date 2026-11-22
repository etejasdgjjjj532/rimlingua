"""Game Strings resources retain file identity, logical order, and source ownership."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, scan_mod


class StringsRound23Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()

    def write(self, relative, text, base=None):
        path = (base or self.source) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_standard_strings_use_logical_indexes_and_exact_engine_comment_rules(self):
        path = self.write('Languages/English/Strings/WordLists/Names.txt',
                          '\ufeff// header\r\n  Alpha  // note\r\n\r\n  Beta  \n // ignored\nGamma\n')
        before = path.read_bytes()
        result = scan_mod(self.source)
        self.assertEqual([(e.kind, e.group, e.key, e.english) for e in result.entries], [
            ('Strings', 'WordLists/Names.txt', 'line_0', 'Alpha  '),
            ('Strings', 'WordLists/Names.txt', 'line_1', 'Beta'),
            ('Strings', 'WordLists/Names.txt', 'line_2', 'Gamma')])
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(all(e.source_file == 'Languages/English/Strings/WordLists/Names.txt' for e in result.entries))

    def test_only_standard_nested_strings_are_extracted(self):
        self.write('Languages/English/Strings/Names/Animal.txt', 'Animal')
        for path in ('Names.txt', 'Strings/WordLists/Names.txt', 'WordLists/Names.txt',
                     'Languages/English/Strings/Root.txt', 'Languages/English/WordInfo/Gender/Male.txt',
                     'Languages/Japanese/Strings/Names/Animal.txt'):
            self.write(path, 'Never import')
        result = scan_mod(self.source)
        self.assertEqual([e.english for e in result.entries], ['Animal'])
        self.assertTrue(any(d['code'] == 'strings-unsupported' for d in result.diagnostics))

    def test_version_precedence_and_context_ownership_are_independent(self):
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li>Common</li><li>1.6</li></v1.6>'
                   '<v1.10><li>Common</li><li>1.10</li></v1.10></loadFolders>')
        for folder, text in (('Common', 'overridden'), ('1.6', 'Old\nOnly old'), ('1.10', 'New')):
            self.write(f'{folder}/Languages/English/Strings/WordLists/Names.txt', text)
        context = self.root / 'context'
        self.write('Languages/English/Strings/Names/Foreign.txt', 'Foreign', base=context)
        before = {p: p.read_bytes() for p in self.root.rglob('*.txt')}
        for version, expected in (('1.6', ['Old', 'Only old']), ('1.10', ['New'])):
            for cache in (None, self.root / 'index.sqlite'):
                result = scan_mod(self.source, game_version=version, context_sources=[context], cache_path=cache)
                self.assertEqual([e.english for e in result.entries], expected)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.txt')})

    def test_symlink_and_invalid_utf8_never_become_confirmed_entries(self):
        external = self.write('outside.txt', 'outside')
        link = self.source / 'Languages/English/Strings/WordLists/Linked.txt'
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(external)
        (link.parent / 'Broken.txt').write_bytes(b'bad\xff')
        result = scan_mod(self.source)
        self.assertEqual(result.entries, [])
        self.assertTrue(any(d['code'] == 'strings-read' for d in result.diagnostics))

    def test_resource_path_validator_rejects_traversal_and_unportable_paths(self):
        from rimworld_translator.string_resources import validate_string_entry
        self.assertTrue(validate_string_entry('Names/Animal.txt', 'line_0'))
        for group in ('Names.txt', '../Names.txt', '/Names/Animal.txt', 'Names//Animal.txt',
                      'Names/../Animal.txt', 'Names\\Animal.txt', 'Names/Animal:bad.txt',
                      'Names/.Animal.txt', 'Names/Animal.txt\x00'):
            self.assertFalse(validate_string_entry(group, 'line_0'), group)
        for key in ('line_-1', 'line_01', 'line_1\n', 'line_1/../../evil'):
            self.assertFalse(validate_string_entry('Names/Animal.txt', key), key)

    def test_serializer_preserves_logical_order_and_full_translated_resource(self):
        from rimworld_translator import string_resources
        self.assertTrue(hasattr(string_resources, 'serialize_string_entries'), 'Strings serializer is missing')
        entries = [Entry('Strings:Names/Animal.txt:line_' + str(i), 'Strings', 'Names/Animal.txt',
                         'line_' + str(i), value, 'source') for i, value in enumerate(('First', 'Second'))]
        translated = {entries[0].id: '最初  ', entries[1].id: '次'}
        raw = string_resources.serialize_string_entries(list(reversed(entries)), translated)
        self.assertEqual(string_resources.parse_strings(raw.decode('utf-8')), ['最初  ', '次'])
        self.assertNotIn(b'First', raw)

    def test_serializer_refuses_missing_or_lossy_translations_and_index_gaps(self):
        from rimworld_translator import string_resources
        self.assertTrue(hasattr(string_resources, 'serialize_string_entries'), 'Strings serializer is missing')
        entry = Entry('Strings:Names/Animal.txt:line_0', 'Strings', 'Names/Animal.txt', 'line_0', 'First', 'source')
        for value in ('', '  leading', 'a//b', 'a\nb', 'a\rb', 'bad\x00', 'bad\ud800'):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                string_resources.serialize_string_entries([entry], {entry.id: value})
        with self.assertRaises(ValueError):
            string_resources.serialize_string_entries([entry], {})
        entry.key = 'line_1'
        with self.assertRaises(ValueError):
            string_resources.serialize_string_entries([entry], {entry.id: '訳'})


if __name__ == '__main__':
    unittest.main()

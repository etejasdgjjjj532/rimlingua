"""Standard Strings decoding and trimming follow the game text reader."""
import codecs
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, scan_mod
from rimworld_translator.string_resources import decode_strings, parse_strings, serialize_string_entries


class StringsRound24Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()

    def write(self, relative, content, base=None):
        path = (base or self.source) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_standard_reader_detects_utf_boms_before_parsing_logical_lines(self):
        # UTF-32 LE shares UTF-16 LE's prefix; matching the short BOM first loses lines.
        formats = [('utf-8', codecs.BOM_UTF8), ('utf-16-le', codecs.BOM_UTF16_LE),
                   ('utf-16-be', codecs.BOM_UTF16_BE), ('utf-32-le', codecs.BOM_UTF32_LE),
                   ('utf-32-be', codecs.BOM_UTF32_BE)]
        text = '// heading\r\n  Alpha  // note\r\n\r\n  Ωmega\n'
        for encoding, bom in formats:
            with self.subTest(encoding=encoding):
                path = self.write('Languages/English/Strings/WordLists/Names.txt', bom + text.encode(encoding))
                original = path.read_bytes()
                result = scan_mod(self.source)
                self.assertEqual([(e.group, e.key, e.english, e.source_file) for e in result.entries], [
                    ('WordLists/Names.txt', 'line_0', 'Alpha  ', 'Languages/English/Strings/WordLists/Names.txt'),
                    ('WordLists/Names.txt', 'line_1', 'Ωmega', 'Languages/English/Strings/WordLists/Names.txt')])
                self.assertFalse(any(d['code'] == 'strings-read' for d in result.diagnostics))
                self.assertEqual(path.read_bytes(), original)

    def test_bom_resources_preserve_version_precedence_and_target_ownership(self):
        self.write('LoadFolders.xml', b'<loadFolders><v1.6><li>Common</li><li>1.6</li></v1.6>'
                   b'<v1.10><li>Common</li><li>1.10</li></v1.10></loadFolders>')
        self.write('Common/Languages/English/Strings/WordLists/Names.txt', b'overridden')
        self.write('1.6/Languages/English/Strings/WordLists/Names.txt',
                   codecs.BOM_UTF16_LE + 'Old\nOnly old'.encode('utf-16-le'))
        self.write('1.10/Languages/English/Strings/WordLists/Names.txt',
                   codecs.BOM_UTF32_BE + 'New'.encode('utf-32-be'))
        context = self.root / 'context'
        self.write('Languages/English/Strings/Names/Foreign.txt', codecs.BOM_UTF16_BE + 'Foreign'.encode('utf-16-be'), base=context)
        original = {p: p.read_bytes() for p in self.root.rglob('*.txt')}
        for version, expected in [('1.6', ['Old', 'Only old']), ('1.10', ['New'])]:
            for cache in [None, self.root / 'index.sqlite']:
                with self.subTest(version=version, cache=cache):
                    result = scan_mod(self.source, game_version=version, context_sources=[context], cache_path=cache)
                    self.assertEqual([e.english for e in result.entries], expected)
                    self.assertTrue(all(e.source_file.startswith(version + '/') for e in result.entries))
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*.txt')}, original)

    def test_engine_trim_does_not_silently_remove_python_only_control_whitespace(self):
        for control in ['\x1c', '\x1d', '\x1e', '\x1f']:
            with self.subTest(control=repr(control)):
                self.assertEqual(parse_strings(control + 'Alpha' + control + '\n' + control + '\n'),
                                 [control + 'Alpha' + control, control])
        self.assertEqual(parse_strings('\t\u0085\u00a0\u2000Alpha\u3000\n\u2007// header\n'), ['Alpha'])
        self.assertEqual(parse_strings('Alpha\rBeta\n'), ['Alpha\rBeta'])

    def test_malformed_bom_payloads_are_diagnosed_without_partial_entries(self):
        for name, content in [('UTF16', codecs.BOM_UTF16_LE + b'A'),
                              ('UTF32', codecs.BOM_UTF32_BE + b'\x00\x00\x00A\x00'),
                              ('UTF8', codecs.BOM_UTF8 + b'Valid\nInvalid\xff')]:
            with self.subTest(name=name):
                self.write('Languages/English/Strings/WordLists/Broken.txt', content)
                result = scan_mod(self.source)
                self.assertEqual(result.entries, [])
                self.assertTrue(any(d['code'] == 'strings-read' for d in result.diagnostics))

    def test_serializer_rejects_first_line_bom_that_reader_would_consume(self):
        entries = [Entry(f'Strings:WordLists/Names.txt:line_{index}', 'Strings',
                         'WordLists/Names.txt', f'line_{index}', english, 'source')
                   for index, english in enumerate(['First', 'Second'])]
        translations = {entries[0].id: '最\ufeff初', entries[1].id: '\ufeff次'}
        # Interior and later-line U+FEFF are content, unlike the file-leading mark.
        raw = serialize_string_entries(entries, translations)
        self.assertEqual(parse_strings(decode_strings(raw)), ['最\ufeff初', '\ufeff次'])
        translations[entries[0].id] = '\ufeff最初'
        with self.assertRaises(ValueError):
            serialize_string_entries(list(reversed(entries)), translations)


if __name__ == '__main__':
    unittest.main()

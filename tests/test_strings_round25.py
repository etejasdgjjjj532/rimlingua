"""WordInfo diagnostics distinguish grammar metadata from translatable lists."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod


class WordInfoRound25Tests(unittest.TestCase):
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

    def test_fixed_gender_files_are_diagnosed_as_metadata_without_manual_xml_keys(self):
        for name in ('Male', 'Female', 'Neuter'):
            self.write(f'Languages/English/WordInfo/Gender/{name}.txt', 'reference term\n// literal physical line')
        result = scan_mod(self.source)
        self.assertEqual(result.entries, [])
        diagnostics = [d for d in result.diagnostics if d['code'] == 'wordinfo-gender-unsupported']
        self.assertEqual({d['source_file'] for d in diagnostics}, {
            f'Languages/English/WordInfo/Gender/{name}.txt' for name in ('Male', 'Female', 'Neuter')})
        self.assertTrue(all(not d['entry_id'] and 'physical lines' in d['message'] for d in diagnostics))
        self.assertTrue(all('manual key' not in d['suggestion'] for d in result.diagnostics))

    def test_symbolic_wordinfo_is_unverified_and_file_contents_are_never_decoded(self):
        external = self.root / 'outside.txt'
        external.write_bytes(b'foreign\xff')
        linked = self.source / 'Languages/English/WordInfo/Gender/Male.txt'
        linked.parent.mkdir(parents=True)
        linked.symlink_to(external)
        regular = self.write('Languages/English/WordInfo/Gender/Female.txt', 'placeholder')
        regular.write_bytes(b'unknown encoding\xff')
        result = scan_mod(self.source)
        self.assertEqual(result.entries, [])
        diagnostics = {d['source_file']: d for d in result.diagnostics}
        self.assertEqual(diagnostics['Languages/English/WordInfo/Gender/Male.txt']['code'], 'wordinfo-unsupported')
        self.assertEqual(diagnostics['Languages/English/WordInfo/Gender/Female.txt']['code'], 'wordinfo-gender-unsupported')
        limited = scan_mod(self.source, diagnostic_limit=1)
        self.assertLessEqual(len(limited.diagnostics), 1)
        self.assertGreater(limited.warning_count, len(limited.diagnostics))
        self.assertEqual(external.read_bytes(), b'foreign\xff')

    def test_lut_registration_is_unverified_and_unknown_files_do_not_get_fake_keys(self):
        self.write('Languages/English/WordInfo/Inflections.txt', 'lookup;form one;form two')
        for relative in ('Gender/male.txt', 'Gender/Other.txt', 'Custom/Names.txt'):
            self.write('Languages/English/WordInfo/' + relative, 'Never import')
        result = scan_mod(self.source)
        self.assertEqual(result.entries, [])
        diagnostics = {d['source_file']: d for d in result.diagnostics}
        self.assertIn('Languages/English/WordInfo/Inflections.txt', diagnostics)
        lut = diagnostics['Languages/English/WordInfo/Inflections.txt']
        self.assertEqual(lut['code'], 'wordinfo-lut-unverified')
        self.assertIn('RegisterLut', lut['suggestion'])
        for relative in ('Gender/male.txt', 'Gender/Other.txt', 'Custom/Names.txt'):
            self.assertEqual(diagnostics['Languages/English/WordInfo/' + relative]['code'], 'wordinfo-unsupported')

    def test_wordinfo_diagnostics_follow_version_precedence_and_target_ownership(self):
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li>Common</li><li>1.6</li></v1.6>'
                   '<v1.10><li>Common</li><li>1.10</li></v1.10></loadFolders>')
        for folder in ('Common', '1.6', '1.10'):
            self.write(f'{folder}/Languages/English/WordInfo/Gender/Male.txt', folder)
        self.write('1.6/Languages/English/WordInfo/Gender/Female.txt', 'Old only')
        context = self.root / 'context'
        self.write('Languages/English/WordInfo/Gender/Neuter.txt', 'Foreign', base=context)
        before = {p: p.read_bytes() for p in self.root.rglob('*.txt')}
        for version, expected in [('1.6', {'1.6/Languages/English/WordInfo/Gender/Male.txt',
                                           '1.6/Languages/English/WordInfo/Gender/Female.txt'}),
                                  ('1.10', {'1.10/Languages/English/WordInfo/Gender/Male.txt'})]:
            for cache in (None, self.root / 'cache.sqlite'):
                with self.subTest(version=version, cache=cache):
                    result = scan_mod(self.source, game_version=version, context_sources=[context], cache_path=cache)
                    self.assertEqual(result.entries, [])
                    self.assertEqual({d['source_file'] for d in result.diagnostics
                                      if d['code'].startswith('wordinfo-')}, expected)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.txt')})


if __name__ == '__main__':
    unittest.main()

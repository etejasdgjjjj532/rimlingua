"""Keyed scalar values ignore inert processing instructions without losing text."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod


class KeyedScalarProcessingInstructionTests(unittest.TestCase):
    versions = ('1.3', '1.4', '1.5', '1.6')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.cache = Path(self.temp.name) / 'cache.sqlite'
        self.clear_memory()
        self.addCleanup(self.clear_memory)
        self.write('About/About.xml', '<ModMetaData><packageId>test.keyed.scalar</packageId>'
                   '<supportedVersions><li>1.3</li><li>1.4</li><li>1.5</li><li>1.6</li>'
                   '</supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders>' + ''.join(
            '<v' + v + '><li>' + v + '</li></v' + v + '>' for v in self.versions)
            + '</loadFolders>')

    def write(self, name, text):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    @staticmethod
    def clear_memory():
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def assert_modes(self, body, expected, nested=False):
        for version in self.versions:
            self.write(version + '/Languages/English/Keyed/messages.xml',
                       '<LanguageData>' + body.replace('VERSION', version) + '</LanguageData>')
        before = {p: p.read_bytes() for p in self.source.rglob('*.xml')}
        for version in self.versions:
            for mode in ('uncached', 'sqlite-first', 'memory', 'sqlite-restored'):
                with self.subTest(version=version, mode=mode):
                    if mode == 'sqlite-restored':
                        self.clear_memory()
                    result = scan_mod(self.source, game_version=version,
                                      cache_path=None if mode == 'uncached' else self.cache)
                    self.assertEqual({e.key: e.english for e in result.entries},
                                     {k: v.replace('VERSION', version) for k, v in expected.items()})
                    self.assertEqual(any('Nested Keyed entry skipped' in w for w in result.warnings), nested)
                    if mode == 'memory':
                        self.assertEqual(result.stats['memory_hits'], 1)
                    if mode == 'sqlite-restored':
                        self.assertEqual(result.stats['parsed_files'], 0)
                        self.assertEqual(result.stats['cached_files'], 1)
        self.assertEqual(before, {p: p.read_bytes() for p in self.source.rglob('*.xml')})

    def test_internal_instructions_preserve_scalar_text_for_each_version_and_cache(self):
        self.assert_modes('<Greeting>hello <?probe secret?>VERSION<?other hidden?> world</Greeting>'
                          '<TailOnly><?probe hidden?>tail VERSION</TailOnly>'
                          '<Plain>plain VERSION</Plain>',
                          {'Greeting': 'hello VERSION world', 'TailOnly': 'tail VERSION',
                           'Plain': 'plain VERSION'})

    def test_actual_nested_elements_remain_excluded(self):
        self.assert_modes('<Nested>head<?probe hidden?><part>body</part>tail</Nested>'
                          '<Plain>plain VERSION</Plain>', {'Plain': 'plain VERSION'}, nested=True)

    def test_instruction_only_value_does_not_become_instruction_data(self):
        self.assert_modes('<Empty><?probe never translate this?></Empty>'
                          '<Plain>plain VERSION</Plain>', {'Plain': 'plain VERSION'})


if __name__ == '__main__':
    unittest.main()

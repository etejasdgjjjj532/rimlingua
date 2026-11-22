import tempfile
import unittest
from pathlib import Path

from rimworld_translator import platforms
from rimworld_translator.platforms import CACHE_MARKER, clear_app_cache, clear_app_cache_report, mark_cache_folder


class CacheOwnershipTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name) / 'cache'

    def test_schema_is_not_a_known_cache_subfolder(self):
        self.assertNotIn('schema', platforms.CACHE_SUBFOLDERS)

    def test_unmarked_folder_is_left_alone_and_reported(self):
        (self.cache / 'game-table').mkdir(parents=True)
        (self.cache / 'game-table/mine.txt').write_text('user data')
        removed, skipped = clear_app_cache_report(self.cache)
        self.assertEqual((removed, skipped), (0, ['game-table']))
        self.assertTrue((self.cache / 'game-table/mine.txt').exists())
        self.assertEqual(clear_app_cache(self.cache), 0)

    def test_marked_folder_is_removed(self):
        (self.cache / 'game-table').mkdir(parents=True)
        (self.cache / 'game-table/x.json.gz').write_bytes(b'x')
        mark_cache_folder(self.cache / 'game-table')
        self.assertTrue((self.cache / 'game-table' / CACHE_MARKER).is_file())
        self.assertEqual(clear_app_cache_report(self.cache), (1, []))
        self.assertFalse((self.cache / 'game-table').exists())

    def test_schema_folder_of_the_user_is_never_touched(self):
        (self.cache / 'schema').mkdir(parents=True)
        (self.cache / 'schema/keep.txt').write_text('keep')
        mark_cache_folder(self.cache / 'schema')
        clear_app_cache(self.cache)
        self.assertTrue((self.cache / 'schema/keep.txt').exists())


if __name__ == '__main__':
    unittest.main()

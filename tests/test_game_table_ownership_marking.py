"""The game-table cache folder is marked as editor-owned only when the editor itself creates it."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rimworld_translator import schema
from rimworld_translator.platforms import CACHE_MARKER


class GameTableOwnershipMarkingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dll = self.root / 'Assembly-CSharp.dll'
        self.dll.write_bytes(b'fake assembly')
        (self.root / 'game').mkdir()

    def run_schema(self, cache):
        table = {'types': {}, 'rimworld_version': '1.6', 'format': schema.GAME_TABLE_FORMAT}
        with mock.patch('rimworld_translator.game_library.game_dll', return_value=self.dll), \
                mock.patch.object(schema, 'build_game_table', return_value=table):
            return schema.game_table_schema(cache, [self.root / 'game'])

    def test_preexisting_folder_with_only_json_gz_is_not_marked(self):
        cache = self.root / 'game-table'
        cache.mkdir()
        (cache / 'user-file.json.gz').write_bytes(b'not ours')
        self.assertIsNotNone(self.run_schema(cache))
        self.assertFalse((cache / CACHE_MARKER).exists())

    def test_preexisting_empty_folder_is_not_marked(self):
        cache = self.root / 'game-table'
        cache.mkdir()
        self.assertIsNotNone(self.run_schema(cache))
        self.assertFalse((cache / CACHE_MARKER).exists())

    def test_folder_created_by_the_editor_is_marked(self):
        cache = self.root / 'game-table'
        self.assertIsNotNone(self.run_schema(cache))
        self.assertTrue((cache / CACHE_MARKER).is_file())


if __name__ == '__main__':
    unittest.main()

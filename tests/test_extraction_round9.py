"""Persistent XML caches preserve XPath text and target-only ownership."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest

from lxml import etree as LX

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod


class PersistentXMLCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'target'
        self.context = self.root / 'context'
        self.cache = self.root / 'cache.sqlite'
        self.clear_memory()
        self.addCleanup(self.clear_memory)
        about = self.source / 'About/About.xml'
        about.parent.mkdir(parents=True)
        about.write_text('<ModMetaData><packageId>test.tail</packageId><supportedVersions>'
                         + ''.join('<li>' + v + '</li>' for v in ['1.3', '1.4', '1.5', '1.6'])
                         + '</supportedVersions></ModMetaData>', encoding='utf-8')
        context = self.context / 'Defs/desk.xml'
        context.parent.mkdir(parents=True)
        context.write_text('<Defs><ThingDef><defName>Desk</defName><label>foreign desk</label>'
                           '<description>head<part>mid<inner>dle</inner>nested</part>tail</description>'
                           '</ThingDef></Defs>', encoding='utf-8')
        for version in ['1.3', '1.4', '1.5', '1.6']:
            patch = self.source / version / 'Patches/tail.xml'
            patch.parent.mkdir(parents=True)
            patch.write_text('<Patch><Operation Class="PatchOperationAdd">'
                             '<xpath>Defs/ThingDef[string(description)="headmiddlenestedtail"]</xpath>'
                             '<value><labelShort>target ' + version + '</labelShort></value>'
                             '</Operation></Patch>', encoding='utf-8')

    @staticmethod
    def clear_memory():
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def scan(self, version='1.6', cached=True):
        return scan_mod(self.source, game_version=version, context_sources=[self.context],
                        cache_path=self.cache if cached else None)

    def assert_target(self, scan, version):
        self.assertEqual({e.key: e.english for e in scan.entries},
                         {'Desk.labelShort': 'target ' + version})
        self.assertEqual(scan.stats['patches_applied'], 1)

    def test_disk_cache_matches_uncached_and_memory_for_each_declared_version(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        for version in ['1.3', '1.4', '1.5', '1.6']:
            with self.subTest(version=version):
                self.assert_target(self.scan(version, cached=False), version)
                self.assert_target(self.scan(version), version)
                memory = self.scan(version)
                self.assert_target(memory, version)
                self.assertEqual(memory.stats['memory_hits'], 2)
                self.clear_memory()
                disk = self.scan(version)
                self.assert_target(disk, version)
                self.assertEqual(disk.stats['parsed_files'], 0)
                self.assertEqual(disk.stats['cached_files'], 2)
                self.assertEqual(disk.stats['memory_hits'], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_legacy_tail_less_rows_are_ignored_without_deleting_existing_data(self):
        def legacy(node):
            return [node.tag, dict(node.attrib), node.text, [legacy(c) for c in node]]
        rows = []
        for path in [self.context / 'Defs/desk.xml', self.source / '1.6/Patches/tail.xml']:
            raw = path.read_bytes()
            rows.append((str(path.resolve()), hashlib.sha256(raw).hexdigest(),
                         json.dumps(legacy(LX.fromstring(raw)))))
        with closing(sqlite3.connect(self.cache)) as db:
            with db:
                db.execute('CREATE TABLE xml_index_v2 (path TEXT PRIMARY KEY, sha TEXT, tree BLOB)')
                db.executemany('INSERT INTO xml_index_v2 VALUES (?,?,?)', rows)
                db.execute('CREATE TABLE preserved_user_data (value TEXT)')
                db.execute('INSERT INTO preserved_user_data VALUES (?)', ('keep me',))
        scan = self.scan()
        self.assert_target(scan, '1.6')
        self.assertEqual(scan.stats['parsed_files'], 2)
        self.assertEqual(scan.stats['cached_files'], 0)
        with closing(sqlite3.connect(self.cache)) as db:
            self.assertEqual(db.execute('SELECT * FROM xml_index_v2 ORDER BY path').fetchall(), sorted(rows))
            self.assertEqual(db.execute('SELECT value FROM preserved_user_data').fetchall(), [('keep me',)])
        self.clear_memory()
        restored = self.scan()
        self.assert_target(restored, '1.6')
        self.assertEqual(restored.stats['parsed_files'], 0)
        self.assertEqual(restored.stats['cached_files'], 2)


if __name__ == '__main__':
    unittest.main()

"""XML cache preserves processing instructions as inert XPath nodes."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from lxml import etree as LX

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod


class ProcessingInstructionCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.cache = self.root / 'cache.sqlite'
        self.clear_memory()
        self.addCleanup(self.clear_memory)
        self.write('About/About.xml', '<ModMetaData><packageId>test.pi</packageId></ModMetaData>')
        self.write('Defs/item.xml', '<Defs><ThingDef><defName>Item</defName>'
                   '<label>own item</label></ThingDef></Defs>')
        self.write('Patches/pi.xml', '<Patch><?probe preserve?><Operation Class="PatchOperationAdd">'
                   '<xpath>Defs/ThingDef[defName="Item"]</xpath>'
                   '<value><description>added text</description></value></Operation></Patch>')

    def write(self, name, xml):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding='utf-8')

    @staticmethod
    def clear_memory():
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def scan(self, cached=True):
        return scan_mod(self.source, cache_path=self.cache if cached else None)

    def assert_modes(self, expected=None, file_count=2):
        if expected is None:
            expected = {'Item.label': 'own item', 'Item.description': 'added text'}
        before = {p: p.read_bytes() for p in self.source.rglob('*.xml')}
        for mode in ['uncached', 'sqlite-first', 'memory', 'sqlite-restored']:
            with self.subTest(mode=mode):
                if mode == 'sqlite-restored':
                    self.clear_memory()
                scan = self.scan(cached=mode != 'uncached')
                self.assertEqual({e.key: e.english for e in scan.entries}, expected)
                if mode == 'memory':
                    self.assertEqual(scan.stats['memory_hits'], file_count)
                elif mode == 'sqlite-restored':
                    self.assertEqual(scan.stats['parsed_files'], 0)
                    self.assertEqual(scan.stats['cached_files'], file_count)
                    self.assertEqual(scan.stats['memory_hits'], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.source.rglob('*.xml')})

    def test_patch_processing_instruction_does_not_stop_persistent_cache_scan(self):
        self.assert_modes()

    def test_instruction_target_data_tail_and_position_keep_xpath_conditions(self):
        # The marker is removed by a real patch after its XPath node semantics
        # choose the description. No PI is interpreted as executable content.
        self.write('Defs/item.xml', '<Defs><ThingDef><defName>Item</defName>'
                   '<label>own item</label><marker>head<?probe preserve?>middle'
                   '<part/>end<?other keep?>last</marker></ThingDef></Defs>')
        self.write('Patches/pi.xml', '<Patch><?probe preserve?>tail'
                   '<Operation Class="PatchOperationAdd"><xpath>'
                   'Defs/ThingDef[string(marker)="headmiddleendlast" and '
                   'count(marker/node())=7 and name(marker/node()[2])="probe" and '
                   'string(marker/processing-instruction("probe"))="preserve" and '
                   'name(marker/node()[6])="other" and marker/text()[4]="last"]'
                   '</xpath><value><description>added text</description></value></Operation>'
                   '<Operation Class="PatchOperationRemove"><xpath>Defs/ThingDef/marker</xpath>'
                   '</Operation></Patch>')
        self.assert_modes()

    def test_inert_instructions_do_not_hide_text_or_change_list_indices(self):
        self.write('Defs/item.xml', '<Defs><?probe root?><ThingDef><?probe field?>'
                   '<defName>Item</defName><label>own <?probe ignored?>item</label>'
                   '<rulesStrings><?probe before?><li>first <?probe inside?>rule</li>'
                   '<?probe between?><li>second rule</li><?probe after?></rulesStrings>'
                   '</ThingDef></Defs>')
        self.assert_modes({'Item.label': 'own item', 'Item.description': 'added text',
                           'Item.rulesStrings.0': 'first rule',
                           'Item.rulesStrings.1': 'second rule'})

    def test_sequence_instruction_does_not_stop_following_operations(self):
        self.write('Patches/pi.xml', '<Patch><Operation Class="PatchOperationSequence">'
                   '<operations><?probe inert?><li Class="PatchOperationAdd">'
                   '<xpath>Defs/ThingDef</xpath><value><description>added text</description>'
                   '</value></li></operations></Operation></Patch>')
        self.assert_modes()

    def test_keyed_root_instruction_is_not_a_translation_key(self):
        self.write('Languages/English/Keyed/messages.xml', '<LanguageData><?probe inert?>'
                   '<Greeting>hello</Greeting></LanguageData>')
        self.assert_modes({'Item.label': 'own item', 'Item.description': 'added text',
                           'Greeting': 'hello'}, file_count=3)

    def test_catalog_root_instruction_is_not_counted_as_candidate(self):
        self.write('Languages/English/DefInjected/ThingDef/items.xml',
                   '<LanguageData><?probe inert?><Item.description>added text</Item.description>'
                   '</LanguageData>')
        self.assert_modes(file_count=3)
        scan = self.scan()
        self.assertEqual(scan.stats['catalog_candidates'], 1)
        self.assertEqual(scan.stats['catalog_matches'], 1)

    def test_existing_v3_element_rows_remain_readable_without_reparse(self):
        # A pre-fix v3 cache can contain ordinary element nodes but cannot have
        # serialized PIs. Its five-item element payload must remain readable.
        self.write('Patches/pi.xml', '<Patch><Operation Class="PatchOperationAdd">'
                   '<xpath>Defs/ThingDef[defName="Item"]</xpath>'
                   '<value><description>added text</description></value></Operation></Patch>')
        def legacy(node):
            return [node.tag, dict(node.attrib), node.text, node.tail,
                    [legacy(child) for child in node]]
        rows = []
        for path in [self.source / 'Defs/item.xml', self.source / 'Patches/pi.xml']:
            raw = path.read_bytes()
            rows.append((str(path.resolve()), hashlib.sha256(raw).hexdigest(),
                         json.dumps(legacy(LX.fromstring(raw)))))
        with closing(sqlite3.connect(self.cache)) as db:
            with db:
                db.execute('CREATE TABLE xml_index_v3 (path TEXT PRIMARY KEY, sha TEXT, tree BLOB)')
                db.executemany('INSERT INTO xml_index_v3 VALUES (?,?,?)', rows)
        scan = self.scan()
        self.assertEqual({e.key: e.english for e in scan.entries},
                         {'Item.label': 'own item', 'Item.description': 'added text'})
        self.assertEqual(scan.stats['parsed_files'], 0)
        self.assertEqual(scan.stats['cached_files'], 2)
        with closing(sqlite3.connect(self.cache)) as db:
            self.assertEqual(db.execute('SELECT * FROM xml_index_v3 ORDER BY path').fetchall(), sorted(rows))


if __name__ == '__main__':
    unittest.main()

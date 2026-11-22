"""PatchOperationAdd preserves text children without broadening ownership."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod


class AddTextPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'target'
        self.context = self.root / 'context'

    def write(self, root, relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def scan(self, operation, description='base', foreign=False):
        self.write(self.context if foreign else self.target, 'Defs/item.xml',
                   '<Defs><ThingDef><defName>Desk</defName><label>desk</label>'
                   '<description>' + description + '</description><texPath Class="InternalTag">Internal/Desk</texPath></ThingDef></Defs>')
        self.write(self.target, 'Patches/add.xml', '<Patch>' + operation + '</Patch>')
        return scan_mod(self.target, context_sources=[self.context] if foreign else [])

    def add(self, xpath, value, order='Append'):
        return ('<Operation Class="PatchOperationAdd"><xpath>' + xpath + '</xpath>'
                '<order>' + order + '</order><value>' + value + '</value></Operation>')

    def values(self, result):
        return {entry.key: entry.english for entry in result.entries}

    def test_append_text_payload_updates_existing_description(self):
        result = self.scan(self.add('Defs/ThingDef/description', ' plus'))
        self.assertEqual(self.values(result), {'Desk.label': 'desk', 'Desk.description': 'base plus'})
        self.assertEqual(result.stats['patches_applied'], 1)

    def test_prepend_text_payload_keeps_order(self):
        result = self.scan(self.add('Defs/ThingDef/description', 'before ', 'Prepend'))
        self.assertEqual(self.values(result)['Desk.description'], 'before base')

    def test_empty_external_field_gets_target_text_but_other_fields_stay_foreign(self):
        result = self.scan(self.add('Defs/ThingDef/description', 'target description'), '', True)
        self.assertEqual(self.values(result), {'Desk.description': 'target description'})
        self.assertEqual(result.entries[0].source_file, 'Patches/add.xml')

    def test_external_changed_field_contains_final_text_without_foreign_label(self):
        result = self.scan(self.add('Defs/ThingDef/description', ' plus'), foreign=True)
        self.assertEqual(self.values(result), {'Desk.description': 'base plus'})

    def test_internal_value_is_not_promoted_by_patch_ownership(self):
        result = self.scan(self.add('Defs/ThingDef/texPath', '/Variant'), foreign=True)
        self.assertEqual(self.values(result), {})
        self.assertEqual(result.stats['patches_applied'], 1)

    def test_attribute_and_text_xpath_remain_unverified(self):
        for xpath in ('Defs/ThingDef/description/text()', 'Defs/ThingDef/texPath/@Class'):
            with self.subTest(xpath=xpath):
                result = self.scan(self.add(xpath, ' unsupported'), foreign=True)
                self.assertEqual(self.values(result), {})
                self.assertEqual(result.stats['patches_applied'], 0)
                self.assertTrue(any(item['code'] == 'patch-xpath' for item in result.diagnostics))

    def test_mixed_payload_and_existing_tail_keep_append_and_prepend_order(self):
        for order, expected in [('Append', 'baseoldendleadnewtail'),
                                ('Prepend', 'leadnewtailbaseoldend')]:
            with self.subTest(order=order):
                operation = self.add('Defs/ThingDef/description', 'lead<part>new</part>tail', order)
                operation += ('<Operation Class="PatchOperationReplace"><xpath>'
                              'Defs/ThingDef[string(description)="' + expected + '"]/label</xpath>'
                              '<value><label>matched order</label></value></Operation>')
                result = self.scan(operation, 'base<part>old</part>end')
                self.assertEqual(self.values(result)['Desk.label'], 'matched order')
                self.assertEqual(result.stats['patches_applied'], 2)


if __name__ == '__main__':
    unittest.main()

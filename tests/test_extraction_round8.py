"""Attribute patch success depends on eligible nodes, not just XPath matches."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_versions

FIXTURE = Path(__file__).parent / 'fixtures/round8-extraction'


class AttributePatchTests(unittest.TestCase):
    def values(self, scan):
        return {entry.key: entry.english for entry in scan.entries}

    def test_declared_versions_stop_on_attribute_noop_and_invert_failure(self):
        before = {str(p): p.read_bytes() for p in FIXTURE.rglob('*') if p.is_file()}
        result = scan_declared_versions(FIXTURE / 'target', contexts={
            v: {'context_sources': [FIXTURE / 'context']} for v in ['1.3', '1.4', '1.5', '1.6']})
        self.assertEqual(result.failures, {})
        expected = {'1.3': {}, '1.4': {},
                    '1.5': {'Desk.description': 'inverted add failure'},
                    '1.6': {'Desk.description': 'inverted remove failure'}}
        for version, values in expected.items():
            with self.subTest(version=version):
                self.assertEqual(self.values(result.scans[version]), values)
        self.assertEqual(before, {str(p): p.read_bytes() for p in FIXTURE.rglob('*') if p.is_file()})

    def sequence(self, kind, attribute='Marker', success='Normal', selector='Defs/ThingDef'):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        source = Path(temp.name)
        path = source / 'Patches/attribute.xml'
        path.parent.mkdir()
        path.write_text('<Patch><Operation Class="PatchOperationSequence"><operations>'
                        '<li Class="PatchOperationAttribute' + kind + '"><success>' + success +
                        '</success><xpath>Defs/ThingDef</xpath><attribute>' + attribute +
                        '</attribute><value>replacement</value></li>'
                        '<li Class="PatchOperationAdd"><xpath>' + selector + '</xpath>'
                        '<value><description>continued</description></value></li>'
                        '</operations></Operation></Patch>', encoding='utf-8')
        return source

    def test_add_existing_attribute_always_does_not_overwrite_it(self):
        source = self.sequence('Add', success='Always', selector="Defs/ThingDef[@Marker='original']")
        scan = scan_mod(source, context_sources=[FIXTURE / 'context'])
        self.assertEqual(self.values(scan), {'Desk.description': 'continued'})

    def test_add_missing_attribute_allows_following_patch(self):
        source = self.sequence('Add', attribute='Absent', selector="Defs/ThingDef[@Absent='replacement']")
        self.assertEqual(self.values(scan_mod(source, context_sources=[FIXTURE / 'context'])),
                         {'Desk.description': 'continued'})

    def test_remove_existing_attribute_allows_following_patch(self):
        source = self.sequence('Remove', selector='Defs/ThingDef[not(@Marker)]')
        self.assertEqual(self.values(scan_mod(source, context_sources=[FIXTURE / 'context'])),
                         {'Desk.description': 'continued'})

    def test_set_updates_existing_and_creates_missing_attributes(self):
        for attribute in ['Marker', 'Absent']:
            with self.subTest(attribute=attribute):
                source = self.sequence('Set', attribute=attribute,
                                       selector="Defs/ThingDef[@" + attribute + "='replacement']")
                self.assertEqual(self.values(scan_mod(source, context_sources=[FIXTURE / 'context'])),
                                 {'Desk.description': 'continued'})

    def test_add_mixed_nodes_preserves_existing_attribute_and_succeeds_if_any_added(self):
        source = self.sequence('Add', selector="Defs/ThingDef[(defName='Desk' and @Marker='original') or (defName='Chair' and @Marker='replacement')]")
        context = source / 'context/Defs/items.xml'
        context.parent.mkdir(parents=True)
        context.write_text('<Defs><ThingDef Marker="original"><defName>Desk</defName>'
                           '<label>foreign desk</label></ThingDef><ThingDef><defName>Chair</defName>'
                           '<label>foreign chair</label></ThingDef></Defs>', encoding='utf-8')
        self.assertEqual(self.values(scan_mod(source, context_sources=[source / 'context'])),
                         {'Desk.description': 'continued', 'Chair.description': 'continued'})

    def test_remove_mixed_nodes_succeeds_if_any_attribute_removed(self):
        source = self.sequence('Remove', selector='Defs/ThingDef[not(@Marker)]')
        context = source / 'context/Defs/items.xml'
        context.parent.mkdir(parents=True)
        context.write_text('<Defs><ThingDef Marker="original"><defName>Desk</defName></ThingDef>'
                           '<ThingDef><defName>Chair</defName></ThingDef></Defs>', encoding='utf-8')
        self.assertEqual(self.values(scan_mod(source, context_sources=[source / 'context'])),
                         {'Desk.description': 'continued', 'Chair.description': 'continued'})


if __name__ == '__main__':
    unittest.main()

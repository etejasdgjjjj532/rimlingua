"""Patch success modifiers govern sequence control without inventing effects."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.multiversion import scan_declared_versions

FIXTURE = Path(__file__).parent / 'fixtures/round7-extraction'


class PatchSuccessTests(unittest.TestCase):
    def values(self, scan):
        return {e.key: e.english for e in scan.entries}

    def test_declared_versions_apply_test_success_independently(self):
        source = FIXTURE / 'target'
        before = {str(p): p.read_bytes() for p in FIXTURE.rglob('*') if p.is_file()}
        scans = scan_declared_versions(source, contexts={
            v: {'context_sources': [FIXTURE / 'context']} for v in ['1.3', '1.4', '1.5', '1.6']})
        self.assertEqual(scans.failures, {})
        self.assertEqual({v: self.values(s) for v, s in scans.scans.items()}, {
            '1.3': {'Desk.description': 'inverted absence'},
            '1.4': {},
            '1.5': {'Desk.description': 'forced success'},
            '1.6': {'Desk.description': 'normal success'}})
        self.assertEqual(before, {str(p): p.read_bytes() for p in FIXTURE.rglob('*') if p.is_file()})

    def sequence(self, first, wrapper_success='Normal'):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        source = Path(temp.name)
        patch = source / 'Patches/operations.xml'
        patch.parent.mkdir()
        patch.write_text('<Patch><Operation Class="PatchOperationSequence"><success>'
                         + wrapper_success + '</success><operations>' + first +
                         '<li Class="PatchOperationAdd"><xpath>Defs/ThingDef</xpath>'
                         '<value><description>continued</description></value></li>'
                         '</operations></Operation></Patch>', encoding='utf-8')
        return scan_mod(source, context_sources=[FIXTURE / 'context'])

    def test_add_never_keeps_own_mutation_but_stops_following_operation(self):
        scan = self.sequence('<li Class="PatchOperationAdd"><success>Never</success>'
                             '<xpath>Defs/ThingDef</xpath><value><labelShort>changed</labelShort></value></li>')
        self.assertEqual(self.values(scan), {'Desk.labelShort': 'changed'})

    def test_failed_supported_operation_always_continues(self):
        scan = self.sequence('<li Class="PatchOperationRemove"><success>Always</success>'
                             '<xpath>Defs/ThingDef/nonexistent</xpath></li>')
        self.assertEqual(self.values(scan), {'Desk.description': 'continued'})

    def test_unsupported_operation_cannot_be_promoted_to_known_success(self):
        scan = self.sequence('<li Class="UnknownOperation"><success>Always</success></li>')
        self.assertEqual(self.values(scan), {})
        self.assertTrue(any(d['code'] == 'patch-unsupported' for d in scan.diagnostics))

    def test_invalid_xpath_cannot_be_inverted_or_forced_to_success(self):
        for success in ['Invert', 'Always']:
            with self.subTest(success=success):
                scan = self.sequence('<li Class="PatchOperationTest"><success>' + success +
                                     '</success><xpath>Defs[</xpath></li>')
                self.assertEqual(self.values(scan), {})
                self.assertTrue(any(d['code'] == 'patch-xpath' for d in scan.diagnostics))

    def test_unknown_success_does_not_mutate_or_continue(self):
        scan = self.sequence('<li Class="PatchOperationAdd"><success>Unknown</success>'
                             '<xpath>Defs/ThingDef</xpath><value><labelShort>wrong</labelShort></value></li>')
        self.assertEqual(self.values(scan), {})
        self.assertTrue(any(d['code'] == 'patch-success' for d in scan.diagnostics))

    def test_nested_sequence_applies_its_own_modifier(self):
        first = ('<li Class="PatchOperationSequence"><success>Invert</success><operations>'
                 '<li Class="PatchOperationTest"><xpath>Defs/ThingDef/missing</xpath></li>'
                 '</operations></li>')
        self.assertEqual(self.values(self.sequence(first)), {'Desk.description': 'continued'})

    def test_nested_unknown_result_is_not_inverted_into_success(self):
        first = ('<li Class="PatchOperationSequence"><success>Invert</success><operations>'
                 '<li Class="UnknownOperation"/></operations></li>')
        self.assertEqual(self.values(self.sequence(first)), {})


if __name__ == '__main__':
    unittest.main()

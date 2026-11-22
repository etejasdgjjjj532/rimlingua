"""Patch-added scalar tails retain target ownership in external definitions."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod


class PatchScalarTailOwnershipTests(unittest.TestCase):
    versions = ('1.3', '1.4', '1.5', '1.6')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.context = self.root / 'context'
        self.cache = self.root / 'cache.sqlite'
        self.clear_memory()
        self.addCleanup(self.clear_memory)
        for folder, package in ((self.source, 'test.patch.tail'),
                                (self.context, 'test.external.tail')):
            self.write(folder, 'About/About.xml',
                       '<ModMetaData><packageId>' + package + '</packageId>'
                       '<supportedVersions>' + ''.join('<li>' + v + '</li>' for v in self.versions)
                       + '</supportedVersions></ModMetaData>')
            self.write(folder, 'LoadFolders.xml', '<loadFolders>' + ''.join(
                '<v' + v + '><li>' + v + '</li></v' + v + '>' for v in self.versions)
                + '</loadFolders>')
        for version in self.versions:
            self.write(self.context, version + '/Defs/external.xml',
                       '<Defs><ThingDef Name="ExternalBase" Abstract="True">'
                       '<label>external ' + version + '</label>'
                       '<description>external description must stay excluded</description>'
                       '</ThingDef><ThingDef ParentName="ExternalBase">'
                       '<defName>ExternalChild</defName></ThingDef>'
                       '<ThingDef><defName>Untouched</defName>'
                       '<label>unrelated external label</label></ThingDef></Defs>')

    @staticmethod
    def write(root, name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    @staticmethod
    def clear_memory():
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def assert_modes(self, order, value, expected, remove=''):
        for version in self.versions:
            self.write(self.source, version + '/Patches/tail.xml',
                       '<Patch><Operation Class="PatchOperationAdd" '
                       'MayRequire="test.external.tail"><xpath>'
                       'Defs/ThingDef[@Name="ExternalBase"]/label</xpath>'
                       '<order>' + order + '</order><value>'
                       + value.replace('VERSION', version) + '</value></Operation>'
                       + ('<Operation Class="PatchOperationRemove"><xpath>'
                          'Defs/ThingDef[@Name="ExternalBase"]/label/' + remove
                          + '</xpath></Operation>' if remove else '') + '</Patch>')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        for version in self.versions:
            for mode in ('uncached', 'sqlite-first', 'memory', 'sqlite-restored'):
                with self.subTest(version=version, mode=mode):
                    if mode == 'sqlite-restored':
                        self.clear_memory()
                    result = scan_mod(
                        self.source, game_version=version, context_sources=[self.context],
                        active_mods={'test.external.tail'},
                        cache_path=None if mode == 'uncached' else self.cache)
                    self.assertEqual({e.key: e.english for e in result.entries},
                                     {k: v.replace('VERSION', version) for k, v in expected.items()})
                    for entry in result.entries:
                        self.assertEqual(entry.source_file, version + '/Patches/tail.xml')
                    if mode == 'memory':
                        self.assertEqual(result.stats['memory_hits'], 2)
                    if mode == 'sqlite-restored':
                        self.assertEqual(result.stats['parsed_files'], 0)
                        self.assertEqual(result.stats['cached_files'], 2)
            excluded = scan_mod(self.source, game_version=version,
                                context_sources=[self.context], active_mods=set())
            self.assertEqual(excluded.entries, [])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_appended_pi_tail_owns_combined_external_scalar_and_inherited_child(self):
        self.assert_modes('Append', '<?probe inert?> added VERSION',
                          {'ExternalChild.label': 'external VERSION added VERSION'})

    def test_prepended_pi_tails_preserve_order_and_ownership(self):
        self.assert_modes('Prepend', '<?first inert?>added VERSION <?second inert?>then ',
                          {'ExternalChild.label': 'added VERSION then external VERSION'})

    def test_inert_only_patch_does_not_claim_external_text(self):
        self.assert_modes('Append', '<?probe do not translate?>', {})

    def test_removing_added_pi_preserves_independent_text_sibling(self):
        self.assert_modes('Append', '<?probe inert?> added VERSION',
                          {'ExternalChild.label': 'external VERSION added VERSION'},
                          remove='processing-instruction()')

    def test_removing_multiple_prepend_pis_preserves_tail_order(self):
        self.assert_modes('Prepend', '<?first inert?>added VERSION <?second inert?>then ',
                          {'ExternalChild.label': 'added VERSION then external VERSION'},
                          remove='processing-instruction()')

    def test_removing_element_preserves_its_following_text(self):
        self.assert_modes('Append', '<part>removed element text</part> added VERSION',
                          {'ExternalChild.label': 'external VERSION added VERSION'}, remove='part')


if __name__ == '__main__':
    unittest.main()

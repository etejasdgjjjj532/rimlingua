"""Preserve malformed editable text in JSON without allowing it into XML."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Entry, Project, Scan, export_mod, export_versions_test


VERSIONS = ('1.3', '1.4', '1.5', '1.6', '1.9', '1.10')
LABEL = 'DefInjected:ThingDef:Item.label'
OTHER = 'DefInjected:ThingDef:Other.label'


class VersionOutputRound8Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()

    def scan(self, version):
        return Scan(entries=[
            Entry(LABEL, 'DefInjected', 'ThingDef', 'Item.label', f'item {version}', 'items.xml'),
            Entry(OTHER, 'DefInjected', 'ThingDef', 'Other.label', 'other', 'items.xml'),
        ], name='Surrogate persistence', package_id='test.surrogates',
            versions=list(VERSIONS), stats={'active_version': version})

    def test_schema1_can_save_and_restore_lone_surrogate_for_later_repair(self):
        for index, character in enumerate(('\ud800', '\udfff')):
            with self.subTest(codepoint=hex(ord(character))):
                project = Project.create(self.source, self.scan('1.6'))
                path = self.root / f'workspace/legacy-{index}.json'
                project.set_translation(LABEL, '変更前')
                project.save(path)
                text = '要修正' + character + '訳'
                project.set_translation(LABEL, text)
                project.save(path)
                path.read_bytes().decode('utf-8')
                restored = Project.load(path)
                self.assertEqual(restored.schema, 1)
                self.assertEqual(restored.get_translation(LABEL), text)
                before = path.read_bytes()
                restored.save(path)
                self.assertEqual(path.read_bytes(), before)
                with self.assertRaises(ValueError):
                    export_mod(restored, self.root / f'legacy-output-{index}')

    def test_schema2_preserves_active_and_inactive_surrogates_and_safe_version_output(self):
        for index, (character, unsafe_version) in enumerate((
                ('\ud800', '1.3'), ('\udfff', '1.3'),
                ('\ud800', '1.10'), ('\udfff', '1.10'))):
            with self.subTest(codepoint=hex(ord(character)), unsafe_version=unsafe_version):
                project = Project.create_versions(self.source, {v: self.scan(v) for v in VERSIONS})
                for version in VERSIONS:
                    project.switch_version(version)
                    project.set_translation(LABEL, f'独立訳 {version}')
                    project.mark_reviewed(LABEL, approved=True)
                    project.set_translation(OTHER, f'安全訳 {version} \U0001f680')
                project.switch_version(unsafe_version)
                text = '要修正' + character + '訳'
                project.set_translation(LABEL, text)
                project.switch_version('1.10')
                path = self.root / f'workspace/versions-{index}.json'
                project.save(path)
                self.assertIn('独立訳'.encode('utf-8'), path.read_bytes())
                restored = Project.load(path)
                self.assertEqual(restored.schema, 2)
                self.assertEqual(restored.game_version, '1.10')
                before = path.read_bytes()
                restored.save(path)
                self.assertEqual(path.read_bytes(), before)
                target = self.root / f'output-{index}'
                warnings = export_versions_test(restored, target)
                self.assertTrue(any('Item.label' in warning and 'XML' in warning for warning in warnings))
                for version in VERSIONS:
                    restored.switch_version(version)
                    self.assertEqual(restored.get_translation(LABEL),
                                     text if version == unsafe_version else f'独立訳 {version}')
                    self.assertEqual(restored.entry_index()[LABEL].approved, version != unsafe_version)
                    xml = ET.parse(target / version / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml').getroot()
                    self.assertEqual(xml.findtext('Item.label'),
                                     None if version == unsafe_version else f'独立訳 {version}')
                    self.assertEqual(xml.findtext('Other.label'), f'安全訳 {version} \U0001f680')

    def test_surrogate_pairs_are_rejected_before_existing_project_is_replaced(self):
        for schema, unsafe_version in ((1, '1.6'), (2, '1.3'), (2, '1.10')):
            with self.subTest(schema=schema, unsafe_version=unsafe_version):
                project = (Project.create(self.source, self.scan('1.6')) if schema == 1
                           else Project.create_versions(self.source, {v: self.scan(v) for v in VERSIONS}))
                project.set_translation(LABEL, '保存済み訳')
                path = self.root / f'workspace/pair-{schema}-{unsafe_version}.json'
                project.save(path)
                before = path.read_bytes()
                if schema == 2:
                    project.switch_version(unsafe_version)
                project.set_translation(LABEL, '要修正' + '\ud83d\ude80' + '訳')
                if schema == 2:
                    project.switch_version('1.10')
                with self.assertRaisesRegex(ValueError, 'surrogate'):
                    project.save(path)
                self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()

"""XML-forbidden translation characters must not corrupt exported files."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_mod, export_versions_test
from rimworld_translator.multiversion import scan_declared_versions


LABEL = 'DefInjected:ThingDef:Item.label'
OTHER = 'DefInjected:ThingDef:Other.label'
INVALID = ('\x00', '\x08', '\x0b', '\x1f', '\ufffe', '\uffff')


class VersionOutputRound7Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        about = self.source / 'About/About.xml'
        about.parent.mkdir(parents=True)
        about.write_text('<ModMetaData><name>XML validation</name>'
                         '<packageId>test.xml</packageId><supportedVersions>'
                         '<li>1.5</li><li>1.6</li></supportedVersions></ModMetaData>')
        defs = self.source / 'Defs/items.xml'
        defs.parent.mkdir()
        defs.write_text('<Defs><ThingDef><defName>Item</defName><label>item</label>'
                        '</ThingDef><ThingDef><defName>Other</defName><label>other</label>'
                        '</ThingDef></Defs>')
        self.scans = scan_declared_versions(self.source).scans

    def xml(self, target, version):
        return target / version / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml'

    def test_test_output_omits_forbidden_characters_and_preserves_other_versions(self):
        for index, character in enumerate(INVALID):
            with self.subTest(codepoint=hex(ord(character))):
                project = Project.create_versions(self.source, self.scans)
                project.set_translation(LABEL, '旧版の訳')
                project.mark_reviewed(LABEL, approved=True)
                project.switch_version('1.6')
                project.set_translation(LABEL, '危険' + character + '訳')
                project.set_translation(OTHER, '安全な訳')
                saved = self.root / f'workspace/{index}.json'
                project.save(saved)
                restored = Project.load(saved)
                target = self.root / f'output-{index}'
                warnings = export_versions_test(restored, target)
                self.assertTrue(any('Item.label' in warning and 'XML' in warning
                                    for warning in warnings))
                xml = ET.parse(self.xml(target, '1.6')).getroot()
                self.assertIsNone(xml.find('Item.label'))
                self.assertEqual(xml.findtext('Other.label'), '安全な訳')
                self.assertEqual(ET.parse(self.xml(target, '1.5')).getroot()
                                 .findtext('Item.label'), '旧版の訳')
                self.assertEqual(restored.get_translation(LABEL), '危険' + character + '訳')
                restored.switch_version('1.5')
                self.assertTrue(restored.entry_index()[LABEL].approved)

    def test_legacy_export_rejects_forbidden_text_before_modifying_existing_output(self):
        project = Project.create(self.source, self.scans['1.6'])
        project.set_translation(LABEL, '元の訳')
        target = self.root / 'legacy'
        export_mod(project, target)
        before = {str(path.relative_to(target)): path.read_bytes()
                  for path in target.rglob('*') if path.is_file()}
        for character in (*INVALID, '\ud800', '\udfff'):
            with self.subTest(codepoint=hex(ord(character))):
                project.set_translation(LABEL, '危険' + character + '訳')
                with self.assertRaises(ValueError):
                    export_mod(project, target)
                self.assertEqual({str(path.relative_to(target)): path.read_bytes()
                                  for path in target.rglob('*') if path.is_file()}, before)

    def test_test_output_omits_lone_surrogates_without_stopping_safe_entries(self):
        for index, character in enumerate(('\ud800', '\udfff')):
            with self.subTest(codepoint=hex(ord(character))):
                project = Project.create_versions(self.source, self.scans)
                project.set_translation(LABEL, '危険' + character + '訳')
                project.set_translation(OTHER, '安全な訳')
                target = self.root / f'surrogate-{index}'
                warnings = export_versions_test(project, target)
                self.assertTrue(any('Item.label' in warning and 'XML' in warning
                                    for warning in warnings))
                xml = ET.parse(self.xml(target, '1.5')).getroot()
                self.assertIsNone(xml.find('Item.label'))
                self.assertEqual(xml.findtext('Other.label'), '安全な訳')

    def test_xml_legal_whitespace_and_unicode_still_roundtrip(self):
        project = Project.create_versions(self.source, self.scans)
        text = '翻訳\t<&>\n行\u0085\ue000\ufffd\U0001f680\U0010ffff'
        project.set_translation(LABEL, text)
        target = self.root / 'legal'
        warnings = export_versions_test(project, target)
        self.assertFalse(any('XML' in warning for warning in warnings))
        self.assertEqual(ET.parse(self.xml(target, '1.5')).getroot().findtext('Item.label'), text)


if __name__ == '__main__':
    unittest.main()

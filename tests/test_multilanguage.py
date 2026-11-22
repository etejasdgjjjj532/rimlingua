"""Check all installed RimWorld languages, safe per-language editing and combined mod output."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
import xml.etree.ElementTree as ET
from rimworld_translator.languages import discover_languages, validate_language
from rimworld_translator.core import Project, scan_mod, export_mod

class LanguageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix='rw-language-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'Defs').mkdir()
        (self.source / 'About/About.xml').write_text('<ModMetaData><name>Sample</name><packageId>mod.sample</packageId></ModMetaData>')
        (self.source / 'Defs/A.xml').write_text('<Defs><ThingDef><defName>Item</defName><label>item</label><description>Something {0}</description></ThingDef></Defs>')
        self.project = Project.create(self.source, scan_mod(self.source))
        self.project_file = self.root / 'project/project.json'
        self.output = self.root / 'project/mod'

    def test_every_installed_rimworld_language_is_discoverable(self):
        game = Path.home() / '.local/share/Steam/steamapps/common/RimWorld'
        if not (game / 'Data/Core/Languages').is_dir():
            self.skipTest('RimWorld is not installed in the known Steam location')
        languages = discover_languages()
        self.assertGreaterEqual(len(languages), 29)
        for name in ('English', 'Japanese', 'Korean', 'ChineseSimplified', 'ChineseTraditional', 'SpanishLatin', 'Catalan', 'Vietnamese'):
            self.assertIn(name, languages)
        self.assertIn('日本語', languages['Japanese'])
        self.assertIn('Español', languages['SpanishLatin'])

    def test_switch_save_reload_export_three_languages_and_thumbnail(self):
        self.project.entries[0].japanese = '日本語名'
        self.project.switch_language('French')
        self.assertEqual(self.project.entries[0].japanese, '')
        self.project.entries[0].japanese = 'nom français'
        self.project.switch_language('Korean')
        self.project.entries[0].japanese = '한국어 이름'
        self.project.switch_language('Japanese')
        self.assertEqual(self.project.entries[0].japanese, '日本語名')
        self.project.save(self.project_file)
        loaded = Project.load(self.project_file)
        self.assertEqual(loaded.language, 'Japanese')
        loaded.switch_language('French')
        self.assertEqual(loaded.entries[0].japanese, 'nom français')
        loaded.switch_language('Korean')
        self.assertEqual(loaded.entries[0].japanese, '한국어 이름')
        export_mod(loaded, self.output)
        for folder, expected in [('Japanese','日本語名'), ('French','nom français'), ('Korean','한국어 이름')]:
            xml = ET.parse(self.output/f'Languages/{folder}/DefInjected/ThingDef/Translations.xml').getroot()
            self.assertEqual(xml.findtext('Item.label'), expected)
            self.assertIsNone(xml.find('Item.description'))
        png = (self.output / 'About/Preview.png').read_bytes()
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertGreater(len(png), 1000)
        output_label = ET.parse(self.output/'About/About.xml').getroot().findtext('name')
        self.assertIn('多言語', output_label)

    def test_legacy_project_load_preserves_japanese_and_new_languages(self):
        self.project.entries[0].japanese = '旧版の訳'
        self.project.save(self.project_file)
        obj = json.loads(self.project_file.read_text())
        obj.pop('translations')
        obj.pop('language')
        self.project_file.write_text(json.dumps(obj))
        legacy = Project.load(self.project_file)
        self.assertEqual(legacy.entries[0].japanese, '旧版の訳')
        legacy.switch_language('Ukrainian')
        legacy.entries[0].japanese = 'Український переклад'
        legacy.switch_language('Japanese')
        self.assertEqual(legacy.entries[0].japanese, '旧版の訳')
        legacy.save(self.project_file)
        self.assertIn('Ukrainian', Project.load(self.project_file).translations)

    def test_rescan_retains_all_language_entries(self):
        self.project.entries[0].japanese = '日本語名'
        self.project.switch_language('German')
        self.project.entries[0].japanese = 'deutscher Name'
        (self.source / 'Defs/A.xml').write_text('<Defs><ThingDef><defName>Item</defName><label>new English name</label></ThingDef></Defs>')
        self.project.rescan(scan_mod(self.source))
        self.assertEqual(self.project.entries[0].japanese, 'deutscher Name')
        self.project.switch_language('Japanese')
        self.assertEqual(self.project.entries[0].japanese, '日本語名')
        self.assertTrue(self.project.entries[0].changed)

    def test_unsafe_language_name_rejected(self):
        for language in ('../Japanese', '日本語', 'French/Keyed', 'English ', ''):
            with self.assertRaises(ValueError): validate_language(language)

if __name__ == '__main__': unittest.main()

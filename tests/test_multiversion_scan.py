"""Declared versions are scanned sequentially with independent contexts."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.extraction import ScanCancelled


class DeclaredVersionScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Independent</name>'
                   '<packageId>sample.independent</packageId><supportedVersions>'
                   '<li>1.10</li><li>1.6</li><li>1.9</li><li>1.6</li>'
                   '</supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6>'
                   '<v1.9><li>1.9</li><li IfModActive="sample.extra">Extra</li></v1.9>'
                   '<v1.10><li>1.10</li></v1.10></loadFolders>')
        for version, text in [('1.3', 'undeclared'), ('1.6', 'old'), ('1.9', 'middle'), ('1.10', 'future')]:
            self.write(f'{version}/Defs/a.xml', '<Defs><ThingDef><defName>A</defName>'
                       f'<label>{text}</label></ThingDef></Defs>')
        self.write('Extra/Defs/b.xml', '<Defs><ThingDef><defName>B</defName>'
                   '<label>conditional</label></ThingDef></Defs>')

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_declared_only_numeric_order_and_context_isolation(self):
        from rimworld_translator.multiversion import scan_declared_versions
        before = {str(p): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        result = scan_declared_versions(self.source, contexts={'1.9': {'active_mods': ['sample.extra']}})
        self.assertEqual(result.declared_versions, ['1.6', '1.9', '1.10'])
        self.assertEqual(list(result.scans), ['1.6', '1.9', '1.10'])
        self.assertEqual(result.failures, {})
        self.assertEqual({e.key: e.english for e in result.scans['1.6'].entries}, {'A.label': 'old'})
        self.assertEqual({e.key: e.english for e in result.scans['1.9'].entries},
                         {'A.label': 'middle', 'B.label': 'conditional'})
        self.assertEqual({e.key: e.english for e in result.scans['1.10'].entries}, {'A.label': 'future'})
        self.assertIsNone(result.scans['1.10'].stats['active_mods'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.source.rglob('*') if p.is_file()})

    def test_scan_project_roundtrip_and_export_preserve_version_specific_text(self):
        import xml.etree.ElementTree as ET
        from rimworld_translator.core import Project, export_versions_test
        from rimworld_translator.multiversion import scan_declared_versions
        result = scan_declared_versions(self.source)
        project = Project.create_versions(self.source, result.scans)
        for version, text in [('1.6', '旧版'), ('1.9', '中間版'), ('1.10', '将来版')]:
            project.switch_version(version)
            project.set_translation('DefInjected:ThingDef:A.label', text)
        path = Path(self.temp.name) / 'workspace/project.json'
        project.save(path)
        loaded = Project.load(path)
        target = Path(self.temp.name) / 'output'
        export_versions_test(loaded, target)
        for version, text in [('1.6', '旧版'), ('1.9', '中間版'), ('1.10', '将来版')]:
            xml = target / version / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml'
            self.assertEqual(ET.parse(xml).getroot().findtext('A.label'), text)

    def test_one_unavailable_context_does_not_skip_other_declared_versions(self):
        from rimworld_translator.multiversion import scan_declared_versions
        result = scan_declared_versions(self.source, contexts={'1.9': {'context_sources': [self.source/'missing']}})
        self.assertEqual(list(result.scans), ['1.6', '1.10'])
        self.assertIn('1.9', result.failures)
        self.assertTrue(result.failures['1.9'])

    def test_corrupt_version_cache_is_isolated_and_preserved(self):
        from rimworld_translator.multiversion import scan_declared_versions
        cache = Path(self.temp.name) / 'bad.sqlite'
        cache.write_bytes(b'not a sqlite database')
        result = scan_declared_versions(self.source, contexts={'1.9': {'cache_path': cache}})
        self.assertEqual(list(result.scans), ['1.6', '1.10'])
        self.assertIn('1.9', result.failures)
        self.assertEqual(cache.read_bytes(), b'not a sqlite database')

    def test_cancel_propagates_instead_of_reporting_version_failure(self):
        from rimworld_translator.multiversion import scan_declared_versions
        with self.assertRaises(ScanCancelled):
            scan_declared_versions(self.source, cancel=lambda: True)

    def test_progress_identifies_each_version_without_breaking_file_scan(self):
        from rimworld_translator.multiversion import scan_declared_versions
        updates = []
        result = scan_declared_versions(self.source, progress=lambda version, done, total:
                                        updates.append((version, done, total)))
        self.assertEqual(result.failures, {})
        self.assertEqual({version for version, _, _ in updates}, {'1.6', '1.9', '1.10'})
        self.assertTrue(all(0 <= done <= total for _, done, total in updates))

    def test_missing_or_invalid_declarations_are_not_inferred_from_folders(self):
        from rimworld_translator.multiversion import scan_declared_versions
        for versions in ['', '<li>../1.6</li>']:
            self.write('About/About.xml', f'<ModMetaData><supportedVersions>{versions}</supportedVersions></ModMetaData>')
            with self.assertRaises(ValueError):
                scan_declared_versions(self.source)

    def test_undeclared_context_or_version_override_is_rejected(self):
        from rimworld_translator.multiversion import scan_declared_versions
        for contexts in [{'1.3': {}}, {'1.6': {'game_version': '1.10'}}]:
            with self.assertRaises(ValueError):
                scan_declared_versions(self.source, contexts=contexts)

    def test_cache_cannot_write_into_source_or_steam_content(self):
        from rimworld_translator.multiversion import scan_declared_versions
        for cache in [self.source/'cache.sqlite', Path(self.temp.name)/'steamapps/cache.sqlite']:
            with self.assertRaises(ValueError):
                scan_declared_versions(self.source, contexts={'1.6': {'cache_path': cache}})
            self.assertFalse(cache.exists())

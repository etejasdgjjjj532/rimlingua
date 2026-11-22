"""Keep scan evidence independent from version-local review and translation state."""
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_versions_test, scan_mod


GREETING = 'Keyed:Keyed:Greeting'


class VersionOutputRound18Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Scan ownership</name>'
                   '<packageId>test.scanownership</packageId><supportedVersions>'
                   '<li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6>'
                   '<v1.10><li>1.10</li></v1.10></loadFolders>')
        for version in ('1.6', '1.10'):
            self.write_keyed(version, f'hello {version}')
        self.scans = {version: scan_mod(self.source, game_version=version)
                      for version in ('1.6', '1.10')}

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def write_keyed(self, version, text):
        self.write(f'{version}/Languages/English/Keyed/messages.xml',
                   f'<LanguageData><Greeting>{text}</Greeting></LanguageData>')

    def test_rescan_preserves_scan_evidence_and_does_not_import_old_translation_into_new_project(self):
        project = Project.create_versions(self.source, self.scans)
        project.set_translation(GREETING, '変更前の訳')
        project.mark_reviewed(GREETING, approved=True)
        self.write_keyed('1.6', 'changed greeting')
        refreshed = scan_mod(self.source, game_version='1.6')
        before = copy.deepcopy(refreshed)
        project.rescan(refreshed)
        self.assertEqual(refreshed, before)
        fresh_project = Project.create_versions(self.source, {
            '1.6': refreshed, '1.10': self.scans['1.10']})
        self.assertEqual(fresh_project.get_translation(GREETING), '')
        self.assertFalse(fresh_project.entry_index()[GREETING].approved)
        self.assertEqual(project.get_translation(GREETING), '変更前の訳')
        self.assertTrue(project.entry_index()[GREETING].changed)
        self.assertEqual(project.entry_index()[GREETING].previous_english, 'hello 1.6')
        self.assertFalse(project.entry_index()[GREETING].approved)

    def test_reusing_version_scan_for_two_rescans_keeps_review_and_export_independent(self):
        first = Project.create_versions(self.source, self.scans)
        second = Project.create_versions(self.source, self.scans)
        first.rescan(self.scans['1.6'])
        second.rescan(self.scans['1.6'])
        first.set_translation(GREETING, '最初の独立訳')
        first.mark_reviewed(GREETING, approved=True)
        second.set_translation(GREETING, '別の独立訳')
        self.assertEqual(first.get_translation(GREETING), '最初の独立訳')
        self.assertTrue(first.entry_index()[GREETING].approved)
        for project, name, expected in ((first, 'first', '最初の独立訳'),
                                        (second, 'second', '別の独立訳')):
            saved = self.root / name / 'project.json'
            project.save(saved)
            restored = Project.load(saved)
            output = self.root / f'{name}-output'
            warnings = export_versions_test(restored, output)
            self.assertTrue(any('未検証' in warning for warning in warnings))
            self.assertEqual(ET.parse(output / '1.6/Languages/Japanese/Keyed/Keyed.xml')
                             .getroot().findtext('Greeting'), expected)
            restored.switch_version('1.10')
            self.assertEqual(restored.get_translation(GREETING), '')
            self.assertFalse((output / '1.10/Languages/Japanese/Keyed/Keyed.xml').exists())


if __name__ == '__main__':
    unittest.main()

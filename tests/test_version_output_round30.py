"""Reject cross-version refreshes before they can relabel another version's text."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_mod, scan_mod


class VersionOutputRound30Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Version refresh</name>'
                   '<packageId>test.versionrefresh</packageId><supportedVersions>'
                   '<li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6>'
                   '<v1.10><li>1.10</li></v1.10></loadFolders>')
        for version, greeting, name in (('1.6', 'Old greeting', 'Alpha'),
                                        ('1.10', 'New greeting', 'Beta')):
            self.write(f'{version}/Languages/English/Keyed/messages.xml',
                       f'<LanguageData><Greeting>{greeting}</Greeting></LanguageData>')
            self.write(f'{version}/Languages/English/Strings/WordLists/Names.txt', name + '\n')

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_legacy_refresh_rejects_another_version_before_mutating_saved_work(self):
        project = Project.create(self.source, scan_mod(self.source, game_version='1.6'))
        for identity, translation in (('Keyed:Keyed:Greeting', '旧版の挨拶'),
                                      ('Strings:WordLists/Names.txt:line_0', '甲')):
            project.set_translation(identity, translation)
            project.mark_reviewed(identity, approved=True)
        saved = self.root / 'workspace/project.json'
        project.save(saved)
        before = saved.read_bytes()
        target = self.root / 'output'
        export_mod(project, target)
        output_before = {str(path.relative_to(target)): path.read_bytes()
                         for path in target.rglob('*') if path.is_file()}

        with self.assertRaisesRegex(ValueError, '[Vv]ersion'):
            project.rescan(scan_mod(self.source, game_version='1.10'))

        project.save(saved)
        self.assertEqual(saved.read_bytes(), before)
        restored = Project.load(saved)
        self.assertEqual(restored.game_version, '1.6')
        expected = {'Keyed:Keyed:Greeting': ('Old greeting', '旧版の挨拶'),
                    'Strings:WordLists/Names.txt:line_0': ('Alpha', '甲')}
        for identity, (english, translated) in expected.items():
            entry = restored.entry_index()[identity]
            self.assertEqual((entry.english, entry.japanese), (english, translated))
            self.assertTrue(entry.approved)
        export_mod(restored, target)
        self.assertEqual({str(path.relative_to(target)): path.read_bytes()
                          for path in target.rglob('*') if path.is_file()}, output_before)
        self.assertEqual(ET.parse(target / 'About/About.xml').findtext('supportedVersions/li'), '1.6')

    def test_legacy_matching_version_refresh_keeps_source_change_review_gate(self):
        identity = 'Strings:WordLists/Names.txt:line_0'
        project = Project.create(self.source, scan_mod(self.source, game_version='1.6'))
        project.set_translation(identity, '甲')
        project.mark_reviewed(identity, approved=True)
        self.write('1.6/Languages/English/Strings/WordLists/Names.txt', 'Alpha revised\n')
        project.rescan(scan_mod(self.source, game_version='1.6'))
        entry = project.entry_index()[identity]
        self.assertEqual((entry.english, entry.previous_english, entry.japanese),
                         ('Alpha revised', 'Alpha', '甲'))
        self.assertFalse(entry.approved)
        self.assertTrue(entry.changed)
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            export_mod(project, self.root / 'needs-review')
        self.assertFalse((self.root / 'needs-review').exists())
        project.mark_reviewed(identity, approved=True)
        export_mod(project, self.root / 'reviewed')
        self.assertEqual((self.root / 'reviewed/Languages/Japanese/Strings/WordLists/Names.txt')
                         .read_text(encoding='utf-8'), '甲\n')


if __name__ == '__main__':
    unittest.main()

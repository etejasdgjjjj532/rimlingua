"""A removed resource's return must not silently restore release eligibility."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Project, export_mod, scan_mod


class VersionOutputRound29Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Returned resource</name>'
                   '<packageId>test.returnedresource</packageId><supportedVersions>'
                   '<li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
        self.write('LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6>'
                   '<v1.10><li>1.10</li></v1.10></loadFolders>')
        for version in ('1.6', '1.10'):
            self.write(f'{version}/Languages/English/Strings/WordLists/Names.txt', 'Alpha\n')

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def revive(self, project):
        relative = '1.6/Languages/English/Strings/WordLists/Names.txt'
        self.write(relative, '')
        project.rescan(scan_mod(self.source, game_version='1.6'))
        self.write(relative, 'Alpha\n')
        project.rescan(scan_mod(self.source, game_version='1.6'))

    def test_returned_strings_need_review_before_legacy_formal_output(self):
        identity = 'Strings:WordLists/Names.txt:line_0'
        project = Project.create(self.source, scan_mod(self.source, game_version='1.6'))
        project.set_translation(identity, '甲')
        project.mark_reviewed(identity, approved=True)
        target = self.root / 'formal'
        export_mod(project, target)
        before = {str(path.relative_to(target)): path.read_bytes()
                  for path in target.rglob('*') if path.is_file()}
        self.revive(project)
        saved = self.root / 'workspace/returned.json'
        project.save(saved)
        project = Project.load(saved)
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            export_mod(project, target)
        self.assertEqual({str(path.relative_to(target)): path.read_bytes()
                          for path in target.rglob('*') if path.is_file()}, before)
        project.mark_reviewed(identity, approved=True)
        export_mod(project, target)
        self.assertEqual((target / 'Languages/Japanese/Strings/WordLists/Names.txt')
                         .read_text(encoding='utf-8'), '甲\n')

    def test_returned_strings_require_review_in_both_languages_only_in_changed_version(self):
        identity = 'Strings:WordLists/Names.txt:line_0'
        project = Project.create_versions(self.source, {
            version: scan_mod(self.source, game_version=version)
            for version in ('1.6', '1.10')}, ['Japanese', 'French'])
        for version in ('1.6', '1.10'):
            project.switch_version(version)
            for language, text in (('Japanese', '甲'), ('French', 'Alpha traduit')):
                project.switch_language(language)
                project.set_translation(identity, text)
                project.mark_reviewed(identity, approved=True)
        project.switch_version('1.6')
        self.revive(project)
        saved = self.root / 'workspace/versioned.json'
        project.save(saved)
        restored = Project.load(saved)
        for language in ('French', 'Japanese'):
            restored.switch_language(language)
            entry = restored.entry_index()[identity]
            self.assertTrue(entry.changed, language)
            self.assertTrue(entry.review, language)
            self.assertFalse(entry.approved, language)
        restored.switch_version('1.10')
        for language in ('French', 'Japanese'):
            restored.switch_language(language)
            entry = restored.entry_index()[identity]
            self.assertFalse(entry.changed, language)
            self.assertFalse(entry.review, language)
            self.assertTrue(entry.approved, language)


if __name__ == '__main__':
    unittest.main()

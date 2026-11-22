"""Persist the dependency context belonging to the refreshed version's evidence."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Project, scan_mod


class VersionOutputRound31Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.write('About/About.xml', '<ModMetaData><name>Context refresh</name>'
                   '<packageId>test.contextrefresh</packageId><supportedVersions>'
                   '<li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
        self.write('Languages/English/Keyed/messages.xml',
                   '<LanguageData><Greeting>Hello</Greeting></LanguageData>')
        self.write('LoadFolders.xml', '<loadFolders><default><li>/</li>'
                   '<li IfModActive="test.optional">Optional</li></default></loadFolders>')
        self.write('Optional/Languages/English/Keyed/optional.xml',
                   '<LanguageData><OptionalGreeting>Optional hello</OptionalGreeting></LanguageData>')

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def save_restore(self, project):
        saved = self.root / 'workspace/project.json'
        project.save(saved)
        return Project.load(saved)

    def test_legacy_refresh_persists_new_context_without_borrowing_scan_ownership(self):
        project = Project.create(self.source, scan_mod(self.source, active_mods=[]))
        identity = 'Keyed:Keyed:Greeting'
        project.set_translation(identity, '挨拶')
        project.mark_reviewed(identity, approved=True)
        refreshed = scan_mod(self.source, active_mods=['test.optional'])
        project.rescan(refreshed)
        restored = self.save_restore(project)
        self.assertEqual(restored.active_mods, ['test.optional'])
        self.assertTrue(restored.active_mods_known)
        self.assertIn('Keyed:Keyed:OptionalGreeting', restored.entry_index())
        self.assertEqual(restored.get_translation(identity), '挨拶')
        self.assertTrue(restored.entry_index()[identity].approved)
        project.active_mods.append('test.projectonly')
        self.assertEqual(refreshed.stats['active_mods'], ['test.optional'])

    def test_legacy_refresh_keeps_unknown_context_distinct_from_known_empty(self):
        for active_mods, known in ((None, False), ([], True)):
            with self.subTest(active_mods=active_mods):
                project = Project.create(self.source, scan_mod(
                    self.source, active_mods=['test.optional']))
                project.rescan(scan_mod(self.source, active_mods=active_mods))
                restored = self.save_restore(project)
                self.assertEqual(restored.active_mods, [])
                self.assertEqual(restored.active_mods_known, known)

    def test_version_refresh_updates_only_its_saved_dependency_context(self):
        project = Project.create_versions(self.source, {
            version: scan_mod(self.source, game_version=version,
                              active_mods=['test.optional'] if version == '1.10' else [])
            for version in ('1.6', '1.10')})
        project.switch_version('1.10')
        identity = 'Keyed:Keyed:OptionalGreeting'
        project.set_translation(identity, '別版の挨拶')
        project.mark_reviewed(identity, approved=True)
        project.switch_version('1.6')
        project.rescan(scan_mod(self.source, game_version='1.6', active_mods=None))
        restored = self.save_restore(project)
        self.assertEqual(restored.active_mods, [])
        self.assertFalse(restored.active_mods_known)
        restored.switch_version('1.10')
        self.assertEqual(restored.active_mods, ['test.optional'])
        self.assertTrue(restored.active_mods_known)
        self.assertEqual(restored.get_translation(identity), '別版の挨拶')
        self.assertTrue(restored.entry_index()[identity].approved)


if __name__ == '__main__':
    unittest.main()

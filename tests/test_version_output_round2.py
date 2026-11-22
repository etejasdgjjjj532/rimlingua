"""Regression checks for version-local review state and XML output."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator import core


FIXTURE = Path(__file__).parent / 'fixtures' / 'round1-versions'
RIFLE = 'DefInjected:ThingDef:Rifle.label'


class VersionOutputRound2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        shutil.copytree(FIXTURE, self.source)
        self.scans = {version: core.scan_mod(self.source, game_version=version, active_mods=set())
                      for version in ('1.4', '1.9', '1.10')}

    def test_changed_source_invalidates_retained_deselected_language_approval(self):
        for versioned in (False, True):
            with self.subTest(versioned=versioned):
                if versioned:
                    project = core.Project.create_versions(self.source, self.scans, ['Japanese', 'French'])
                    project.switch_version('1.9')
                    project.switch_language('French')
                    project.set_translation(RIFLE, 'Fusil')
                    project.mark_reviewed(RIFLE, approved=True)
                    project.switch_version('1.4')
                else:
                    project = core.Project.create(self.source, copy.deepcopy(self.scans['1.4']), ['Japanese', 'French'])
                    project.switch_language('French')
                project.set_translation(RIFLE, 'Ancien fusil')
                project.mark_reviewed(RIFLE, approved=True)
                project.switch_language('Japanese')
                project.languages = ['Japanese']
                path = self.root / f'workspace/{versioned}.json'
                project.save(path)
                project = core.Project.load(path)
                changed = copy.deepcopy(self.scans['1.4'])
                next(entry for entry in changed.entries if entry.id == RIFLE).english = 'modified old rifle'
                project.rescan(changed)
                project.save(path)
                project = core.Project.load(path)
                project.switch_language('French')
                entry = project.entry_index()[RIFLE]
                self.assertEqual(entry.japanese, 'Ancien fusil')
                self.assertFalse(entry.approved)
                self.assertFalse(entry.reviewed)
                self.assertTrue(entry.changed)
                self.assertTrue(entry.review)
                self.assertEqual(entry.previous_english, 'old rifle')
                if versioned:
                    project.switch_version('1.9')
                    self.assertEqual(project.get_translation(RIFLE), 'Fusil')
                    self.assertTrue(project.entry_index()[RIFLE].approved)

    def test_reintroduced_source_invalidates_retained_deselected_language_approval(self):
        project = core.Project.create_versions(self.source, self.scans, ['Japanese', 'French'])
        project.switch_language('French')
        project.set_translation(RIFLE, 'Ancien fusil')
        project.mark_reviewed(RIFLE, approved=True)
        project.switch_language('Japanese')
        project.languages = ['Japanese']
        removed = copy.deepcopy(self.scans['1.4'])
        removed.entries = [entry for entry in removed.entries if entry.id != RIFLE]
        project.add_version_scan('1.4', removed)
        self.assertTrue(project.entry_index()[RIFLE].stale)
        project.add_version_scan('1.4', self.scans['1.4'])
        project.switch_language('French')
        entry = project.entry_index()[RIFLE]
        self.assertEqual(entry.japanese, 'Ancien fusil')
        self.assertFalse(entry.stale)
        self.assertFalse(entry.approved)
        self.assertTrue(entry.review)

    def test_repeated_rescan_save_and_export_preserves_version_local_xml_and_history(self):
        project = core.Project.create_versions(self.source, self.scans)
        texts = {'1.4': '旧式銃', '1.9': '銃', '1.10': '強化銃'}
        old_key = 'DefInjected:ThingDef:Old.label'
        for version, text in texts.items():
            project.switch_version(version)
            project.set_translation(RIFLE, text)
            project.mark_reviewed(RIFLE, approved=True)
        project.switch_version('1.4')
        project.set_translation(old_key, '廃止品')
        changed = copy.deepcopy(self.scans['1.4'])
        changed.entries = [entry for entry in changed.entries if entry.id != old_key]
        next(entry for entry in changed.entries if entry.id == RIFLE).english = 'modified old rifle'
        project.add_version_scan('1.4', changed)
        target = self.root / 'output'
        path = self.root / 'workspace/repeated.json'
        for _ in range(2):
            project.save(path)
            project = core.Project.load(path)
            project.add_version_scan('1.4', copy.deepcopy(changed))
            self.assertEqual(project.entry_index()[RIFLE].previous_english, 'old rifle')
            self.assertTrue(project.entry_index()[RIFLE].changed)
            self.assertFalse(project.entry_index()[RIFLE].approved)
            self.assertEqual(project.get_translation(old_key), '廃止品')
            self.assertTrue(project.entry_index()[old_key].stale)
            warnings = core.export_versions_test(project, target)
            self.assertTrue(any('Review needed' in warning for warning in warnings))
            for version, text in texts.items():
                xml = ET.parse(target / version / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml').getroot()
                self.assertEqual({entry.tag: entry.text for entry in xml}, {'Rifle.label': text})
            about = ET.parse(target / 'About/About.xml').getroot()
            self.assertEqual([entry.text for entry in about.findall('supportedVersions/li')], list(texts))
            self.assertEqual(about.findtext('modDependencies/li/packageId'), project.original_package_id)
            folders = ET.parse(target / 'LoadFolders.xml').getroot()
            self.assertEqual({entry.tag: entry.findtext('li') for entry in folders},
                             {f'v{version}': version for version in texts})
        project.switch_version('1.9')
        self.assertTrue(project.entry_index()[RIFLE].approved)
        self.assertNotIn(old_key, project.entry_index())


if __name__ == '__main__':
    unittest.main()

"""Explicit sharing must preserve version and language review boundaries."""
import copy
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Project, scan_mod


class VersionSharingRound33Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'About/About.xml').write_text('<ModMetaData><packageId>test.sharing</packageId>'
            '<supportedVersions><li>1.4</li><li>1.9</li><li>1.10</li></supportedVersions></ModMetaData>')
        keyed = self.source / 'Languages/English/Keyed/a.xml'
        keyed.parent.mkdir(parents=True)
        keyed.write_text('<LanguageData><Greeting>Hello {0}</Greeting></LanguageData>')
        self.project = Project.create_versions(self.source, {
            version: scan_mod(self.source, game_version=version) for version in ('1.4', '1.9', '1.10')},
            ['Japanese', 'French'])
        self.identity = 'Keyed:Keyed:Greeting'
        self.project.set_translation(self.identity, 'こんにちは {0}')
        self.project.mark_reviewed(self.identity, approved=True)

    def test_proposal_is_read_only_and_selected_version_does_not_inherit_approval(self):
        before = copy.deepcopy(self.project)
        self.assertEqual(self.project.translation_share_versions(self.identity), ['1.9', '1.10'])
        self.assertEqual(self.project, before)
        self.project.share_translation(self.identity, ['1.10'])
        self.assertEqual(self.project.game_version, '1.4')
        self.assertTrue(self.project.entry_index()[self.identity].approved)
        self.project.save(self.root / 'project/project.json')
        restored = Project.load(self.root / 'project/project.json')
        restored.switch_version('1.10')
        self.assertEqual(restored.get_translation(self.identity), 'こんにちは {0}')
        self.assertFalse(restored.entry_index()[self.identity].approved)
        self.assertFalse(restored.entry_index()[self.identity].reviewed)
        restored.switch_language('French')
        self.assertEqual(restored.get_translation(self.identity), '')
        restored.switch_version('1.9')
        restored.switch_language('Japanese')
        self.assertEqual(restored.get_translation(self.identity), '')

    def test_existing_translation_and_changed_source_are_never_overwritten(self):
        self.project.switch_version('1.9')
        self.project.set_translation(self.identity, '既存 {0}')
        self.project.mark_reviewed(self.identity, approved=True)
        self.project.switch_version('1.10')
        self.project.entry_index()[self.identity].english = 'New hello {0}'
        self.project.entry_index()[self.identity].changed = True
        self.project.switch_version('1.4')
        self.assertEqual(self.project.translation_share_versions(self.identity), [])
        before = copy.deepcopy(self.project)
        with self.assertRaises(ValueError):
            self.project.share_translation(self.identity, ['1.9'])
        self.assertEqual(self.project, before)
        self.project.switch_version('1.9')
        self.assertEqual(self.project.get_translation(self.identity), '既存 {0}')
        self.assertTrue(self.project.entry_index()[self.identity].approved)

    def test_invalid_selection_is_atomic_and_no_selection_changes_nothing(self):
        for selection in ([], ['1.10', '1.4'], ['1.9', '2.0'], ['1.9', '1.9']):
            with self.subTest(selection=selection):
                before = copy.deepcopy(self.project)
                with self.assertRaises(ValueError):
                    self.project.share_translation(self.identity, selection)
                self.assertEqual(self.project, before)

    def test_sharing_preserves_target_extraction_evidence_and_other_language(self):
        self.project.switch_version('1.10')
        self.project.switch_language('French')
        self.project.set_translation(self.identity, 'Bonjour {0}')
        self.project.mark_reviewed(self.identity, approved=True)
        self.project.switch_language('Japanese')
        self.project.switch_version('1.4')
        profile = self.project.version_profiles['1.10']
        profile['coverage']['source_verified'] = True
        profile['selected_folders'] = ['1.10']
        before_stats = copy.deepcopy(profile['stats'])
        self.project.share_translation(self.identity, ['1.10'])
        profile = self.project.version_profiles['1.10']
        self.assertTrue(profile['coverage']['source_verified'])
        self.assertEqual(profile['selected_folders'], ['1.10'])
        self.assertEqual(profile['stats'], before_stats)
        self.project.switch_version('1.10')
        self.project.switch_language('French')
        self.assertEqual(self.project.get_translation(self.identity), 'Bonjour {0}')
        self.assertTrue(self.project.entry_index()[self.identity].approved)

    def test_unsafe_source_or_target_is_not_a_share_candidate(self):
        source = self.project.entry_index()[self.identity]
        for flag in ('blocked', 'stale', 'excluded', 'changed', 'review'):
            with self.subTest(source_flag=flag):
                setattr(source, flag, True)
                self.assertEqual(self.project.translation_share_versions(self.identity), [])
                setattr(source, flag, False)
        self.project.set_translation(self.identity, 'トークン欠落')
        self.assertEqual(self.project.translation_share_versions(self.identity), [])
        self.project.set_translation(self.identity, 'こんにちは {0}')
        self.project.switch_version('1.9')
        self.project.entry_index()[self.identity].blocked = True
        self.project.switch_version('1.4')
        self.assertEqual(self.project.translation_share_versions(self.identity), ['1.10'])

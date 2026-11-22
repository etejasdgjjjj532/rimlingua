"""Chapter 6: carrying translations across versions, per-version diff, and explicit version availability."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import multiversion
from rimworld_translator.core import Entry, Project, Scan


def thing(key, english):
    return Entry(f'DefInjected:ThingDef:{key}', 'DefInjected', 'ThingDef', key, english, 'Things.xml')


def build(per_version):
    versions = sorted(per_version)
    scans = {v: Scan(entries=[thing(k, e) for k, e in per_version[v]], name='Fixture', package_id='test.versions',
                     versions=versions, stats={'active_version': v}) for v in versions}
    folder = tempfile.TemporaryDirectory()
    return Project.create_versions(Path(folder.name), scans), folder


class VersionToolsTests(unittest.TestCase):
    def setUp(self):
        self.project, folder = build({
            '1.4': [('Gun.label', 'gun'), ('Old.label', 'old'), ('Same.label', 'same')],
            '1.5': [('Gun.label', 'gun'), ('Same.label', 'same'), ('New.label', 'new')],
            '1.6': [('Gun.label', 'gun (new)'), ('Same.label', 'same'), ('New.label', 'new')],
        })
        self.addCleanup(folder.cleanup)
        self.project.switch_version('1.4')
        self.project.set_translation('DefInjected:ThingDef:Gun.label', '銃')
        self.project.set_translation('DefInjected:ThingDef:Old.label', '古い')
        self.project.set_translation('DefInjected:ThingDef:Same.label', '同じ')

    def test_preview_copies_identical_english_only_by_default(self):
        preview = multiversion.preview_carry(self.project, '1.4', '1.5')
        self.assertEqual({item.entry_id: item.after for item in preview.items},
                         {'DefInjected:ThingDef:Gun.label': '銃', 'DefInjected:ThingDef:Same.label': '同じ'})
        self.assertEqual(preview.skipped['missing'], 1)

    def test_changed_english_is_skipped_unless_requested_and_then_marked_for_review(self):
        plain = multiversion.preview_carry(self.project, '1.4', '1.6')
        self.assertEqual([item.entry_id for item in plain.items], ['DefInjected:ThingDef:Same.label'])
        self.assertEqual(plain.skipped['english_differs'], 1)
        loose = multiversion.preview_carry(self.project, '1.4', '1.6', include_different_english=True)
        gun = next(item for item in loose.items if item.entry_id.endswith('Gun.label'))
        self.assertTrue(gun.review)

    def test_apply_writes_the_target_version_and_leaves_the_source_alone(self):
        preview = multiversion.preview_carry(self.project, '1.4', '1.5')
        self.assertEqual(multiversion.apply_carry(self.project, preview), 2)
        self.project.switch_version('1.5')
        self.assertEqual(self.project.get_translation('DefInjected:ThingDef:Gun.label'), '銃')
        self.assertFalse(self.project.entry_index()['DefInjected:ThingDef:Gun.label'].reviewed)
        self.project.switch_version('1.4')
        self.assertEqual(self.project.get_translation('DefInjected:ThingDef:Old.label'), '古い')

    def test_apply_to_the_current_version(self):
        self.project.switch_version('1.5')
        preview = multiversion.preview_carry(self.project, '1.4', '1.5')
        multiversion.apply_carry(self.project, preview)
        self.assertEqual(self.project.get_translation('DefInjected:ThingDef:Gun.label'), '銃')

    def test_existing_translations_are_kept_unless_overwrite(self):
        self.project.switch_version('1.5')
        self.project.set_translation('DefInjected:ThingDef:Gun.label', '別')
        preview = multiversion.preview_carry(self.project, '1.4', '1.5')
        self.assertNotIn('DefInjected:ThingDef:Gun.label', [item.entry_id for item in preview.items])
        self.assertEqual(preview.skipped['has_translation'], 1)
        forced = multiversion.preview_carry(self.project, '1.4', '1.5', overwrite=True)
        self.assertIn('DefInjected:ThingDef:Gun.label', [item.entry_id for item in forced.items])

    def test_same_version_is_refused(self):
        with self.assertRaises(ValueError):
            multiversion.preview_carry(self.project, '1.4', '1.4')
        with self.assertRaises(ValueError):
            multiversion.preview_carry(self.project, '1.4', '1.3')

    def test_version_diff(self):
        diff = multiversion.version_diff(self.project, '1.4', '1.6')
        self.assertEqual(diff.only_a, ['DefInjected:ThingDef:Old.label'])
        self.assertEqual(diff.only_b, ['DefInjected:ThingDef:New.label'])
        self.assertEqual([c.entry_id for c in diff.english_changed], ['DefInjected:ThingDef:Gun.label'])
        self.assertEqual(diff.english_changed[0].english_a, 'gun')
        self.assertEqual(diff.same, 0)
        self.assertEqual([c.entry_id for c in diff.translation_differs], ['DefInjected:ThingDef:Same.label'])
        self.assertIn('1.4', diff.summary())


class VersionStateTests(unittest.TestCase):
    def test_states_explain_each_version(self):
        project, folder = build({'1.0': [('A.label', 'a')], '1.5': [('A.label', 'a')]})
        self.addCleanup(folder.cleanup)
        project.versions = ['1.0', '1.5', '1.6']
        states = {s.version: s for s in multiversion.version_states(project, available_game_versions=['1.5'])}
        self.assertEqual(states['1.5'].status, 'ready')
        self.assertEqual(states['1.0'].status, 'unverified_load_rules')
        self.assertFalse(states['1.0'].exportable)
        self.assertIn('1.0', states['1.0'].message)
        self.assertEqual(states['1.6'].status, 'unscanned')

    def test_scanned_version_without_a_library_game_is_stated(self):
        project, folder = build({'1.4': [('A.label', 'a')], '1.5': [('A.label', 'a')]})
        self.addCleanup(folder.cleanup)
        states = {s.version: s for s in multiversion.version_states(project, available_game_versions=['1.5'])}
        self.assertEqual(states['1.4'].status, 'no_library_game')
        self.assertTrue(states['1.4'].exportable)
        unknown = {s.version: s for s in multiversion.version_states(project)}
        self.assertEqual(unknown['1.4'].status, 'ready')

    def test_library_versions_reads_the_library_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / '1.5/Game/Data/Core').mkdir(parents=True)
            (Path(folder) / '1.3/Empty').mkdir(parents=True)
            self.assertEqual(multiversion.library_versions(Path(folder)), {'1.5'})


if __name__ == '__main__':
    unittest.main()

"""Version profiles must never share translations or approval implicitly."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator import core


FIXTURE = Path(__file__).parent / 'fixtures' / 'round1-versions'
RIFLE = 'DefInjected:ThingDef:Rifle.label'


class VersionProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        shutil.copytree(FIXTURE, self.source)
        self.scans = {v: core.scan_mod(self.source, game_version=v, active_mods=set())
                      for v in ('1.10', '1.4', '1.9')}

    def project(self):
        return core.Project.create_versions(self.source, self.scans, ['Japanese', 'French'])

    def test_declared_versions_sorted_numerically_and_context_kept(self):
        project = self.project()
        self.assertEqual(project.versions, ['1.4', '1.9', '1.10'])
        self.assertEqual(project.game_version, '1.4')
        for version in project.versions:
            profile = project.version_profiles[version]
            self.assertEqual(profile['selected_folders'], [version])
            self.assertTrue(profile['coverage']['extracted'])
            self.assertFalse(profile['coverage']['source_verified'])
            self.assertFalse(profile['coverage']['game_tested'])
        with self.assertRaises(ValueError):
            project.add_version_scan('1.3', self.scans['1.4'])
        with self.assertRaises(ValueError):
            project.add_version_scan('1.9', self.scans['1.4'])

    def test_two_languages_and_versions_keep_translation_approval_independent(self):
        project = self.project()
        project.set_translation(RIFLE, '旧式銃')
        project.mark_reviewed(RIFLE, approved=True)
        project.switch_language('French')
        project.set_translation(RIFLE, 'Ancien fusil')
        project.switch_version('1.10')
        self.assertEqual(project.get_translation(RIFLE), '')
        self.assertFalse(project.entry_index()[RIFLE].approved)
        project.set_translation(RIFLE, 'Fusil renforcé')
        project.mark_reviewed(RIFLE, approved=True)
        project.switch_language('Japanese')
        self.assertEqual(project.get_translation(RIFLE), '')
        project.set_translation(RIFLE, '強化銃')
        path = self.root / 'workspace/project.json'
        project.save(path)
        loaded = core.Project.load(path)
        self.assertEqual(loaded.get_translation(RIFLE), '強化銃')
        loaded.switch_version('1.4')
        self.assertEqual(loaded.get_translation(RIFLE), '旧式銃')
        self.assertTrue(loaded.entry_index()[RIFLE].approved)
        loaded.switch_language('French')
        self.assertEqual(loaded.get_translation(RIFLE), 'Ancien fusil')
        self.assertFalse(loaded.entry_index()[RIFLE].approved)
        loaded.switch_version('1.10')
        self.assertEqual(loaded.get_translation(RIFLE), 'Fusil renforcé')
        self.assertTrue(loaded.entry_index()[RIFLE].approved)

    def test_rescan_changed_and_removed_history_is_local_to_version(self):
        project = self.project()
        project.set_translation(RIFLE, '旧式銃')
        project.mark_reviewed(RIFLE, approved=True)
        old_id = 'DefInjected:ThingDef:Old.label'
        project.set_translation(old_id, '旧版専用')
        changed = copy.deepcopy(self.scans['1.4'])
        changed.entries = [e for e in changed.entries if e.id != old_id]
        next(e for e in changed.entries if e.id == RIFLE).english = 'changed old rifle'
        project.add_version_scan('1.4', changed)
        self.assertEqual(project.get_translation(RIFLE), '旧式銃')
        self.assertTrue(project.entry_index()[RIFLE].changed)
        self.assertFalse(project.entry_index()[RIFLE].approved)
        self.assertTrue(project.entry_index()[old_id].stale)
        project.switch_version('1.9')
        self.assertNotIn(old_id, project.entry_index())
        self.assertFalse(project.entry_index()[RIFLE].changed)

    def test_test_export_uses_independent_complete_version_trees(self):
        project = self.project()
        for version, text in [('1.4', '旧式銃'), ('1.9', '銃'), ('1.10', '強化銃')]:
            project.switch_version(version)
            project.set_translation(RIFLE, text)
            only_key = {'1.4': 'Old', '1.9': 'Middle', '1.10': 'New'}[version]
            project.set_translation(f'DefInjected:ThingDef:{only_key}.label', '専用')
        target = self.root / 'output'
        warnings = core.export_versions_test(project, target)
        self.assertTrue(any('未検証' in warning for warning in warnings))
        about = ET.parse(target / 'About/About.xml').getroot()
        self.assertEqual([e.text for e in about.findall('supportedVersions/li')], ['1.4', '1.9', '1.10'])
        folders = ET.parse(target / 'LoadFolders.xml').getroot()
        self.assertEqual([(e.tag, e.findtext('li')) for e in folders], [('v1.4', '1.4'), ('v1.9', '1.9'), ('v1.10', '1.10')])
        for version, text in [('1.4', '旧式銃'), ('1.9', '銃'), ('1.10', '強化銃')]:
            tree = ET.parse(target / version / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml').getroot()
            self.assertEqual(tree.findtext('Rifle.label'), text)
            self.assertEqual(len(tree), 2)
        self.assertFalse((target / 'Languages').exists())
        with self.assertRaises(ValueError):
            core.export_mod(project, target)

    def test_incomplete_scan_test_export_holds_unscanned_versions(self):
        project = core.Project.create_versions(self.source, {'1.4': self.scans['1.4']})
        warnings = core.export_versions_test(project, self.root / 'output')
        self.assertTrue(any('1.9' in warning and '保留' in warning for warning in warnings))
        self.assertFalse((self.root / 'output/1.9').exists())
        self.assertFalse((self.root / 'output/1.10').exists())

    def test_legacy_schema_one_roundtrip_preserves_unscanned_versions_metadata(self):
        project = core.Project.create(self.source, self.scans['1.4'])
        project.set_translation(RIFLE, '旧式銃')
        project.mark_reviewed(RIFLE, approved=True)
        path = self.root / 'workspace/legacy.json'
        project.save(path)
        raw = json.loads(path.read_text())
        raw.pop('version_profiles', None)
        raw['schema'] = 1
        path.write_text(json.dumps(raw))
        loaded = core.Project.load(path)
        self.assertEqual(loaded.versions, ['1.10', '1.4', '1.9'])
        self.assertEqual(loaded.get_translation(RIFLE), '旧式銃')
        self.assertTrue(loaded.entry_index()[RIFLE].approved)
        loaded.save(path)
        self.assertEqual(core.Project.load(path).get_translation(RIFLE), '旧式銃')

    def test_loaded_profile_entries_and_versions_are_validated(self):
        project = self.project()
        path = self.root / 'workspace/project.json'
        project.save(path)
        original = json.loads(path.read_text())
        for mutation in ('version', 'entry', 'translation'):
            data = copy.deepcopy(original)
            if mutation == 'version':
                data['version_profiles']['../../escape'] = data['version_profiles'].pop('1.9')
            elif mutation == 'entry':
                data['version_profiles']['1.9']['entries'][0]['key'] = '../unsafe'
            else:
                data['version_profiles']['1.9']['translations'] = {'Japanese': {'bad': 42}}
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError, msg=mutation):
                core.Project.load(path)

    def test_test_export_omits_unsafe_translation_with_warning_and_keeps_unowned_files(self):
        project = self.project()
        project.switch_version('1.4')
        project.set_translation(RIFLE, '旧式銃')
        target = self.root / 'output'
        core.export_versions_test(project, target)
        custom = target / 'notes.txt'
        custom.write_text('keep')
        before = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()}
        project.switch_version('1.10')
        greeting = 'Keyed:Keyed:Greeting'
        self.assertIn(greeting, project.entry_index())
        project.entry_index()[greeting].english = 'Hello {0}'
        project.set_translation(greeting, '危険な訳')
        warnings = core.export_versions_test(project, target)
        self.assertTrue(any('Greeting' in warning for warning in warnings))
        self.assertFalse((target / '1.10/Languages/Japanese/Keyed/Keyed.xml').exists())
        self.assertEqual(custom.read_text(), 'keep')
        # A safe existing translation remains in the partial test output.
        self.assertEqual(ET.parse(target / '1.4/Languages/Japanese/DefInjected/ThingDef/Translations.xml').getroot().findtext('Rifle.label'), '旧式銃')

    def test_rescan_cannot_silently_replace_current_version_with_another(self):
        project = self.project()
        project.set_translation(RIFLE, '旧式銃')
        with self.assertRaises(ValueError):
            project.rescan(self.scans['1.10'])
        self.assertEqual(project.game_version, '1.4')
        self.assertEqual(project.get_translation(RIFLE), '旧式銃')

    def test_test_export_cleanup_and_symlink_safety(self):
        project = self.project()
        project.set_translation(RIFLE, '旧式銃')
        target = self.root / 'output'
        core.export_versions_test(project, target)
        output = target / '1.4/Languages/Japanese/DefInjected/ThingDef/Translations.xml'
        project.set_translation(RIFLE, '')
        core.export_versions_test(project, target)
        self.assertFalse(output.exists())
        project.set_translation(RIFLE, '再出力')
        external = self.root / 'external'
        external.mkdir()
        output.parent.rmdir()
        output.parent.symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            core.export_versions_test(project, target)
        self.assertEqual(list(external.iterdir()), [])

    def test_legacy_project_can_add_another_version_without_losing_current_text(self):
        project = core.Project.create(self.source, self.scans['1.4'])
        project.set_translation(RIFLE, '旧式銃')
        project.add_version_scan('1.9', self.scans['1.9'])
        self.assertEqual(project.get_translation(RIFLE), '')
        project.switch_version('1.4')
        self.assertEqual(project.get_translation(RIFLE), '旧式銃')
        path = self.root / 'workspace/upgraded.json'
        project.save(path)
        self.assertEqual(core.Project.load(path).get_translation(RIFLE), '旧式銃')

    def test_legacy_one_zero_export_waits_for_verified_load_rule(self):
        old_scan = copy.deepcopy(self.scans['1.4'])
        old_scan.versions = ['1.0']
        old_scan.stats['active_version'] = '1.0'
        project = core.Project.create_versions(self.source, {'1.0': old_scan})
        with self.assertRaises(ValueError):
            core.export_versions_test(project, self.root / 'output')
        self.assertFalse((self.root / 'output').exists())

    def test_deselecting_language_preserves_inactive_profile_translations(self):
        project = self.project()
        project.switch_language('French')
        project.set_translation(RIFLE, 'Ancien fusil')
        project.mark_reviewed(RIFLE, approved=True)
        project.switch_version('1.9')
        project.switch_language('Japanese')
        project.languages = ['Japanese']
        path = self.root / 'workspace/reselected.json'
        project.save(path)
        loaded = core.Project.load(path)
        loaded.switch_version('1.4')
        self.assertEqual(loaded.language, 'Japanese')
        self.assertEqual(loaded.get_translation(RIFLE), '')
        loaded.switch_language('French')
        self.assertEqual(loaded.get_translation(RIFLE), 'Ancien fusil')
        self.assertTrue(loaded.entry_index()[RIFLE].approved)

    def test_partial_multi_version_project_cannot_bypass_export_policy_via_legacy_api(self):
        project = core.Project.create_versions(self.source, {'1.4': self.scans['1.4']})
        project.set_translation(RIFLE, '旧式銃')
        target = self.root / 'output'
        with self.assertRaises(ValueError):
            core.export_mod(project, target)
        self.assertFalse(target.exists())

"""Entries that change key keep their translation work (handle-keyed list items)."""
import json
from pathlib import Path
import tempfile
import unittest
from rimworld_translator.core import Entry, Project, Scan

OLD = 'DefInjected:HediffDef:Drug.stages.0.label'


def entry(key, english='initial', legacy=()):
    item = Entry(f'DefInjected:HediffDef:{key}', 'DefInjected', 'HediffDef', key, english, 'Defs/drug.xml')
    item.legacy_keys = list(legacy)
    return item


class LegacyKeyFieldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.path = self.root / 'work/project.json'

    def project(self, item):
        return Project.create(self.source, Scan(entries=[item]), ['Japanese'])

    def test_entry_default_has_no_legacy_keys(self):
        self.assertEqual(Entry('a', 'Keyed', 'Keyed', 'a', 'x', 'f.xml').legacy_keys, [])

    def test_project_saved_with_legacy_keys_loads_equal(self):
        project = self.project(entry('Drug.stages.Initial.label', legacy=[OLD]))
        project.save(self.path)
        self.assertEqual(Project.load(self.path).entries[0].legacy_keys, [OLD])

    def test_project_file_without_legacy_keys_still_loads(self):
        self.project(entry('Drug.stages.0.label')).save(self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        for item in data['entries']:
            del item['legacy_keys']
        self.path.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(Project.load(self.path).entries[0].legacy_keys, [])

    def test_non_string_legacy_key_is_rejected(self):
        self.project(entry('Drug.stages.0.label')).save(self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['entries'][0]['legacy_keys'] = [1]
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Invalid entry field types'):
            Project.load(self.path)


NEW = 'DefInjected:HediffDef:Drug.stages.Initial.label'


def scan_of(*entries, version=None, versions=None):
    scan = Scan(entries=list(entries), package_id='test.handle.keys')
    if version:
        scan.versions, scan.stats = list(versions), {'active_version': version}
    return scan


class RescanAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()

    def translated(self, *entries):
        project = Project.create(self.source, scan_of(*entries), ['Japanese', 'French'])
        return project

    def moved(self, english='initial'):
        return entry('Drug.stages.Initial.label', english, legacy=[OLD])

    def test_rescan_moves_translation_state_to_handle_key(self):
        project = self.translated(entry('Drug.stages.0.label'))
        project.set_translation(OLD, '初期')
        project.mark_reviewed(OLD, approved=True)
        migrated = project.rescan(scan_of(self.moved()))
        self.assertEqual(migrated, 1)
        self.assertEqual([e.id for e in project.entries], [NEW])
        self.assertFalse(project.entries[0].stale)
        self.assertEqual(project.get_translation(NEW, 'Japanese'), '初期')
        self.assertTrue(project.entries[0].approved)
        self.assertNotIn(OLD, project.translations['Japanese'])

    def test_rescan_moves_other_languages_and_states(self):
        project = self.translated(entry('Drug.stages.0.label'))
        project.switch_language('French')
        project.set_translation(OLD, 'initial')
        project.mark_reviewed(OLD, approved=True)
        project.switch_language('Japanese')
        project.rescan(scan_of(self.moved()))
        self.assertEqual(project.get_translation(NEW, 'French'), 'initial')
        self.assertEqual(project.translations['French'], {NEW: 'initial'})
        self.assertIn(NEW, project.language_states['French'])
        self.assertNotIn(OLD, project.language_states['French'])
        self.assertTrue(project.language_states['French'][NEW]['approved'])

    def test_rescan_with_changed_english_marks_changed_and_drops_approval(self):
        project = self.translated(entry('Drug.stages.0.label'))
        project.set_translation(OLD, '初期')
        project.mark_reviewed(OLD, approved=True)
        project.rescan(scan_of(self.moved('first stage')))
        adopted = project.entries[0]
        self.assertEqual(adopted.japanese, '初期')
        self.assertTrue(adopted.changed)
        self.assertFalse(adopted.approved)

    def test_ambiguous_legacy_claim_adopts_nothing(self):
        project = self.translated(entry('Drug.stages.0.label'))
        project.set_translation(OLD, '初期')
        other = entry('Drug.stages.Worse.label', 'worse', legacy=[OLD])
        migrated = project.rescan(scan_of(self.moved(), other))
        self.assertEqual(migrated, 0)
        by_id = {e.id: e for e in project.entries}
        self.assertTrue(by_id[OLD].stale)
        self.assertEqual(by_id[OLD].japanese, '初期')
        self.assertEqual(by_id[NEW].japanese, '')
        self.assertEqual(by_id[other.id].japanese, '')
        self.assertTrue(any(OLD in warning for warning in project.warnings))

    def test_existing_new_key_is_not_overwritten(self):
        project = self.translated(entry('Drug.stages.0.label'), entry('Drug.stages.Initial.label'))
        project.set_translation(OLD, 'old text')
        project.set_translation(NEW, 'typed by hand')
        migrated = project.rescan(scan_of(self.moved()))
        self.assertEqual(migrated, 0)
        by_id = {e.id: e for e in project.entries}
        self.assertEqual(by_id[NEW].japanese, 'typed by hand')
        self.assertTrue(by_id[OLD].stale)
        self.assertEqual(by_id[OLD].japanese, 'old text')

    def test_second_rescan_migrates_nothing(self):
        project = self.translated(entry('Drug.stages.0.label'))
        project.set_translation(OLD, '初期')
        project.rescan(scan_of(self.moved()))
        self.assertEqual(project.rescan(scan_of(self.moved())), 0)
        self.assertEqual([e.id for e in project.entries], [NEW])
        self.assertEqual(project.entries[0].japanese, '初期')

    def test_version_profile_project_migrates_only_rescanned_version(self):
        versions = ['1.4', '1.6']
        old_scans = {v: scan_of(entry('Drug.stages.0.label'), version=v, versions=versions) for v in versions}
        project = Project.create_versions(self.source, old_scans, ['Japanese'])
        project.set_translation(OLD, '1.4の訳')
        project.switch_version('1.6')
        project.set_translation(OLD, '1.6の訳')
        migrated = project.rescan(scan_of(self.moved(), version='1.6', versions=versions))
        self.assertEqual(migrated, 1)
        self.assertEqual(project.get_translation(NEW), '1.6の訳')
        project.switch_version('1.4')
        self.assertEqual([e.id for e in project.entries], [OLD])
        self.assertEqual(project.get_translation(OLD), '1.4の訳')
        project.switch_version('1.6')
        self.assertEqual([e.id for e in project.entries], [NEW])

    def test_migrated_project_roundtrips(self):
        project = self.translated(entry('Drug.stages.0.label'))
        project.set_translation(OLD, '初期')
        project.rescan(scan_of(self.moved()))
        path = self.root / 'work/project.json'
        project.save(path)
        loaded = Project.load(path)
        self.assertEqual([e.id for e in loaded.entries], [NEW])
        self.assertEqual(loaded.get_translation(NEW, 'Japanese'), '初期')


if __name__ == '__main__':
    unittest.main()

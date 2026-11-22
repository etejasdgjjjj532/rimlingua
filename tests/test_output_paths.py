"""One place decides where a project's translation MOD goes, and which places are never written."""
import json
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.output_paths import (OutputLocationError, check_output_folder, formal_output,
                                              protected_folders, shown_output, trial_output)
from rimworld_translator.platforms import GameInstallation


class OutputPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'About/About.xml').write_text('<ModMetaData><packageId>a.b</packageId></ModMetaData>')
        scan = Scan([Entry('Keyed:Keyed:A', 'Keyed', 'Keyed', 'A', 'a', 'Keyed/A.xml')], [], 'Name', 'a.b', ['1.6'])
        self.project = Project.create(self.source, scan)
        self.project_path = self.root / 'work/project.json'
        self.game_root = self.root / 'game'
        (self.game_root / 'Data/Core').mkdir(parents=True)
        (self.game_root / 'Mods').mkdir()
        self.workshop = self.root / 'workshop'
        self.workshop.mkdir()
        self.game = GameInstallation(self.game_root, self.game_root / 'Mods', self.workshop, '1.6', None)
        self.external = self.root / 'external'
        self.external.mkdir()
        self.settings = {'workshop_folder': '', 'mods_folder': '', 'external_mod_folders': [str(self.external)]}

    def protected(self):
        return protected_folders(self.settings, [self.game], self.source)

    def test_default_single_version_output_is_mod(self):
        self.assertEqual(formal_output(self.project_path, self.project), self.root / 'work/mod')
        self.assertEqual(shown_output(self.project_path, self.project), self.root / 'work/mod')

    def test_default_multi_version_shows_trial_output(self):
        self.project.version_profiles = {'1.6': {}}
        self.assertEqual(formal_output(self.project_path, self.project), self.root / 'work/mod')
        self.assertEqual(trial_output(self.project_path, self.project), self.root / 'work/mod-test')
        self.assertEqual(shown_output(self.project_path, self.project), self.root / 'work/mod-test')

    def test_user_folder_is_used_for_formal_output_and_shown(self):
        chosen = self.root / 'out/MyTranslation'
        self.project.output_folder = str(chosen)
        self.assertEqual(formal_output(self.project_path, self.project), chosen)
        self.assertEqual(shown_output(self.project_path, self.project), chosen)
        self.project.version_profiles = {'1.6': {}}
        self.assertEqual(shown_output(self.project_path, self.project), chosen)
        # Trial output is a test artifact and stays with the project.
        self.assertEqual(trial_output(self.project_path, self.project), self.root / 'work/mod-test')

    def refused(self, path, reason):
        with self.assertRaises(OutputLocationError) as caught:
            check_output_folder(path, project_path=self.project_path, protected=self.protected())
        self.assertEqual(caught.exception.reason, reason)
        self.assertTrue(caught.exception.japanese)
        self.assertTrue(str(caught.exception))

    def test_overlapping_source_is_refused(self):
        self.refused(self.source / 'Translation', 'source')
        self.refused(self.source, 'source')
        self.refused(self.root, 'source')

    def test_workshop_and_game_data_are_refused(self):
        self.refused(self.workshop / '123', 'workshop')
        self.refused(self.game_root / 'Data/Mine', 'data')

    def test_user_added_folders_are_refused(self):
        self.refused(self.external / 'Mine', 'external')
        set_workshop = self.root / 'my workshop'
        self.settings['workshop_folder'] = str(set_workshop)
        self.refused(set_workshop / 'x', 'workshop')

    def test_mods_folder_allows_only_a_direct_child(self):
        allowed = check_output_folder(self.game_root / 'Mods/MyTranslation', project_path=self.project_path,
                                      protected=self.protected())
        self.assertEqual(allowed, (self.game_root / 'Mods/MyTranslation').resolve())
        self.refused(self.game_root / 'Mods', 'mods')
        self.refused(self.game_root / 'Mods/Other/Deep', 'mods')

    def test_project_folder_itself_is_refused(self):
        self.refused(self.root / 'work', 'project')

    def test_relative_path_is_refused(self):
        self.refused(Path('relative/out'), 'relative')

    def test_resolve_output_checks_the_project_folder(self):
        from rimworld_translator.output_paths import resolve_output
        self.assertEqual(resolve_output(self.project_path, self.project, self.settings, [self.game]),
                         (self.root / 'work/mod').resolve())
        self.assertEqual(resolve_output(self.project_path, self.project, self.settings, [self.game], trial=True),
                         (self.root / 'work/mod-test').resolve())
        self.project.output_folder = str(self.workshop / 'mine')
        with self.assertRaises(OutputLocationError):
            resolve_output(self.project_path, self.project, self.settings, [self.game])

    def test_ordinary_folder_is_accepted(self):
        target = self.root / 'exports/Mine'
        self.assertEqual(check_output_folder(target, project_path=self.project_path, protected=self.protected()),
                         target.resolve())


class ProjectOutputFieldTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source'
        source.mkdir()
        scan = Scan([Entry('Keyed:Keyed:A', 'Keyed', 'Keyed', 'A', 'a', 'Keyed/A.xml')], [], 'Name', 'a.b', ['1.6'])
        self.project = Project.create(source, scan)
        self.path = self.root / 'work/project.json'

    def test_output_folder_is_saved_and_loaded(self):
        self.project.output_folder = str(self.root / 'out')
        self.project.save(self.path)
        self.assertEqual(Project.load(self.path).output_folder, str(self.root / 'out'))

    def test_old_project_without_the_field_loads_with_default(self):
        self.project.save(self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data.pop('output_folder')
        self.path.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(Project.load(self.path).output_folder, '')

    def test_invalid_output_folder_is_rejected(self):
        self.project.save(self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        for bad in (5, 'relative/out'):
            data['output_folder'] = bad
            self.path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError):
                Project.load(self.path)


if __name__ == '__main__':
    unittest.main()

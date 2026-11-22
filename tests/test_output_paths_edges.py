"""Edge cases of output folder checks: blank, relative, trailing, '..', symlinks and prefix-only overlaps.

Everything runs under a temporary directory; no real game, Workshop or Steam folder is touched.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.output_paths import (OutputLocationError, check_output_folder, formal_output,
                                              protected_folders, resolve_output, shown_output, trial_output)
from rimworld_translator.platforms import GameInstallation


class OutputPathEdgeTests(unittest.TestCase):
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

    def check(self, path):
        return check_output_folder(path, project_path=self.project_path, protected=self.protected())

    def refused(self, path, reason):
        with self.assertRaises(OutputLocationError) as caught:
            self.check(path)
        self.assertEqual(caught.exception.reason, reason)

    # Blank and whitespace folders

    def test_blank_output_folder_falls_back_to_default_for_both_layouts(self):
        self.assertEqual(self.project.output_folder, '')
        self.assertEqual(formal_output(self.project_path, self.project), self.root / 'work/mod')
        self.assertEqual(shown_output(self.project_path, self.project), self.root / 'work/mod')
        self.project.version_profiles = {'1.6': {}}
        self.assertEqual(formal_output(self.project_path, self.project), self.root / 'work/mod')
        self.assertEqual(trial_output(self.project_path, self.project), self.root / 'work/mod-test')
        self.assertEqual(shown_output(self.project_path, self.project), self.root / 'work/mod-test')

    def test_whitespace_output_folder_is_not_treated_as_blank_today(self):
        # Current behaviour, pinned on purpose: only the empty string means "default". A whitespace-only value
        # is kept as a relative path and refused, instead of falling back to <project>/mod.
        self.project.output_folder = '   '
        self.assertEqual(formal_output(self.project_path, self.project), Path('   '))
        self.assertEqual(shown_output(self.project_path, self.project), Path('   '))
        self.refused('   ', 'relative')

    # Relative and home-relative paths

    def test_relative_forms_are_refused(self):
        for relative in ('out', './out', '../out', 'Mods/MyTranslation', 'source/Translation'):
            with self.subTest(relative=relative):
                self.refused(relative, 'relative')

    def test_tilde_expands_to_home_before_the_checks(self):
        with mock.patch.dict(os.environ, {'HOME': str(self.root / 'home')}):
            self.assertEqual(self.check('~/MyTranslation'), (self.root / 'home/MyTranslation').resolve())
        with mock.patch.dict(os.environ, {'HOME': str(self.source)}):
            self.refused('~/Translation', 'source')

    # Trailing separators

    def test_trailing_separator_is_normalised(self):
        target = self.root / 'exports/Mine'
        self.assertEqual(self.check(str(target) + os.sep), target.resolve())

    def test_trailing_separator_does_not_hide_protected_overlap(self):
        self.refused(str(self.source) + os.sep, 'source')
        self.refused(str(self.workshop) + os.sep, 'workshop')
        self.refused(str(self.game_root / 'Data') + os.sep, 'data')
        self.refused(str(self.game_root / 'Mods') + os.sep, 'mods')
        self.refused(str(self.project_path.parent) + os.sep, 'project')

    # '..' segments

    def test_dotdot_segments_resolving_into_protected_folders_are_refused(self):
        self.refused(self.root / 'exports' / '..' / 'source' / 'Translation', 'source')
        self.refused(self.root / 'exports' / '..' / 'workshop' / '123', 'workshop')
        self.refused(self.root / 'x' / '..' / 'game' / 'Data' / 'Mine', 'data')
        self.refused(self.root / 'x' / '..' / 'external' / 'Mine', 'external')
        self.refused(self.game_root / 'Mods' / 'Other' / '..' / '..' / 'Mods', 'mods')

    def test_dotdot_segments_resolving_outside_protected_folders_are_accepted(self):
        target = self.root / 'work' / '..' / 'exports' / 'Mine'
        self.assertEqual(self.check(target), (self.root / 'exports/Mine').resolve())

    # Symlinks

    def test_symlinks_into_protected_folders_are_refused(self):
        links = {
            'to_source': (self.source, 'Translation', 'source'),
            'to_workshop': (self.workshop, '123', 'workshop'),
            'to_data': (self.game_root / 'Data', 'Mine', 'data'),
            'to_external': (self.external, 'Mine', 'external'),
        }
        for name, (destination, child, reason) in links.items():
            with self.subTest(link=name):
                link = self.root / name
                link.symlink_to(destination, target_is_directory=True)
                self.refused(link / child, reason)

    def test_symlink_to_mods_folder_itself_is_refused(self):
        link = self.root / 'to_mods'
        link.symlink_to(self.game_root / 'Mods', target_is_directory=True)
        self.refused(link, 'mods')

    def test_symlink_to_direct_child_of_mods_is_accepted(self):
        # Resolves to Mods/MyTranslation, the one arrangement install allows.
        link = self.root / 'to_mods'
        link.symlink_to(self.game_root / 'Mods', target_is_directory=True)
        self.assertEqual(self.check(link / 'MyTranslation'), (self.game_root / 'Mods/MyTranslation').resolve())

    def test_symlink_into_deep_mods_subfolder_is_refused(self):
        (self.game_root / 'Mods/Other/Deep').mkdir(parents=True)
        link = self.root / 'to_deep'
        link.symlink_to(self.game_root / 'Mods/Other/Deep', target_is_directory=True)
        self.refused(link, 'mods')

    def test_chained_symlinks_are_resolved_before_the_check(self):
        first = self.root / 'first'
        second = self.root / 'second'
        first.symlink_to(self.source, target_is_directory=True)
        second.symlink_to(first, target_is_directory=True)
        self.refused(second / 'Translation', 'source')

    def test_symlink_to_project_folder_is_refused(self):
        link = self.root / 'to_project'
        link.symlink_to(self.project_path.parent, target_is_directory=True)
        self.refused(link, 'project')

    def test_output_inside_project_folder_is_accepted(self):
        # The default layout (work/mod, work/mod-test) lives inside the project folder and must stay allowed.
        self.assertEqual(self.check(self.project_path.parent / 'mod'), (self.root / 'work/mod').resolve())

    # Prefix-only overlaps must not be refused

    def test_sibling_sharing_a_name_prefix_with_source_is_accepted(self):
        self.assertEqual(self.check(self.root / 'source2/Translation'), (self.root / 'source2/Translation').resolve())
        self.assertEqual(self.check(self.root / 'source-out'), (self.root / 'source-out').resolve())
        self.assertEqual(self.check(self.root / 'sour'), (self.root / 'sour').resolve())

    def test_sibling_sharing_a_name_prefix_with_workshop_and_external_is_accepted(self):
        self.assertEqual(self.check(self.root / 'workshop2/123'), (self.root / 'workshop2/123').resolve())
        self.assertEqual(self.check(self.root / 'external2/Mine'), (self.root / 'external2/Mine').resolve())

    def test_sibling_sharing_a_name_prefix_with_game_folders_is_accepted(self):
        self.assertEqual(self.check(self.game_root / 'Mods2/MyTranslation'),
                         (self.game_root / 'Mods2/MyTranslation').resolve())
        self.assertEqual(self.check(self.game_root / 'Data2/Mine'), (self.game_root / 'Data2/Mine').resolve())

    def test_project_folder_prefix_sibling_is_accepted(self):
        # The project folder is work/; work2 and work-notes are siblings, not parents or children.
        self.assertEqual(self.check(self.root / 'work2'), (self.root / 'work2').resolve())
        self.assertEqual(self.check(self.root / 'work-notes/mod'), (self.root / 'work-notes/mod').resolve())

    def test_default_style_mod_and_mod2_do_not_collide(self):
        self.assertEqual(self.check(self.project_path.parent / 'mod2'), (self.root / 'work/mod2').resolve())
        self.assertEqual(self.check(self.project_path.parent / 'mod-test'), (self.root / 'work/mod-test').resolve())

    def test_user_folder_prefix_sibling_is_used_as_is(self):
        chosen = self.root / 'exports/MyTranslation'
        self.project.output_folder = str(chosen)
        self.assertEqual(resolve_output(self.project_path, self.project, self.settings, [self.game]),
                         chosen.resolve())
        sibling = self.root / 'exports/MyTranslation2'
        self.project.output_folder = str(sibling)
        self.assertEqual(resolve_output(self.project_path, self.project, self.settings, [self.game]),
                         sibling.resolve())


if __name__ == '__main__':
    unittest.main()

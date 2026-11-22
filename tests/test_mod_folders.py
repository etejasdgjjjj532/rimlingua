"""User-set MOD folders, ModsConfig.xml discovery (native, Proton, explicit) and source-folder recognition."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from rimworld_translator.platforms import (GameInstallation, PROTON_PROFILE, find_mods_config, is_mod_folder,
                                           mod_folders, mod_roots, mods_config_candidates)


def make_mod(folder: Path, package='a.b'):
    (folder / 'About').mkdir(parents=True)
    (folder / 'About/About.xml').write_text(f'<ModMetaData><packageId>{package}</packageId></ModMetaData>')
    return folder


class ModsConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        registry = patch('rimworld_translator.platforms._windows_steam_roots', return_value=[])
        registry.start()
        self.addCleanup(registry.stop)

    def config(self, folder: Path):
        path = folder / 'Config/ModsConfig.xml'
        path.parent.mkdir(parents=True)
        path.write_text('<ModsConfigData><activeMods><li>ludeon.rimworld</li></activeMods></ModsConfigData>')
        return path

    def test_native_linux_profile_is_found(self):
        native = self.config(self.home / '.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios')
        self.assertEqual(find_mods_config(platform='linux', home=self.home), native)

    def test_proton_profile_in_a_steam_library_is_found(self):
        steam = self.home / '.local/share/Steam'
        proton = self.config(steam / PROTON_PROFILE)
        self.assertEqual(find_mods_config(platform='linux', home=self.home), proton)

    def test_proton_profile_in_an_extra_library_is_found(self):
        steam = self.home / '.local/share/Steam'
        (steam / 'steamapps').mkdir(parents=True)
        other = self.root / 'disk2'
        (steam / 'steamapps/libraryfolders.vdf').write_text(
            '"libraryfolders" { "1" { "path" "' + str(other) + '" } }')
        proton = self.config(other / PROTON_PROFILE)
        self.assertIn(proton, mods_config_candidates(platform='linux', home=self.home))
        self.assertEqual(find_mods_config(platform='linux', home=self.home), proton)

    def test_native_profile_wins_over_proton(self):
        native = self.config(self.home / '.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios')
        self.config(self.home / '.local/share/Steam' / PROTON_PROFILE)
        self.assertEqual(find_mods_config(platform='linux', home=self.home), native)

    def test_explicit_setting_is_the_only_candidate(self):
        self.config(self.home / '.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios')
        portable = self.config(self.root / 'portable/SaveData')
        self.assertEqual(find_mods_config(str(portable), platform='linux', home=self.home), portable)
        self.assertIsNone(find_mods_config(str(self.root / 'missing.xml'), platform='linux', home=self.home))

    def test_explicit_folder_means_its_config_file(self):
        portable = self.config(self.root / 'portable/SaveData')
        self.assertEqual(find_mods_config(str(self.root / 'portable/SaveData'), platform='linux', home=self.home), portable)

    def test_nothing_found_is_none(self):
        self.assertIsNone(find_mods_config(platform='linux', home=self.home))


class ModRootsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game_root = self.root / 'steamapps/common/RimWorld'
        (self.game_root / 'Mods').mkdir(parents=True)
        self.workshop = self.root / 'steamapps/workshop/content/294100'
        self.workshop.mkdir(parents=True)
        self.game = GameInstallation(self.game_root, self.game_root / 'Mods', self.workshop, '1.6', None)

    def test_empty_settings_use_detected_folders(self):
        roots = mod_roots({'workshop_folder': '', 'mods_folder': '', 'external_mod_folders': []}, [self.game])
        self.assertEqual(roots.workshop, (self.workshop,))
        self.assertEqual(roots.mods, (self.game_root / 'Mods',))
        self.assertEqual(roots.external, ())

    def test_set_folders_replace_detection(self):
        mine = self.root / 'my workshop'
        mods = self.root / 'my mods'
        extra = [str(self.root / 'x'), str(self.root / 'y')]
        roots = mod_roots({'workshop_folder': str(mine), 'mods_folder': str(mods), 'external_mod_folders': extra},
                          [self.game])
        self.assertEqual(roots.workshop, (mine,))
        self.assertEqual(roots.mods, (mods,))
        self.assertEqual(roots.external, tuple(Path(p) for p in extra))
        self.assertEqual(roots.all(), (mine, mods, *map(Path, extra)))

    def test_mod_folders_lists_only_mods_once(self):
        make_mod(self.workshop / '111')
        (self.workshop / 'notamod').mkdir()
        make_mod(self.workshop / '.hidden')
        found = mod_folders([self.workshop, self.workshop, self.root / 'missing'])
        self.assertEqual(found, [self.workshop / '111'])


class SourceFolderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_about_file_makes_a_mod(self):
        self.assertTrue(is_mod_folder(make_mod(self.root / 'm')))

    def test_lowercase_about_is_accepted(self):
        (self.root / 'm/about').mkdir(parents=True)
        (self.root / 'm/about/about.xml').write_text('<ModMetaData/>')
        self.assertTrue(is_mod_folder(self.root / 'm'))

    def test_defs_or_languages_without_about_is_accepted(self):
        (self.root / 'old/Defs').mkdir(parents=True)
        (self.root / 'lang/Languages').mkdir(parents=True)
        (self.root / 'versioned/1.6/Defs').mkdir(parents=True)
        for name in ('old', 'lang', 'versioned'):
            self.assertTrue(is_mod_folder(self.root / name), name)

    def test_an_ordinary_folder_is_refused(self):
        (self.root / 'photos/holiday').mkdir(parents=True)
        (self.root / 'photos/a.txt').write_text('x')
        self.assertFalse(is_mod_folder(self.root / 'photos'))
        self.assertFalse(is_mod_folder(self.root / 'missing'))


class CacheLocationTests(unittest.TestCase):
    def test_user_location_replaces_the_default(self):
        from rimworld_translator.platforms import app_cache_directory
        self.assertEqual(app_cache_directory('linux', '/h', {}, override='/fast/cache'), Path('/fast/cache'))
        self.assertEqual(app_cache_directory('linux', '/h', {}, override=''), Path('/h/.cache/rimworld-translation-editor'))


if __name__ == '__main__':
    unittest.main()

"""Installation discovery with portable Steam/non-Steam filesystem fixtures."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from rimworld_translator.platforms import discover_installations


class PlatformTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # Resolve 8.3 short names (RUNNER~1) so expected paths match what the code returns on Windows.
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        registry = patch("rimworld_translator.platforms._windows_steam_roots", return_value=[])
        registry.start()
        self.addCleanup(registry.stop)
        environment = patch.dict(os.environ, {key: "" for key in (
            "ProgramFiles(x86)", "ProgramFiles", "PROGRAMFILES(X86)", "PROGRAMFILES",
        )})
        environment.start()
        self.addCleanup(environment.stop)

    def game(self, root, executable="RimWorldLinux"):
        (root / "Data/Core").mkdir(parents=True)
        (root / "Mods").mkdir()
        (root / executable).write_bytes(b"fixture executable")
        (root / "Version.txt").write_text("1.6.4871 rev598\n")
        return root

    def library(self, root, directory="RimWorld", executable="RimWorldLinux"):
        game = self.game(root / "steamapps/common" / directory, executable)
        (root / "steamapps/appmanifest_294100.acf").write_text(
            '"AppState" { "appid" "294100" "installdir" "' + directory + '" }'
        )
        (root / "steamapps/workshop/content/294100").mkdir(parents=True)
        return game

    def test_linux_default_and_multiple_library_vdf(self):
        steam = self.home / ".local/share/Steam"
        original = self.library(steam)
        second = self.root / "another disk/SteamLibrary"
        added = self.library(second, "RimWorld custom directory")
        (steam / "steamapps/libraryfolders.vdf").write_text(
            '"libraryfolders" { "0" { "path" "' + str(steam) + '" } '
            '"1" { "path" "' + str(second) + '" "apps" { "294100" "1" } } }'
        )
        found = discover_installations(platform="linux", home=self.home)
        self.assertEqual({item.root for item in found}, {original, added})
        self.assertEqual(found[0].version, "1.6.4871")
        self.assertEqual(found[0].mods, original / "Mods")
        self.assertEqual(found[0].workshop, steam / "steamapps/workshop/content/294100")

    def test_old_library_vdf_and_duplicate_custom_path(self):
        steam = self.root / "Steam"
        game = self.library(steam)
        second = self.root / "second"
        other = self.library(second)
        (steam / "steamapps/libraryfolders.vdf").write_text(
            '"LibraryFolders" { "TimeNextStatsReport" "0" "1" "' + str(second) + '" }'
        )
        found = discover_installations(
            custom_paths=[game, game / "RimWorldLinux"], steam_roots=[steam],
            platform="linux", home=self.home,
        )
        self.assertEqual({item.root for item in found}, {game, other})
        self.assertEqual(len(found), 2)
        self.assertEqual(next(item for item in found if item.root == game).distribution, "Steam")

    def test_windows_spaces_registry_and_multiple_libraries(self):
        steam = self.root / "Program Files (x86)/Steam"
        game = self.library(steam, executable="RimWorldWin64.exe")
        second = self.root / "D drive/Steam library"
        other = self.library(second, executable="RimWorldWin64.exe")
        (steam / "steamapps/libraryfolders.vdf").write_text(
            '"libraryfolders" { "1" { "path" "' + str(second) + '" } }'
        )
        with patch("rimworld_translator.platforms._windows_steam_roots", return_value=[steam]):
            found = discover_installations(platform="win32", home=self.home)
        self.assertEqual({item.root for item in found}, {game, other})
        self.assertTrue(all(item.executable.name == "RimWorldWin64.exe" for item in found))

    def test_non_steam_custom_game_or_executable(self):
        game = self.game(self.root / "Downloaded games/RimWorld", "RimWorldWin.exe")
        found = discover_installations([game / "RimWorldWin.exe"], platform="win32", home=self.home)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].root, game)
        self.assertEqual(found[0].distribution, "Custom")
        self.assertIsNone(found[0].workshop)

    def test_lowercase_data_and_version_file_are_found(self):
        game = self.root / "copied/RimWorld"
        (game / "data/core").mkdir(parents=True)
        (game / "version.txt").write_text("﻿1.4.3901 rev238\r\n", encoding="utf-8")
        found = discover_installations([game], platform="linux", home=self.home)
        self.assertEqual([(item.root, item.version) for item in found], [(game, "1.4.3901")])

    def test_invalid_custom_folder_ignored_and_unknown_version_explicit(self):
        invalid = self.root / "ordinary folder"
        invalid.mkdir()
        game = self.game(self.root / "custom")
        (game / "Version.txt").unlink()
        found = discover_installations([invalid, game], platform="linux", home=self.home)
        self.assertEqual([item.root for item in found], [game])
        self.assertEqual(found[0].version, "")

    def test_vdf_path_escape_and_comment_parser(self):
        steam = self.root / "Steam"
        steam.mkdir()
        (steam / "steamapps").mkdir()
        second = self.root / ("disk with spaces" if os.name == "nt" else 'quoted "disk"')
        game = self.library(second)
        escaped = str(second).replace("\\", "\\\\").replace('"', '\\"')
        (steam / "steamapps/libraryfolders.vdf").write_text(
            '// comment with braces {\n"libraryfolders" { "1" { "path" "' + escaped + '" } }'
        )
        found = discover_installations(platform="linux", home=self.home, steam_roots=[steam])
        self.assertEqual([item.root for item in found], [game])

    def test_missing_or_invalid_manifest_falls_back_to_standard_directory(self):
        steam = self.root / "Steam"
        game = self.library(steam)
        (steam / "steamapps/appmanifest_294100.acf").write_text('"AppState" { "installdir" "../other" }')
        found = discover_installations(platform="linux", home=self.home, steam_roots=[steam])
        self.assertEqual([item.root for item in found], [game])

    def test_explicit_game_from_unregistered_steam_library_retains_workshop_path(self):
        steam = self.root / "unregistered disk/SteamLibrary"
        game = self.library(steam)
        found = discover_installations([game], platform="linux", home=self.home)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].distribution, "Steam")
        self.assertEqual(found[0].workshop, steam / "steamapps/workshop/content/294100")


if __name__ == "__main__":
    unittest.main()

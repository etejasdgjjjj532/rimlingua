"""Game folders in the user's library are identified by Version.txt, the game DLL and the DLCs that DLL knows."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.game_library import (
    contradicts, game_dll, identify_game, known_game_paths, library_directory, library_game_roots,
)


def make_game(root, version_txt, dll_strings, dlc_folders, data_dir='RimWorldLinux_Data'):
    """A synthetic game folder; the DLL holds only the UTF-16 strings the game's real DLL would contain."""
    root = Path(root)
    dll = root / data_dir / 'Managed/Assembly-CSharp.dll'
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b'MZ synthetic\x00' + b'\x00\x00'.join(s.encode('utf-16-le') for s in dll_strings) + b'\x00\x00')
    if version_txt is not None:
        (root / 'Version.txt').write_text(version_txt, encoding='utf-8', newline='')
    for name, package in {'Core': 'Ludeon.RimWorld', **dlc_folders}.items():
        about = root / 'Data' / name / 'About/About.xml'
        about.parent.mkdir(parents=True)
        about.write_text(f'<ModMetaData><packageId>{package}</packageId></ModMetaData>')
    return root


class GameLibraryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)

    def test_version_build_and_dlcs_from_version_txt_and_dll(self):
        root = make_game(self.tmp/'g', '\ufeff1.4.3901 rev238\r\n', ['1.4.8000', 'ludeon.rimworld.royalty', 'ludeon.rimworld.biotech'],
                         {'Royalty': 'Ludeon.RimWorld.Royalty', 'Biotech': 'Ludeon.RimWorld.Biotech'})
        identity = identify_game(root)
        self.assertEqual((identity.version, identity.build, identity.problem), ('1.4', '1.4.3901', ''))
        self.assertEqual(identity.dll_versions, ('1.4',))
        self.assertEqual(identity.dlcs, ('ludeon.rimworld.biotech', 'ludeon.rimworld.royalty'))
        self.assertEqual(identity.excluded, ())

    def test_leftover_dlc_from_later_version_is_excluded(self):
        root = make_game(self.tmp/'g', '1.1.2654 rev673', ['1.1.7459', 'ludeon.rimworld.royalty'],
                         {'Royalty': 'ludeon.rimworld.royalty', 'Biotech': 'ludeon.rimworld.biotech'})
        identity = identify_game(root)
        self.assertEqual(identity.dlcs, ('ludeon.rimworld.royalty',))
        self.assertEqual([p.name for p in identity.excluded], ['Biotech'])

    def test_unknown_future_dlc_known_to_the_dll_is_accepted(self):
        root = make_game(self.tmp/'g', '1.9.1', ['1.9.1', 'ludeon.rimworld.newthing'], {'NewThing': 'ludeon.rimworld.newthing'})
        self.assertEqual(identify_game(root).dlcs, ('ludeon.rimworld.newthing',))

    def test_non_ludeon_folder_under_data_is_left_alone(self):
        root = make_game(self.tmp/'g', '1.6.1', ['1.6.1'], {'Extra': 'someone.extra'})
        identity = identify_game(root)
        self.assertEqual((identity.dlcs, identity.excluded), ((), ()))

    def test_dll_of_another_version_is_a_problem(self):
        root = make_game(self.tmp/'g', '1.6.4871', ['1.5.9214'], {})
        identity = identify_game(root)
        self.assertEqual(identity.version, '1.6')
        self.assertIn('1.5', identity.problem)

    def test_dll_without_version_string_is_not_a_contradiction(self):
        root = make_game(self.tmp/'g', '1.6.4871', [], {})
        identity = identify_game(root)
        self.assertEqual((identity.dll_versions, identity.problem), ((), ''))
        self.assertFalse(contradicts(identity, '1.6'))
        self.assertTrue(contradicts(identify_game(make_game(self.tmp/'h', '1.6.1', ['1.5.9214'], {})), '1.6'))

    def test_missing_dll_or_version_is_a_problem(self):
        root = make_game(self.tmp/'g', '1.6.4871', ['1.6.9676'], {})
        game_dll(root).unlink()
        self.assertTrue(identify_game(root).problem)
        self.assertTrue(identify_game(make_game(self.tmp/'n', None, ['1.6.9676'], {})).problem)
        self.assertTrue(identify_game(self.tmp/'empty').problem)

    def test_windows_and_mac_layouts_are_found_on_any_os(self):
        win = make_game(self.tmp/'w', '1.6.1', ['1.6.1'], {}, data_dir='RimWorldWin64_Data')
        mac = make_game(self.tmp/'m', '1.6.1', ['1.6.1'], {}, data_dir='RimWorldMac.app/Contents/Resources/Data')
        self.assertEqual(game_dll(win).parent.parent.name, 'RimWorldWin64_Data')
        self.assertEqual(identify_game(mac).problem, '')

    def test_names_are_matched_without_case(self):
        root = make_game(self.tmp/'g', '1.6.1', ['1.6.1', 'ludeon.rimworld.royalty'], {'royalty': 'ludeon.rimworld.royalty'},
                         data_dir='rimworldwin64_data')
        (root / 'Version.txt').rename(root / 'version.txt')
        (root / 'Data').rename(root / 'data')
        identity = identify_game(root)
        self.assertEqual((identity.version, identity.dlcs, identity.problem), ('1.6', ('ludeon.rimworld.royalty',), ''))

    def test_library_directory_per_os_and_override(self):
        env = {'LOCALAPPDATA': r'C:\Users\u\AppData\Local', 'XDG_DATA_HOME': '/x'}
        self.assertEqual(library_directory('win32', Path('/h'), env), Path(r'C:\Users\u\AppData\Local') / 'RimWorldTranslationEditor/games')
        self.assertEqual(library_directory('darwin', Path('/h'), {}), Path('/h/Library/Application Support/RimWorldTranslationEditor/games'))
        self.assertEqual(library_directory('linux', Path('/h'), {}), Path('/h/.local/share/rimworld-translation-editor/games'))
        self.assertEqual(library_directory('linux', Path('/h'), env), Path('/x/rimworld-translation-editor/games'))
        self.assertEqual(library_directory('linux', Path('/h'), env, override='/mine'), Path('/mine'))

    def test_library_lists_version_folders_newest_first(self):
        for version in ('1.1', '1.6', '1.10'):
            make_game(self.tmp/'lib'/version/'RimWorld', f'{version}.1', [f'{version}.1'], {})
        (self.tmp/'lib/notes').mkdir()
        (self.tmp/'lib/1.6/empty').mkdir()
        self.assertEqual([p.parent.name for p in library_game_roots(self.tmp/'lib')], ['1.10', '1.6', '1.1'])
        self.assertEqual(library_game_roots(self.tmp/'missing'), [])

    def test_dlc_folder_reached_through_a_link_is_still_identified(self):
        root = make_game(self.tmp/'g', '1.6.1', ['1.6.1', 'ludeon.rimworld.royalty'], {})
        real = make_game(self.tmp/'elsewhere', '1.6.1', [], {'Royalty': 'ludeon.rimworld.royalty'}) / 'Data/Royalty'
        (root / 'Data/Royalty').symlink_to(real, target_is_directory=True)
        linked = self.tmp / 'linked-library'
        linked.symlink_to(self.tmp, target_is_directory=True)
        self.assertEqual(identify_game(linked / 'g').dlcs, ('ludeon.rimworld.royalty',))

    def test_only_game_like_version_strings_count(self):
        root = make_game(self.tmp/'g', '1.6.4871', ['1.6.9676.18234', '0.1.32425', '127.0.0.1', '2.0.0.0', '1.5.9214.1.2'], {})
        self.assertEqual(identify_game(root).dll_versions, ('1.6',))

    def test_build_game_table_reads_lowercase_data_and_bom_version(self):
        from unittest.mock import patch
        from rimworld_translator.schema import build_game_table
        root = make_game(self.tmp/'g', '\ufeff1.6.4871 rev598\r\n', ['1.6.1'], {'Royalty': 'ludeon.rimworld.royalty'})
        defs = root / 'Data/Core/defs/a.xml'
        defs.parent.mkdir()
        defs.write_text('<Defs><ThingDef><defName>Gun</defName></ThingDef></Defs>')
        (root / 'Data').rename(root / 'data')
        with patch('rimworld_translator.schema.inspect_assembly', return_value={}):
            table = build_game_table(root)
        self.assertEqual(table['rimworld_version'], '1.6.4871 rev598')
        self.assertEqual(table['data_folders'], ['Core', 'Royalty'])
        self.assertEqual(table['def_names'], ['Gun'])

    def test_identity_is_reused_until_the_game_changes(self):
        import os
        root = make_game(self.tmp/'g', '1.6.1', ['1.6.9676.1'], {})
        first = identify_game(root)
        self.assertIs(identify_game(root), first)
        dll = game_dll(root)
        dll.write_bytes(dll.read_bytes() + '1.5.9214.1'.encode('utf-16-le'))
        os.utime(dll, ns=(1, 1))
        self.assertIsNot(identify_game(root), first)

    def test_known_game_paths_add_library_games_after_explicit_ones_once(self):
        game = make_game(self.tmp/'lib/1.4/RimWorld', '1.4.1', ['1.4.1'], {})
        self.assertEqual(known_game_paths({'game_paths': ['/a'], 'game_library': str(self.tmp/'lib')}), ['/a', str(game)])
        self.assertEqual(known_game_paths({'game_paths': [str(game)], 'game_library': str(self.tmp/'lib')}), [str(game)])


if __name__ == '__main__':
    unittest.main()

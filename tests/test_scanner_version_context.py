"""Game metadata from another version must not establish field eligibility."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rimworld_translator.gui import DeclaredVersionScanner, Scanner
from rimworld_translator.platforms import GameInstallation
from rimworld_translator.schema import TranslationSchema, TypeSpec, FieldSpec


class ScannerVersionContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        about = self.source / 'About/About.xml'
        about.parent.mkdir(parents=True)
        about.write_text('<ModMetaData><packageId>test.versioncontext</packageId>'
                         '<supportedVersions><li>1.4</li><li>1.6</li></supportedVersions></ModMetaData>')
        defs = self.source / 'Defs/a.xml'
        defs.parent.mkdir()
        defs.write_text('<Defs><ThingDef><defName>Demo</defName><label>Visible item</label>'
                        '<special>Version-specific message</special></ThingDef></Defs>')

    def game(self, name, version):
        root = self.root / name
        dll = root / 'RimWorld_Data/Managed/Assembly-CSharp.dll'
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b'synthetic metadata boundary; never executed')
        return GameInstallation(root, root / 'Mods', None, version, None)

    def scan(self, games):
        worker = Scanner(self.source, {'game_version': '1.4', 'active_mods': []}, True)
        results = []
        worker.finished.connect(lambda result, error: results.append((result, error)))

        def metadata(paths, *args, **kwargs):
            # This field is eligible only with the explicitly matched fixture.
            schema = TranslationSchema()
            if any(path.parent.parent.parent.name == 'old-game' for path in paths):
                schema.types = {'Verse.Def': TypeSpec('Verse.Def'),
                                'ThingDef': TypeSpec('ThingDef', 'Verse.Def',
                                                    {'special': FieldSpec('System.String')})}
            return schema

        with patch('rimworld_translator.platforms.discover_installations', return_value=games), \
                patch('rimworld_translator.schema.schema_from_assemblies', side_effect=metadata):
            worker.run()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], '')
        return results[0][0]

    def test_selects_matching_installation_instead_of_first_game(self):
        scan = self.scan([self.game('new-game', '1.6.4871'), self.game('old-game', '1.4.3901')])
        self.assertIn('Demo.special', [entry.key for entry in scan.entries])
        self.assertEqual(scan.stats['game_context']['version'], '1.4')
        self.assertEqual(scan.stats['game_context']['root'], str(self.root / 'old-game'))

    def test_unknown_or_mismatched_game_remains_explicitly_unverified(self):
        for version in ('1.6.4871', '', 'unknown'):
            with self.subTest(version=version):
                name = 'old-game'  # Would supply eligible metadata if wrongly used.
                if (self.root / name).exists():
                    games = [GameInstallation(self.root / name, self.root / name / 'Mods', None, version, None)]
                else:
                    games = [self.game(name, version)]
                scan = self.scan(games)
                self.assertNotIn('Demo.special', [entry.key for entry in scan.entries])
                self.assertIn('game-version-context-unverified', [d['code'] for d in scan.diagnostics])
                self.assertIsNone(scan.stats['game_context']['root'])

    def test_missing_game_keeps_static_xml_workflow_available(self):
        scan = self.scan([])
        self.assertIn('Demo.label', [entry.key for entry in scan.entries])
        self.assertIn('game-version-context-unverified', [d['code'] for d in scan.diagnostics])


class ScannerDependencyTests(unittest.TestCase):
    """Prerequisite MODs and library games reach the scan; a mixed game folder is refused."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'About/About.xml').write_text(
            '<ModMetaData><packageId>test.dependent</packageId><supportedVersions><li>1.4</li><li>1.6</li></supportedVersions>'
            '<modDependencies><li><packageId>sample.fw</packageId><displayName>Framework</displayName></li>'
            '<li><packageId>sample.gone</packageId><displayName>Gone</displayName></li></modDependencies></ModMetaData>')
        (self.source / 'Defs').mkdir()
        (self.source / 'Defs/a.xml').write_text(
            '<Defs><ThingDef><defName>Demo</defName><label>Visible item</label></ThingDef>'
            '<ThingDef MayRequire="sample.fw"><defName>Optional</defName><label>Optional item</label></ThingDef></Defs>')

    def game(self, name, version, dll_strings=(), version_txt=True):
        root = self.root / name
        dll = root / 'RimWorldLinux_Data/Managed/Assembly-CSharp.dll'
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b'synthetic ' + b'\x00\x00'.join(s.encode('utf-16-le') for s in dll_strings) + b'\x00\x00')
        (root / 'Data/Core/About').mkdir(parents=True)
        (root / 'Data/Core/About/About.xml').write_text('<ModMetaData><packageId>Ludeon.RimWorld</packageId></ModMetaData>')
        if version_txt:
            (root / 'Version.txt').write_text(version)
        return GameInstallation(root, root / 'Mods', None, version, None)

    def framework(self, game):
        fw = game.mods / 'fw'
        (fw / 'About').mkdir(parents=True)
        (fw / 'About/About.xml').write_text('<ModMetaData><packageId>sample.fw</packageId></ModMetaData>')
        (fw / 'Assemblies').mkdir()
        (fw / 'Assemblies/fw.dll').write_bytes(b'framework metadata; never executed')
        return fw

    def run_scanner(self, worker, games):
        calls, results = [], []
        worker.finished.connect(lambda result, error: results.append((result, error)))

        def metadata(paths, *args, **kwargs):
            calls.append([Path(p) for p in paths])
            return TranslationSchema()

        with patch('rimworld_translator.platforms.discover_installations', return_value=games), \
                patch('rimworld_translator.schema.schema_from_assemblies', side_effect=metadata):
            worker.run()
        self.assertEqual(results[0][1], '')
        return results[0][0], calls

    def test_prerequisite_assembly_and_folder_reach_the_scan(self):
        game = self.game('steam', '1.6.4871')
        fw = self.framework(game)
        worker = Scanner(self.source, {'game_version': '1.6', 'active_mods': []}, True)
        scan, calls = self.run_scanner(worker, [game])
        self.assertIn(fw / 'Assemblies/fw.dll', calls[0])
        self.assertIn(fw, [Path(p) for p in worker.options['context_sources']])

    def test_installed_prerequisite_counts_as_loaded_for_may_require(self):
        game = self.game('steam', '1.6.4871')
        self.framework(game)
        scan, _calls = self.run_scanner(Scanner(self.source, {'game_version': '1.6', 'active_mods': []}, True), [game])
        self.assertIn('Optional.label', [entry.key for entry in scan.entries])

    def test_missing_prerequisite_is_reported(self):
        game = self.game('steam', '1.6.4871')
        self.framework(game)
        scan, _calls = self.run_scanner(Scanner(self.source, {'game_version': '1.6', 'active_mods': []}, True), [game])
        missing = [d for d in scan.diagnostics if d['code'] == 'missing-dependency']
        self.assertEqual([d['package_ids'] for d in missing], [['sample.gone']])

    def test_game_folder_whose_dll_is_another_version_is_refused(self):
        mixed = self.game('mixed', '1.4.3901', ['1.5.9214.1'])
        scan, calls = self.run_scanner(Scanner(self.source, {'game_version': '1.4', 'active_mods': []}, True), [mixed])
        codes = [d['code'] for d in scan.diagnostics]
        self.assertIn('game-version-context-unverified', codes)
        self.assertIn('game-folder-rejected', codes)
        self.assertNotIn(mixed.root / 'RimWorldLinux_Data/Managed/Assembly-CSharp.dll', calls[0])

    def test_game_folder_without_dll_is_refused_and_its_leftovers_unread(self):
        partial = self.game('partial', '1.1.2654')
        (partial.root / 'RimWorldLinux_Data/Managed/Assembly-CSharp.dll').unlink()
        (partial.root / 'Data/Biotech/About').mkdir(parents=True)
        (partial.root / 'Data/Biotech/About/About.xml').write_text('<ModMetaData><packageId>Ludeon.RimWorld.Biotech</packageId></ModMetaData>')
        worker = Scanner(self.source, {'game_version': '1.1', 'active_mods': []}, True)
        scan, _calls = self.run_scanner(worker, [partial])
        self.assertIn('game-folder-rejected', [d['code'] for d in scan.diagnostics])
        self.assertNotIn(partial.root / 'Data/Biotech', [Path(p) for p in worker.options['context_sources']])

    def test_prerequisite_conditional_assembly_reaches_field_metadata(self):
        game = self.game('steam', '1.6.4871')
        fw = self.framework(game)
        (fw / 'LoadFolders.xml').write_text(
            '<loadFolders><v1.6><li>/</li><li IfModActive="sample.fw">Active</li></v1.6></loadFolders>')
        (fw / 'Active/Assemblies').mkdir(parents=True)
        (fw / 'Active/Assemblies/active.dll').write_bytes(b'conditional metadata; never executed')
        _scan, calls = self.run_scanner(Scanner(self.source, {'game_version': '1.6', 'active_mods': []}, True), [game])
        self.assertIn(fw / 'Active/Assemblies/active.dll', calls[0])

    def test_saved_active_mods_are_not_widened_by_prerequisites(self):
        game = self.game('steam', '1.6.4871')
        self.framework(game)
        scan, _calls = self.run_scanner(Scanner(self.source, {'game_version': '1.6', 'active_mods': []}, True), [game])
        self.assertIn('Optional.label', [entry.key for entry in scan.entries])
        self.assertEqual(scan.stats['active_mods'], [])

    def test_unknown_profile_treats_found_prerequisites_as_loaded(self):
        game = self.game('steam', '1.6.4871')
        fw = self.framework(game)
        (fw / 'LoadFolders.xml').write_text(
            '<loadFolders><v1.6><li>/</li><li IfModActive="sample.fw">Active</li></v1.6></loadFolders>')
        (fw / 'Active/Assemblies').mkdir(parents=True)
        (fw / 'Active/Assemblies/active.dll').write_bytes(b'conditional metadata; never executed')
        scan, calls = self.run_scanner(Scanner(self.source, {'game_version': '1.6', 'active_mods': None}, True), [game])
        self.assertIn('Optional.label', [entry.key for entry in scan.entries])
        self.assertIn(fw / 'Active/Assemblies/active.dll', calls[0])
        self.assertIsNone(scan.stats['active_mods'])

    def test_official_translation_patterns_become_entry_reasons(self):
        game = self.game('steam', '1.6.4871')
        pack = game.root / 'Data/Core/Languages/Japanese/DefInjected/ThingDef/a.xml'
        pack.parent.mkdir(parents=True)
        pack.write_text('<LanguageData><!-- EN: steel --><Steel.label>鋼鉄</Steel.label></LanguageData>', encoding='utf-8')
        scan, _calls = self.run_scanner(Scanner(self.source, {'game_version': '1.6', 'active_mods': []}, True), [game])
        demo = next(entry for entry in scan.entries if entry.key == 'Demo.label')
        self.assertIn('official-pattern', demo.reasons)
        result, _calls = self.run_scanner(DeclaredVersionScanner(self.source, {}, True), [game])
        demo = next(entry for entry in result.scans['1.6'].entries if entry.key == 'Demo.label')
        self.assertIn('official-pattern', demo.reasons)

    def test_declared_versions_treat_found_prerequisites_as_loaded(self):
        steam = self.game('steam', '1.6.4871', ['1.6.9676.1'])
        self.framework(steam)
        result, _calls = self.run_scanner(DeclaredVersionScanner(self.source, {}, True), [steam])
        self.assertIn('Optional.label', [entry.key for entry in result.scans['1.6'].entries])

    def test_each_declared_version_uses_its_own_library_game(self):
        steam = self.game('steam', '1.6.4871', ['1.6.9676.1'])
        self.framework(steam)
        library = self.game('library/1.4/RimWorld', '1.4.3901', ['1.4.8000.1'])
        library = GameInstallation(library.root, library.mods, None, library.version, None, distribution='Custom')
        result, calls = self.run_scanner(DeclaredVersionScanner(self.source, {}, True), [steam, library])
        old_dll = library.root / 'RimWorldLinux_Data/Managed/Assembly-CSharp.dll'
        self.assertTrue(any(old_dll in call for call in calls))
        self.assertTrue(any(steam.mods / 'fw/Assemblies/fw.dll' in call for call in calls if old_dll in call))
        self.assertNotIn('game-version-context-unverified', [d['code'] for d in result.scans['1.4'].diagnostics])
        self.assertIn('missing-dependency', [d['code'] for d in result.scans['1.4'].diagnostics])


class LibraryWiringTests(unittest.TestCase):
    """The main window hands library games to the scanner, and only to the scanner."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_scan_receives_library_games(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from rimworld_translator import gui
        from rimworld_translator.settings import SettingsStore
        from tests.test_game_library import make_game
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        library_game = make_game(root / 'lib/1.4/RimWorld', '1.4.3901', ['1.4.8000.1'], {})
        settings = SettingsStore(root / 'settings.json')
        settings.data['game_library'] = str(root / 'lib')
        settings.save()
        source = root / 'source'
        (source / 'About').mkdir(parents=True)
        (source / 'About/About.xml').write_text('<ModMetaData><packageId>test.wiring</packageId></ModMetaData>')
        captured = []

        class Recording(gui.Scanner):
            def __init__(self, *args):
                super().__init__(*args)
                captured.append(list(self.game_paths))

            def run(self):
                self.finished.emit(None, 'cancelled')

        window = gui.Window(settings_path=root / 'settings.json')
        try:
            with patch.object(gui, 'Scanner', Recording):
                window.start_scan(source, root / 'work/project.json', {'game_version': '1.4', 'active_mods': []})
                for _ in range(200):
                    if not window.busy:
                        break
                    self.app.processEvents()
                    window.thread.wait(10)
        finally:
            window.dirty = False
            window.close()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
        self.assertEqual(len(captured), 1)
        self.assertIn(str(library_game), captured[0])


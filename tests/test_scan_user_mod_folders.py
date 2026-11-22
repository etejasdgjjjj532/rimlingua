"""Scans find prerequisites in the user's own MOD folders, without writing to them."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rimworld_translator.gui import DeclaredVersionScanner, Scanner


def make_mod(folder, package, requires=()):
    about = Path(folder) / 'About/About.xml'
    about.parent.mkdir(parents=True)
    deps = ''.join(f'<li><packageId>{p}</packageId><displayName>{p}</displayName></li>' for p in requires)
    about.write_text(f'<ModMetaData><name>{package}</name><packageId>{package}</packageId>'
                     f'<supportedVersions><li>1.6</li></supportedVersions><modDependencies>{deps}</modDependencies></ModMetaData>')
    return Path(folder)


class UserModFolderScanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = make_mod(self.root / 'source', 'test.source', ['test.needed'])
        (self.source / 'Defs').mkdir()
        (self.source / 'Defs/a.xml').write_text('<Defs><ThingDef><defName>D</defName><label>Item</label></ThingDef></Defs>')
        self.library = self.root / 'my-mods'
        make_mod(self.library / 'needed', 'test.needed')

    def run_worker(self, worker):
        results = []
        worker.finished.connect(lambda result, error: results.append((result, error)))
        with patch('rimworld_translator.platforms.discover_installations', return_value=[]):
            worker.run()
        self.assertEqual(results[0][1], '')
        return results[0][0]

    def test_prerequisite_in_an_external_folder_is_used(self):
        worker = Scanner(self.source, {'game_version': '1.6', 'active_mods': []}, False, (),
                         {'external_mod_folders': [str(self.library)]})
        self.run_worker(worker)
        self.assertIn(self.library / 'needed', worker.options['context_sources'])

    def test_missing_prerequisite_is_reported_without_the_folder(self):
        worker = Scanner(self.source, {'game_version': '1.6', 'active_mods': []}, False)
        scan = self.run_worker(worker)
        self.assertTrue(any(d['code'] == 'missing-dependency' for d in scan.diagnostics))

    def test_workshop_and_mods_folders_from_settings_are_used(self):
        worker = Scanner(self.source, {'game_version': '1.6', 'active_mods': []}, False, (),
                         {'workshop_folder': str(self.library), 'mods_folder': str(self.root / 'none')})
        self.run_worker(worker)
        self.assertIn(self.library / 'needed', worker.options['context_sources'])

    def test_declared_version_scan_uses_user_folders_too(self):
        worker = DeclaredVersionScanner(self.source, {}, False, (), {'external_mod_folders': [str(self.library)]})
        with patch('rimworld_translator.multiversion.scan_declared_versions') as scan:
            scan.return_value = type('R', (), {'scans': {}})()
            self.run_worker(worker)
        contexts = scan.call_args.kwargs['contexts']
        self.assertIn(self.library / 'needed', contexts['1.6']['context_sources'])


if __name__ == '__main__':
    unittest.main()

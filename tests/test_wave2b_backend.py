"""Backup generations setting and the prerequisite report behind the prerequisites dialog."""
import json
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.platforms import GameInstallation
from rimworld_translator.scan_context import dependency_context, prerequisite_report, workshop_link
from rimworld_translator.settings import SettingsStore


class BackupGenerationSetting(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'settings.json'

    def test_default_keeps_everything(self):
        self.assertEqual(SettingsStore(self.path).data['backup_generations'], 0)

    def test_valid_and_invalid_values(self):
        self.path.write_text(json.dumps({'backup_generations': 25}))
        self.assertEqual(SettingsStore(self.path).data['backup_generations'], 25)
        for bad in (-1, 'x', 2.5, True, 100000):
            self.path.write_text(json.dumps({'backup_generations': bad}))
            self.assertEqual(SettingsStore(self.path).data['backup_generations'], 0, bad)


class PrerequisiteReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = GameInstallation(self.root / 'game', self.root / 'game/Mods', self.root / 'workshop', '1.6.4633', None)

    def mod(self, path, package, deps=(), languages=()):
        (path / 'About').mkdir(parents=True)
        items = ''.join(f'<li><packageId>{p}</packageId><displayName>{n}</displayName><steamWorkshopUrl>{u}</steamWorkshopUrl></li>'
                        for p, n, u in deps)
        (path / 'About/About.xml').write_text(f'<ModMetaData><name>{package} name</name><packageId>{package}</packageId>'
                                              f'<modDependencies>{items}</modDependencies></ModMetaData>')
        if package == 'sample.lib':
            (path / 'About/PublishedFileId.txt').write_text('2200001')
        for language in languages:
            (path / 'Languages' / language).mkdir(parents=True)
        return path

    def test_missing_and_found_prerequisites_are_described(self):
        self.mod(self.root / 'game/Data/Core', 'ludeon.rimworld')
        self.mod(self.game.workshop / '2200001', 'sample.lib', languages=['Japanese (日本語)'])
        source = self.mod(self.root / 'src', 'sample.src', deps=[
            ('sample.lib', 'Lib', ''),
            ('sample.gone', 'Gone Mod', 'steam://url/CommunityFilePage/2012345678'),
            ('sample.nolink', 'No Link', '')])
        context = dependency_context(self.game, (), source, '1.6', None)
        report = prerequisite_report(context, [{'code': 'missing-dependency', 'count': 7}])
        missing = {m.package_id: m for m in report.missing}
        self.assertEqual(set(missing), {'sample.gone', 'sample.nolink'})
        self.assertEqual(missing['sample.gone'].name, 'Gone Mod')
        self.assertEqual(missing['sample.gone'].workshop_id, '2012345678')
        self.assertIn('2012345678', workshop_link(missing['sample.gone']))
        self.assertEqual(workshop_link(missing['sample.nolink']), '')
        found = {f.package_id: f for f in report.found}
        self.assertIn('sample.lib', found)
        self.assertEqual(found['sample.lib'].workshop_id, '2200001')
        self.assertEqual(found['sample.lib'].translations, ('Japanese (日本語)',))
        self.assertTrue(found['ludeon.rimworld'].official)
        self.assertEqual(report.unverified_fields, 7)

    def test_unverified_fields_unknown_without_diagnostic(self):
        self.mod(self.root / 'game/Data/Core', 'ludeon.rimworld')
        source = self.mod(self.root / 'src', 'sample.src')
        report = prerequisite_report(dependency_context(self.game, (), source, '1.6', None), [])
        self.assertIsNone(report.unverified_fields)
        self.assertEqual(report.missing, ())


if __name__ == '__main__':
    unittest.main()

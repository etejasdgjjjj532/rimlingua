"""Export behaviour found by the 2026-11-19 random holdout and GUI review."""
from pathlib import Path
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import (EMPTY_OUTPUT_NOTICE, Entry, ExportBlocked, Project, Scan, export_mod, export_versions,
                                      export_versions_test, source_folder_problem)


def keyed(key, english, japanese=''):
    return Entry(f'Keyed:Keyed:{key}', 'Keyed', 'Keyed', key, english, 'Main.xml', japanese)


class ExportTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'About/About.xml').write_text('<ModMetaData><packageId>author.original</packageId></ModMetaData>')

    def project(self, entries):
        return Project(str(self.source), 'Example', 'local.translation.example', 'author.original', ['1.6'],
                       entries, [])


class SingleVersionExportTests(ExportTestCase):
    def test_formal_export_lists_every_blocking_entry(self):
        project = self.project([keyed('A', 'Hit {0}', '命中'), keyed('B', 'Ok', '了解'), keyed('C', '{1} x', 'x')])
        with self.assertRaises(ExportBlocked) as caught:
            export_mod(project, self.root / 'out')
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual([item[1] for item in caught.exception.entries], ['Keyed:Keyed:A', 'Keyed:Keyed:C'])
        self.assertFalse((self.root / 'out').exists())

    def test_test_export_writes_valid_rows_and_reports_the_rest(self):
        project = self.project([keyed('A', 'Hit {0}', '命中'), keyed('B', 'Ok', '了解')])
        warnings = export_mod(project, self.root / 'out', test_only=True)
        text = (self.root / 'out/Languages/Japanese/Keyed/Keyed.xml').read_text(encoding='utf-8')
        self.assertIn('了解', text)
        self.assertNotIn('命中', text)
        self.assertTrue(any('A' in warning and '除外' in warning for warning in warnings))
        marker = json.loads((self.root / 'out/.rimworld-translator.json').read_text(encoding='utf-8'))
        self.assertTrue(marker['test_only'])

    def test_project_without_entries_is_refused(self):
        with self.assertRaisesRegex(ValueError, '0件'):
            export_mod(self.project([]), self.root / 'out')
        self.assertFalse((self.root / 'out').exists())

    def test_source_folder_problem_names_the_missing_about(self):
        self.assertEqual(source_folder_problem(self.source), '')
        (self.source / 'About/About.xml').unlink()
        self.assertIn('About.xml', source_folder_problem(self.source))
        self.assertIn('About.xml', source_folder_problem(self.root / 'missing'))
        nested = self.root / 'collection'
        (nested / 'Inner/About').mkdir(parents=True)
        (nested / 'Inner/About/About.xml').write_text('<ModMetaData/>')
        self.assertIn('Inner', source_folder_problem(nested))

    def test_nothing_translated_is_reported_first(self):
        warnings = export_mod(self.project([keyed('B', 'Ok')]), self.root / 'out')
        self.assertEqual(warnings[0], EMPTY_OUTPUT_NOTICE)


class DependencyUrlTests(ExportTestCase):
    def about(self, project):
        export_mod(project, self.root / 'out')
        return ET.parse(self.root / 'out/About/About.xml').getroot().find('modDependencies/li')

    def test_workshop_folder_name_gives_steam_workshop_url(self):
        workshop = self.root / 'steamapps/workshop/content/294100/2009463077'
        (workshop / 'About').mkdir(parents=True)
        (workshop / 'About/About.xml').write_text('<ModMetaData><packageId>author.original</packageId></ModMetaData>')
        self.source = workshop
        dependency = self.about(self.project([keyed('B', 'Ok', '了解')]))
        self.assertEqual(dependency.findtext('steamWorkshopUrl'),
                         'https://steamcommunity.com/sharedfiles/filedetails/?id=2009463077')

    def test_source_url_gives_download_url(self):
        (self.source / 'About/About.xml').write_text(
            '<ModMetaData><packageId>author.original</packageId><url>https://github.com/author/mod</url></ModMetaData>')
        dependency = self.about(self.project([keyed('B', 'Ok', '了解')]))
        self.assertEqual(dependency.findtext('downloadUrl'), 'https://github.com/author/mod')
        self.assertIsNone(dependency.find('steamWorkshopUrl'))

    def test_non_http_source_url_is_ignored(self):
        (self.source / 'About/About.xml').write_text(
            '<ModMetaData><packageId>author.original</packageId><url>javascript:alert(1)</url></ModMetaData>')
        self.assertIsNone(self.about(self.project([keyed('B', 'Ok', '了解')])).find('downloadUrl'))


class VersionTestExportTests(ExportTestCase):
    def versions_project(self, versions, scanned):
        entry = Entry('DefInjected:ThingDef:Gun.label', 'DefInjected', 'ThingDef', 'Gun.label', 'gun', 'Things.xml')
        scans = {v: Scan(entries=[entry], name='Fixture', package_id='author.original', versions=versions,
                         stats={'active_version': v}) for v in scanned}
        project = Project.create_versions(self.source, scans)
        for version in scanned:
            project.switch_version(version)
            project.set_translation(entry.id, '銃')
        return project

    def test_test_export_holds_1_0_like_the_formal_export(self):
        project = self.versions_project(['1.0', '1.6'], ['1.0', '1.6'])
        warnings = export_versions_test(project, self.root / 'test')
        about = ET.parse(self.root / 'test/About/About.xml').getroot()
        self.assertEqual([li.text for li in about.find('supportedVersions')], ['1.6'])
        self.assertTrue((self.root / 'test/1.6/Languages').is_dir())
        self.assertFalse((self.root / 'test/1.0').exists())
        self.assertTrue(any('1.0' in warning and '保留' in warning for warning in warnings))
        marker = json.loads((self.root / 'test/.rimworld-translator.json').read_text(encoding='utf-8'))
        self.assertIn('1.0', marker['held_versions'])
        project.switch_version('1.6')
        project.mark_reviewed('DefInjected:ThingDef:Gun.label')
        self.assertIn('1.0', export_versions(project, self.root / 'formal').held)

    def test_test_export_holds_unscanned_versions(self):
        project = self.versions_project(['1.5', '1.6'], ['1.6'])
        warnings = export_versions_test(project, self.root / 'test')
        self.assertTrue(any('1.5' in warning for warning in warnings))
        self.assertFalse((self.root / 'test/1.5').exists())

    def test_test_export_refuses_when_nothing_can_be_tested(self):
        project = self.versions_project(['1.0', '1.6'], ['1.0'])
        with self.assertRaises(ValueError):
            export_versions_test(project, self.root / 'test')


if __name__ == '__main__':
    unittest.main()

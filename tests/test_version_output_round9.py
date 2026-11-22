"""Apply the unverified 1.0 load-rule guard to numerically equal versions."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_mod, export_versions_test
from rimworld_translator.multiversion import scan_declared_versions


LABEL = 'DefInjected:ThingDef:Item.label'


class VersionOutputRound9Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def project(self, versions, name):
        source = self.root / name
        about = source / 'About/About.xml'
        about.parent.mkdir(parents=True)
        about.write_text('<ModMetaData><name>Numeric versions</name>'
                         '<packageId>test.numericversions</packageId><supportedVersions>'
                         + ''.join(f'<li>{version}</li>' for version in versions)
                         + '</supportedVersions></ModMetaData>', encoding='utf-8')
        (source / 'LoadFolders.xml').write_text('<loadFolders>'
            + ''.join(f'<v{version}><li>{version}</li></v{version}>' for version in versions)
            + '</loadFolders>', encoding='utf-8')
        for version in versions:
            path = source / version / 'Defs/items.xml'
            path.parent.mkdir(parents=True)
            path.write_text('<Defs><ThingDef><defName>Item</defName>'
                            f'<label>item {version}</label></ThingDef></Defs>', encoding='utf-8')
        result = scan_declared_versions(source)
        self.assertEqual(result.failures, {})
        self.assertEqual(set(result.scans), set(versions))
        project = Project.create_versions(source, result.scans)
        for version in versions:
            project.switch_version(version)
            self.assertEqual(project.entry_index()[LABEL].english, f'item {version}')
            project.set_translation(LABEL, f'独立訳 {version}')
            project.mark_reviewed(LABEL, approved=True)
        saved = self.root / 'workspace' / f'{name}.json'
        project.save(saved)
        return Project.load(saved)

    def test_numeric_one_zero_alias_refuses_before_creating_output(self):
        for index, old_version in enumerate(('1.0', '1.00', '01.0', '01.00')):
            with self.subTest(version=old_version):
                project = self.project([old_version, '1.6'], f'old-{index}')
                target = self.root / f'output-{index}'
                # 1.0 is held (load rules unverified) and the other versions are still exported (2026-11-20).
                warnings = export_versions_test(project, target)
                self.assertTrue(any(old_version in warning and '保留' in warning for warning in warnings))
                self.assertFalse((target / old_version).exists())
                self.assertEqual([node.text for node in ET.parse(target / 'About/About.xml')
                                  .getroot().findall('supportedVersions/li')], ['1.6'])
                for version in project.versions:
                    project.switch_version(version)
                    self.assertEqual(project.get_translation(LABEL), f'独立訳 {version}')
                    self.assertTrue(project.entry_index()[LABEL].approved)

    def test_numeric_one_zero_alias_refuses_before_changing_existing_output(self):
        project = self.project(['01.00', '1.6'], 'existing')
        safe = self.project(['1.6'], 'safe-existing')
        project.package_id = safe.package_id
        target = self.root / 'existing-output'
        export_versions_test(safe, target)
        keep = target / 'notes.txt'
        keep.write_bytes(b'keep existing user content')
        before = {path.relative_to(target).as_posix(): path.read_bytes()
                  for path in target.rglob('*') if path.is_file()}
        export_versions_test(project, target)
        after = {path.relative_to(target).as_posix(): path.read_bytes()
                 for path in target.rglob('*') if path.is_file()}
        self.assertEqual(after['notes.txt'], before['notes.txt'])
        self.assertFalse(any(name.startswith('01.00') for name in after))

    def test_later_versions_remain_independent_and_legacy_export_still_works(self):
        versions = ['1.1', '1.3', '1.4', '1.5', '1.6', '1.9', '1.10']
        project = self.project(versions, 'later')
        target = self.root / 'later-output'
        warnings = export_versions_test(project, target)
        self.assertTrue(any('未検証' in warning for warning in warnings))
        about = ET.parse(target / 'About/About.xml').getroot()
        self.assertEqual([node.text for node in about.findall('supportedVersions/li')], versions)
        for version in versions:
            xml = target / version / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml'
            self.assertEqual(ET.parse(xml).getroot().findtext('Item.label'), f'独立訳 {version}')
        source = Path(project.source)
        legacy = Project.create(source, scan_declared_versions(source).scans['1.6'])
        legacy.set_translation(LABEL, '単一版の訳')
        legacy_target = self.root / 'legacy-output'
        export_mod(legacy, legacy_target)
        xml = legacy_target / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml'
        self.assertEqual(ET.parse(xml).getroot().findtext('Item.label'), '単一版の訳')


if __name__ == '__main__':
    unittest.main()

"""Reject cross-MOD rescans before modifying legacy translation history."""
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_mod, scan_mod


class VersionOutputRound24Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.write_mod(self.source, 'test.target')
        self.project = Project.create(self.source, scan_mod(self.source))
        self.identity = 'Keyed:Keyed:Greeting'
        self.project.set_translation(self.identity, '対象MODだけの訳')
        self.project.mark_reviewed(self.identity, approved=True)

    @staticmethod
    def write_mod(root, package_id):
        about = root / 'About/About.xml'
        about.parent.mkdir(parents=True)
        about.write_text('<ModMetaData><name>One target</name>'
                         f'<packageId>{package_id}</packageId>'
                         '<supportedVersions><li>1.6</li></supportedVersions>'
                         '</ModMetaData>', encoding='utf-8')
        keyed = root / 'Languages/English/Keyed/messages.xml'
        keyed.parent.mkdir(parents=True)
        keyed.write_text('<LanguageData><Greeting>Hello</Greeting></LanguageData>',
                         encoding='utf-8')

    def test_legacy_rescan_rejects_foreign_mod_without_reassigning_approved_work(self):
        saved = self.root / 'workspace/project.json'
        self.project.save(saved)
        before = copy.deepcopy(self.project)
        saved_before = saved.read_bytes()
        foreign = self.root / 'context'
        self.write_mod(foreign, 'test.context')
        foreign_scan = scan_mod(foreign)
        foreign_before = copy.deepcopy(foreign_scan)
        with self.assertRaisesRegex(ValueError, 'source MOD'):
            self.project.rescan(foreign_scan)
        self.assertEqual(self.project, before)
        self.assertEqual(foreign_scan, foreign_before)
        self.assertEqual(saved.read_bytes(), saved_before)
        self.project.save(saved)
        restored = Project.load(saved)
        self.assertEqual(restored.original_package_id, 'test.target')
        self.assertEqual(restored.get_translation(self.identity), '対象MODだけの訳')
        self.assertTrue(restored.entry_index()[self.identity].approved)
        output = self.root / 'output'
        export_mod(restored, output)
        about = ET.parse(output / 'About/About.xml').getroot()
        self.assertEqual(about.findtext('modDependencies/li/packageId'), 'test.target')
        self.assertEqual(ET.parse(output / 'Languages/Japanese/Keyed/Keyed.xml')
                         .getroot().findtext('Greeting'), '対象MODだけの訳')


if __name__ == '__main__':
    unittest.main()

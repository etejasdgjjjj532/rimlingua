"""Regression cases for the real-world mod automation pipeline."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from rimworld_translator.core import Project, scan_mod, export_mod, atomic_write
from rimworld_translator.history import snapshot


class RegressionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.source = self.base / 'mod_source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'Defs').mkdir()
        (self.source / 'About/About.xml').write_text(
            '<ModMetaData><name>Example</name><packageId>sample.example</packageId></ModMetaData>', encoding='utf-8'
        )
        (self.source / 'Defs/Example.xml').write_text(
            '<Defs><ThingDef><defName>TestThing</defName><label>English name</label></ThingDef></Defs>', encoding='utf-8'
        )

    def test_malformed_about_is_warning_not_crash(self):
        (self.source / 'About/About.xml').write_text('<ModMetaData><name>broken', encoding='utf-8')
        result = scan_mod(self.source)
        self.assertEqual(len(result.entries), 1)
        self.assertGreaterEqual(result.warning_count, 1)
        self.assertTrue(any('About/About.xml' in w for w in result.warnings))

    def test_many_warnings_bounded_with_count_and_summary(self):
        xml = '<Defs><ThingDef><defName>TestThing</defName><label>One</label><comps>' + (
            ''.join(f'<field{i}><li>Not extracted</li></field{i}>' for i in range(1650))
        ) + '</comps></ThingDef></Defs>'
        (self.source / 'Defs/Example.xml').write_text(xml, encoding='utf-8')
        result = scan_mod(self.source)
        self.assertEqual(result.warning_count, 1650)
        self.assertEqual(len(result.warnings), 1501)
        self.assertIn('150', result.warnings[-1])
        self.assertEqual([e.key for e in result.entries], ['TestThing.label'])

    def test_active_version_overrides_same_relative_file_without_false_duplicate(self):
        f = self.source / '1.6/Defs/Example.xml'
        f.parent.mkdir(parents=True)
        f.write_text('<Defs><ThingDef><defName>TestThing</defName><label>Another version</label></ThingDef></Defs>', encoding='utf-8')
        scanned = scan_mod(self.source)
        entry = next(e for e in scanned.entries if e.key == 'TestThing.label')
        self.assertFalse(entry.blocked)
        self.assertEqual(entry.english, 'Another version')
        entry.japanese = '重複を保護'
        project = Project.create(self.source, scanned)
        output = self.base / 'output'
        export_mod(project, output)
        self.assertTrue((output / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml').exists())

    def test_workshop_dependency_has_valid_source_url(self):
        import xml.etree.ElementTree as ET
        (self.source / 'About/PublishedFileId.txt').write_text('3687005016\n')
        p = Project.create(self.source, scan_mod(self.source))
        output = self.base / 'output'
        export_mod(p, output)
        root = ET.parse(output / 'About/About.xml').getroot()
        self.assertEqual(
            root.findtext('modDependencies/li/steamWorkshopUrl'),
            'https://steamcommunity.com/sharedfiles/filedetails/?id=3687005016',
        )
    def test_git_history_can_restore_prior_translation(self):
        p = Project.create(self.source, scan_mod(self.source))
        project_path = self.base / 'workspace/project.json'
        p.entries[0].japanese = '最初の翻訳'
        p.save(project_path)
        export_mod(p, project_path.parent / 'mod')
        self.assertTrue(snapshot(project_path))
        p.entries[0].japanese = '修正した翻訳'
        p.save(project_path)
        export_mod(p, project_path.parent / 'mod')
        self.assertTrue(snapshot(project_path))
        older = subprocess.check_output([
            'git', '-C', str(project_path.parent), 'show', 'HEAD~1:project.json'
        ])
        atomic_write(project_path, older)
        recovered = Project.load(project_path)
        self.assertEqual(recovered.entries[0].japanese, '最初の翻訳')
        self.assertEqual(subprocess.check_output([
            'git','-C',str(project_path.parent),'rev-list','--count','HEAD'
        ],text=True).strip(),'2')

if __name__ == '__main__':
    unittest.main()

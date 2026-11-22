import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from rimworld_translator.core import Entry, Project, export_mod, scan_mod, safe_xml
from rimworld_translator.history import snapshot


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.write('About/About.xml', '<ModMetaData><name>Example</name><packageId>author.example</packageId><supportedVersions><li>1.6</li></supportedVersions></ModMetaData>')
        self.write('Defs/Things.xml', '<Defs><ThingDef><defName>Gun</defName><label>gun</label><description>A &amp; B {0}</description><texPath>secret</texPath><cost>100</cost><tools><li><label>skip</label></li></tools></ThingDef></Defs>')
        self.write('Languages/English/Keyed/Main.xml', '<LanguageData><Hello>Hello {1}</Hello></LanguageData>')
        self.project = Project.create(self.source, scan_mod(self.source))
        self.workspace = self.root / 'project'
        self.path = self.workspace / 'project.json'
    def write(self, rel, text):
        path = self.source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path
    def test_extract_and_partial_export(self):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.rglob('*') if p.is_file()}
        self.assertEqual({e.key for e in self.project.entries}, {'Gun.label', 'Gun.description', 'Gun.tools.0.label', 'Hello'})
        export_mod(self.project, self.workspace / 'mod')
        self.assertTrue((self.workspace / 'mod/About/About.xml').exists())
        self.assertFalse((self.workspace / 'mod/Languages').exists())
        self.project.entries[0].japanese = '銃 <試験> & 弾'
        export_mod(self.project, self.workspace / 'mod')
        root = ET.parse(self.workspace / 'mod/Languages/Japanese/DefInjected/ThingDef/Translations.xml').getroot()
        self.assertEqual(len(root), 1)
        self.assertEqual(root[0].text, '銃 <試験> & 弾')
        about = ET.parse(self.workspace / 'mod/About/About.xml').getroot()
        self.assertEqual(about.findtext('modDependencies/li/packageId'), 'author.example')
        self.assertNotEqual(about.findtext('packageId'), 'author.example')
        self.assertIn('Not affiliated with or endorsed by Ludeon Studios', about.findtext('description'))
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.rglob('*') if p.is_file()})
    def test_rescan_preserves_changed_and_stale(self):
        self.project.entries[0].japanese = '銃'
        self.write('Defs/Things.xml', '<Defs><ThingDef><defName>Gun</defName><label>new gun</label></ThingDef></Defs>')
        self.project.rescan(scan_mod(self.source))
        entry = next(e for e in self.project.entries if e.key == 'Gun.label')
        self.assertEqual(entry.japanese, '銃')
        self.assertEqual(entry.status, 'changed')
        self.assertEqual(entry.previous_english, 'gun')
        self.assertTrue(next(e for e in self.project.entries if e.key == 'Gun.description').stale)
    def test_duplicates_are_blocked(self):
        self.write('Languages/English/Keyed/Other.xml', '<LanguageData><Hello>Other</Hello></LanguageData>')
        project = Project.create(self.source, scan_mod(self.source))
        entry = next(e for e in project.entries if e.key == 'Hello')
        self.assertTrue(entry.blocked)
        entry.japanese = '重複'
        export_mod(project, self.workspace / 'mod')
        self.assertFalse((self.workspace / 'mod/Languages/Japanese/Keyed/Keyed.xml').exists())
    def test_dtd_malformed_and_utf16(self):
        for text in ['<!DOCTYPE Defs [<!ENTITY x "evil">]><Defs/>', '<Defs>']:
            self.write('Defs/Bad.xml', text)
            self.assertTrue(any('Bad.xml' in w for w in scan_mod(self.source).warnings))
        path = self.write('Defs/Bad.xml', '')
        path.write_bytes('<!DOCTYPE Defs><Defs/>'.encode('utf-16'))
        with self.assertRaises(ValueError): safe_xml(path)
    def test_placeholder_blocks_export(self):
        entry = next(e for e in self.project.entries if e.key == 'Hello')
        entry.japanese = 'こんにちは'
        with self.assertRaises(ValueError): export_mod(self.project, self.workspace / 'mod')
        self.assertFalse(self.workspace.exists())
        entry.japanese = 'こんにちは {1}'
        export_mod(self.project, self.workspace / 'mod')
    def test_path_and_symlink_safety(self):
        with self.assertRaises(ValueError): export_mod(self.project, self.source / 'output')
        with self.assertRaises(ValueError): self.project.save(self.source / 'project.json')
        with self.assertRaises(ValueError): export_mod(self.project, self.root / 'steamapps/output')
        link = self.root / 'link'
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError): export_mod(self.project, link / 'output')
        self.write('Defs/Linked.xml', '').unlink()
        (self.source / 'Defs/Linked.xml').symlink_to(self.source / 'Defs/Things.xml')
        self.assertTrue(any('symbolic' in w.lower() for w in scan_mod(self.source).warnings))
    def test_manifest_traversal_and_unowned_output(self):
        self.workspace.mkdir()
        (self.workspace / 'keep.txt').write_text('keep')
        with self.assertRaises(ValueError): export_mod(self.project, self.workspace)
        output = self.workspace / 'mod'
        export_mod(self.project, output)
        marker = output / '.rimworld-translator.json'
        marker.write_text(json.dumps({'package_id': self.project.package_id, 'files': ['../../keep.txt']}))
        with self.assertRaises(ValueError): export_mod(self.project, output)
        self.assertTrue((self.workspace / 'keep.txt').exists())
    def test_atomic_roundtrip_and_history(self):
        self.project.save(self.path)
        self.assertEqual(Project.load(self.path), self.project)
        self.assertTrue(snapshot(self.path))
        stamp = self.path.stat().st_mtime_ns
        self.project.save(self.path)
        self.assertEqual(stamp, self.path.stat().st_mtime_ns)
        self.assertFalse(snapshot(self.path))
        self.project.entries[0].japanese = '銃'
        self.project.save(self.path)
        export_mod(self.project, self.workspace / 'mod')
        self.assertTrue(snapshot(self.path))
        count = subprocess.check_output(['git', '-C', str(self.workspace), 'rev-list', '--count', 'HEAD'], text=True)
        self.assertEqual(count.strip(), '2')
    def test_stale_export_cleanup(self):
        self.project.entries[0].japanese = '銃'
        export_mod(self.project, self.workspace / 'mod')
        self.project.entries[0].japanese = ''
        export_mod(self.project, self.workspace / 'mod')
        self.assertFalse((self.workspace / 'mod/Languages/Japanese/DefInjected/ThingDef/Translations.xml').exists())
    def test_manual_keys_survive_rescan(self):
        manual = Entry('Keyed:Keyed:Manual', 'Keyed', 'Keyed', 'Manual', 'Manual text', '(manual)', '手動訳', review=True)
        self.project.entries.append(manual)
        self.project.rescan(scan_mod(self.source))
        entry = next(e for e in self.project.entries if e.id == manual.id)
        self.assertFalse(entry.stale)
        self.assertEqual(entry.japanese, '手動訳')
    def test_invalid_xml_character(self):
        self.project.entries[0].japanese = 'bad\x00value'
        with self.assertRaises(ValueError): export_mod(self.project, self.workspace / 'mod')
        self.assertFalse(self.workspace.exists())
    def test_export_reports_every_blocking_entry_in_one_pass(self):
        by_key = {e.key: e for e in self.project.entries}
        by_key['Hello'].japanese = 'こんにちは'          # drops {1}
        by_key['Gun.description'].japanese = '銃 {0} と {9}'   # extra {9}
        with self.assertRaises(ValueError) as caught:
            export_mod(self.project, self.workspace / 'mod')
        message = str(caught.exception)
        self.assertIn('Hello', message)
        self.assertIn('Gun.description', message)
        self.assertFalse((self.workspace / 'mod').exists())

    def test_export_symlink_and_git_unrelated_file(self):
        export_mod(self.project, self.workspace / 'mod')
        output = self.workspace / 'mod'
        (output / 'Languages').symlink_to(self.source, target_is_directory=True)
        self.project.entries[0].japanese = '銃'
        with self.assertRaises(ValueError): export_mod(self.project, output)
        (output / 'Languages').unlink()
        (output / 'stray.dll').write_bytes(b'not executable')
        self.project.save(self.path)
        with self.assertRaises(ValueError): snapshot(self.path)
    def test_project_field_types(self):
        self.project.save(self.path)
        data = json.loads(self.path.read_text())
        data['entries'][0]['english'] = 123
        self.path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): Project.load(self.path)
    def test_git_attributes_not_executed(self):
        self.project.save(self.path)
        (self.workspace / '.gitattributes').write_text('project.json filter=unexpected')
        with self.assertRaises(ValueError): snapshot(self.path)
        self.assertFalse((self.workspace / '.git').exists())
    def test_invalid_project_key(self):
        self.project.entries[0].group = '../../escape'
        self.project.save(self.path)
        with self.assertRaises(ValueError): Project.load(self.path)
    def test_unresolved_inheritance_warns_and_empty_patch_has_no_effect(self):
        self.write('Defs/Child.xml', '<Defs><ThingDef ParentName="Base"><defName>Child</defName><label>child</label></ThingDef></Defs>')
        self.write('Patches/Test.xml', '<Patch/>')
        scan = scan_mod(self.source)
        # The Def's own label keeps its key whatever the parent adds (backlog 2: missing prerequisites do not demote P0).
        self.assertFalse(next(e for e in scan.entries if e.key == 'Child.label').review)
        self.assertTrue(any('Unresolved inheritance' in w for w in scan.warnings))

if __name__ == '__main__': unittest.main()

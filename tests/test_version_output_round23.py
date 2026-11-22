"""Keep reusable scan evidence and single-version project state independent."""
import copy
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, Project, Scan, export_mod, export_versions_test, scan_mod

GREETING = 'Keyed:Keyed:Greeting'


class VersionOutputRound23Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.scan = Scan(name='Scan ownership', package_id='test.scanownership',
                         versions=['1.6', '1.10'], warnings=['source warning'],
                         diagnostics=[{'category': 'source', 'evidence': ['origin']}],
                         stats={'active_version': '1.6', 'active_mods': ['test.context']},
                         entries=[Entry(GREETING, 'Keyed', 'Keyed', 'Greeting',
                                        'hello', 'messages.xml', evidence=['source evidence'])])

    def test_create_projects_do_not_share_translation_or_review_with_scan(self):
        before = copy.deepcopy(self.scan)
        first = Project.create(self.source, self.scan)
        second = Project.create(self.source, self.scan)
        first.set_translation(GREETING, '独立した訳')
        first.mark_reviewed(GREETING, approved=True)
        self.assertEqual(self.scan, before)
        self.assertEqual(second.get_translation(GREETING), '')
        self.assertFalse(second.entry_index()[GREETING].approved)

    def test_create_copies_nested_scan_evidence_and_context(self):
        before = copy.deepcopy(self.scan)
        project = Project.create(self.source, self.scan)
        project.entries[0].evidence.append('project evidence')
        project.diagnostics[0]['evidence'].append('project diagnostic')
        project.warnings.append('project warning')
        project.versions.append('2.0')
        project.active_mods.append('test.other')
        self.assertEqual(self.scan, before)

    def test_rescan_does_not_share_new_scan_metadata(self):
        project = Project.create(self.source, copy.deepcopy(self.scan))
        refreshed = copy.deepcopy(self.scan)
        before = copy.deepcopy(refreshed)
        project.rescan(refreshed)
        project.diagnostics[0]['evidence'].append('project diagnostic')
        project.warnings.append('project warning')
        project.versions.append('2.0')
        self.assertEqual(refreshed, before)

    def strings_scan(self, version):
        return Scan(name='Strings ownership', package_id='test.scanownership',
                    versions=['1.6', '1.10'], stats={'active_version': version},
                    entries=[Entry(f'Strings:WordLists/Names.txt:line_{index}',
                                   'Strings', 'WordLists/Names.txt', f'line_{index}',
                                   text, f'{version}/Languages/English/Strings/WordLists/Names.txt')
                             for index, text in enumerate((f'Alpha {version}', f'Beta {version}'))])

    def test_strings_save_restore_and_version_export_preserve_file_and_line_order(self):
        project = Project.create_versions(self.source, {
            version: self.strings_scan(version) for version in ('1.6', '1.10')})
        for version in ('1.6', '1.10'):
            project.switch_version(version)
            for index, text in enumerate((f'甲 {version}', f'乙 {version}')):
                project.set_translation(f'Strings:WordLists/Names.txt:line_{index}', text)
        saved = self.root / 'workspace/project.json'
        project.save(saved)
        restored = Project.load(saved)
        target = self.root / 'output'
        export_versions_test(restored, target)
        for version in ('1.6', '1.10'):
            self.assertEqual((target / version / 'Languages/Japanese/Strings/WordLists/Names.txt')
                             .read_text(encoding='utf-8'), f'甲 {version}\n乙 {version}\n')

    def test_incomplete_strings_file_is_not_published_or_filled_with_source(self):
        project = Project.create(self.source, self.strings_scan('1.6'))
        project.set_translation('Strings:WordLists/Names.txt:line_0', '甲')
        target = self.root / 'output'
        with self.assertRaisesRegex(ValueError, 'Incomplete Strings'):
            export_mod(project, target)
        self.assertFalse(target.exists())

    def test_unsafe_strings_translation_is_excluded_as_whole_file_in_test_export(self):
        project = Project.create_versions(self.source, {
            version: self.strings_scan(version) for version in ('1.6', '1.10')})
        for version in ('1.6', '1.10'):
            project.switch_version(version)
            project.set_translation('Strings:WordLists/Names.txt:line_0', '甲')
            project.set_translation('Strings:WordLists/Names.txt:line_1', '乙\n余分な行')
        target = self.root / 'output'
        warnings = export_versions_test(project, target)
        self.assertTrue(any('Strings' in warning for warning in warnings))
        self.assertEqual(list(target.rglob('*.txt')), [])

    def test_strings_source_change_revokes_only_affected_version_approval(self):
        scans = {version: self.strings_scan(version) for version in ('1.6', '1.10')}
        project = Project.create_versions(self.source, scans)
        identity = 'Strings:WordLists/Names.txt:line_0'
        for version in ('1.6', '1.10'):
            project.switch_version(version)
            project.set_translation(identity, f'訳 {version}')
            project.mark_reviewed(identity, approved=True)
        project.switch_version('1.6')
        refreshed = copy.deepcopy(scans['1.6'])
        refreshed.entries[0].english = 'Updated source'
        project.rescan(refreshed)
        self.assertFalse(project.entry_index()[identity].approved)
        self.assertTrue(project.entry_index()[identity].changed)
        self.assertEqual(project.get_translation(identity), '訳 1.6')
        project.switch_version('1.10')
        self.assertTrue(project.entry_index()[identity].approved)
        self.assertFalse(project.entry_index()[identity].changed)

    def test_partial_strings_file_is_omitted_from_test_export(self):
        project = Project.create_versions(self.source, {
            version: self.strings_scan(version) for version in ('1.6', '1.10')})
        project.set_translation('Strings:WordLists/Names.txt:line_0', '甲')
        target = self.root / 'output'
        warnings = export_versions_test(project, target)
        self.assertTrue(any('Incomplete Strings' in warning for warning in warnings))
        self.assertEqual(list(target.rglob('*.txt')), [])

    def test_strings_unsafe_relative_path_is_rejected_before_writing(self):
        scan = self.strings_scan('1.6')
        scan.entries[0].group = '../../escaped.txt'
        scan.entries[0].id = 'Strings:../../escaped.txt:line_0'
        project = Project.create(self.source, scan)
        project.set_translation(scan.entries[0].id, '甲')
        target = self.root / 'output'
        with self.assertRaisesRegex(ValueError, 'Unsafe Strings'):
            export_mod(project, target)
        self.assertFalse(target.exists())

    def test_removed_strings_lines_keep_history_without_blocking_current_file(self):
        resource = self.source / 'Languages/English/Strings/WordLists/Names.txt'
        resource.parent.mkdir(parents=True)
        resource.write_text('Alpha\nBeta\nGamma\n', encoding='utf-8')
        project = Project.create(self.source, scan_mod(self.source))
        for index, text in enumerate(('甲', '乙', '丙')):
            identity = f'Strings:WordLists/Names.txt:line_{index}'
            project.set_translation(identity, text)
            project.mark_reviewed(identity, approved=True)
        resource.write_text('Alpha\nBeta\n', encoding='utf-8')
        project.rescan(scan_mod(self.source))
        removed = project.entry_index()['Strings:WordLists/Names.txt:line_2']
        self.assertTrue(removed.stale)
        self.assertEqual(removed.japanese, '丙')
        target = self.root / 'output'
        export_mod(project, target)
        output = target / 'Languages/Japanese/Strings/WordLists/Names.txt'
        self.assertEqual(output.read_text(encoding='utf-8'), '甲\n乙\n')
        resource.unlink()
        project.rescan(scan_mod(self.source))
        export_mod(project, target)
        self.assertFalse(output.exists())
        self.assertEqual(len(project.entries), 3)
        self.assertTrue(all(entry.stale for entry in project.entries))


if __name__ == '__main__':
    unittest.main()

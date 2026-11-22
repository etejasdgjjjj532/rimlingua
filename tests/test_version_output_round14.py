"""Protect version-local edits and require review after source changes."""
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Entry, Project, Scan, export_mod, export_versions_test


GREETING = 'Keyed:Keyed:Greeting'


class VersionOutputRound14Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.scans = {version: Scan(
            name='Version safety', package_id='test.versionsafety',
            versions=['1.3', '1.6'], stats={'active_version': version},
            entries=[Entry(GREETING, 'Keyed', 'Keyed', 'Greeting',
                           f'hello {version}', 'messages.xml')]) for version in ('1.3', '1.6')}

    @staticmethod
    def files(root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    def test_switching_versions_before_edit_keeps_translation_in_current_entries(self):
        project = Project.create_versions(self.source, self.scans)
        # Group switches between edits to exercise cache lifetime across many
        # replacement lists, including allocator reuse of a former list address.
        for pause in range(1, 33):
            project.get_translation(GREETING)
            for number in range(pause):
                project.switch_version('1.6' if number % 2 == 0 else '1.3')
            text = f'独立訳 {pause}'
            project.set_translation(GREETING, text)
            self.assertEqual(next(entry for entry in project.entries
                                  if entry.id == GREETING).japanese, text)
            saved = self.root / 'workspace/project.json'
            project.save(saved)
            restored = Project.load(saved)
            self.assertEqual(restored.get_translation(GREETING), text)

    def test_changed_source_blocks_formal_export_until_review_and_preserves_output(self):
        project = Project.create(self.source, copy.deepcopy(self.scans['1.6']))
        project.set_translation(GREETING, '以前の原文の訳')
        project.mark_reviewed(GREETING, approved=True)
        output = self.root / 'formal'
        export_mod(project, output)
        before = self.files(output)
        changed = copy.deepcopy(self.scans['1.6'])
        changed.entries[0].english = 'changed greeting'
        project.rescan(changed)
        saved = self.root / 'workspace/changed.json'
        project.save(saved)
        project = Project.load(saved)
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            export_mod(project, output)
        self.assertEqual(self.files(output), before)
        project.mark_reviewed(GREETING, approved=True)
        export_mod(project, output)
        self.assertEqual(ET.parse(output / 'Languages/Japanese/Keyed/Keyed.xml')
                         .getroot().findtext('Greeting'), '以前の原文の訳')

    def test_source_change_review_is_independent_for_each_language(self):
        project = Project.create(self.source, copy.deepcopy(self.scans['1.6']),
                                 ['Japanese', 'French'])
        for language, text in [('Japanese', '以前の訳'), ('French', 'ancienne traduction')]:
            project.switch_language(language)
            project.set_translation(GREETING, text)
            project.mark_reviewed(GREETING, approved=True)
        changed = copy.deepcopy(self.scans['1.6'])
        changed.entries[0].english = 'changed greeting'
        project.rescan(changed)
        project.mark_reviewed(GREETING, approved=True)
        self.assertFalse(project.entry_index()[GREETING].changed)
        target = self.root / 'multilingual-formal'
        with self.assertRaisesRegex(ValueError, 'Source changed.*Japanese'):
            export_mod(project, target)
        self.assertFalse(target.exists())
        project.switch_language('Japanese')
        project.mark_reviewed(GREETING, approved=True)
        export_mod(project, target)
        self.assertEqual(ET.parse(target / 'Languages/French/Keyed/Keyed.xml')
                         .getroot().findtext('Greeting'), 'ancienne traduction')

    def test_test_export_retains_changed_translation_with_warning_and_other_version(self):
        project = Project.create_versions(self.source, self.scans)
        for version, text in [('1.3', '旧版の訳'), ('1.6', '新版の訳')]:
            project.switch_version(version)
            project.set_translation(GREETING, text)
            project.mark_reviewed(GREETING, approved=True)
        changed = copy.deepcopy(self.scans['1.3'])
        changed.entries[0].english = 'changed old greeting'
        project.add_version_scan('1.3', changed)
        target = self.root / 'test-output'
        warnings = export_versions_test(project, target)
        self.assertTrue(any('1.3' in warning and 'Review needed' in warning
                            for warning in warnings))
        for version, text in [('1.3', '旧版の訳'), ('1.6', '新版の訳')]:
            self.assertEqual(ET.parse(target / version / 'Languages/Japanese/Keyed/Keyed.xml')
                             .getroot().findtext('Greeting'), text)

    def test_formal_export_still_accepts_unchanged_unreviewed_translation(self):
        project = Project.create(self.source, copy.deepcopy(self.scans['1.6']))
        project.set_translation(GREETING, '未承認だが原文変更なし')
        project.entries[0].review = True
        project.entries[0].is_new = True
        target = self.root / 'unchanged-formal'
        export_mod(project, target)
        self.assertEqual(ET.parse(target / 'Languages/Japanese/Keyed/Keyed.xml')
                         .getroot().findtext('Greeting'), '未承認だが原文変更なし')


if __name__ == '__main__':
    unittest.main()

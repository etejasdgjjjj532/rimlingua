"""Recover independent version exports after interrupted publication."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from rimworld_translator import core
from rimworld_translator.core import Entry, Project, Scan, export_versions_test


class VersionOutputRound16Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.versions = ['1.6', '1.7', '1.8', '1.9', '1.10', '2.0']
        self.entry_id = 'Keyed:Keyed:Greeting'
        scans = {version: Scan(name='Version output', package_id='test.versionoutput',
                  versions=self.versions, stats={'active_version': version},
                  entries=[Entry(self.entry_id, 'Keyed', 'Keyed', 'Greeting',
                                 f'hello {version}', 'messages.xml')])
                 for version in self.versions}
        self.project = Project.create_versions(self.source, scans)
        self.target = self.root / 'output'
        self.translate('旧訳')

    def translate(self, prefix):
        for version in self.versions:
            self.project.switch_version(version)
            self.project.set_translation(self.entry_id, f'{prefix} {version}')

    @staticmethod
    def snapshot(root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    def test_staging_write_failure_keeps_previous_all_version_output(self):
        export_versions_test(self.project, self.target)
        (self.target / 'user-note.txt').write_text('keep', encoding='utf-8')
        before = self.snapshot(self.target)
        self.translate('新訳')
        real_write = core.atomic_write
        count = 0

        def fail_second_write(path, data):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('injected staging write failure')
            return real_write(path, data)

        with patch.object(core, 'atomic_write', side_effect=fail_second_write):
            with self.assertRaisesRegex(OSError, 'injected staging'):
                export_versions_test(self.project, self.target)
        self.assertEqual(self.snapshot(self.target), before)
        export_versions_test(self.project, self.target)
        for version in self.versions:
            text = ET.parse(self.target / version / 'Languages/Japanese/Keyed/Keyed.xml').getroot().findtext('Greeting')
            self.assertEqual(text, f'新訳 {version}')

    def test_mid_publication_failure_restores_previous_version_bytes(self):
        export_versions_test(self.project, self.target)
        before = self.snapshot(self.target)
        self.translate('新訳')
        real_replace = core.os.replace
        count = 0

        def fail_second_publication(source, destination):
            nonlocal count
            if self.target in Path(destination).parents:
                count += 1
                if count == 2:
                    raise OSError('injected publication failure')
            return real_replace(source, destination)

        with patch.object(core.os, 'replace', side_effect=fail_second_publication):
            with self.assertRaisesRegex(OSError, 'injected publication'):
                export_versions_test(self.project, self.target)
        self.assertEqual(self.snapshot(self.target), before)

    def test_failed_new_export_does_not_leave_partial_version_tree(self):
        real_replace = core.os.replace
        count = 0

        def fail_second_publication(source, destination):
            nonlocal count
            if self.target in Path(destination).parents:
                count += 1
                if count == 2:
                    raise OSError('injected initial publication failure')
            return real_replace(source, destination)

        with patch.object(core.os, 'replace', side_effect=fail_second_publication):
            with self.assertRaisesRegex(OSError, 'injected initial'):
                export_versions_test(self.project, self.target)
        self.assertFalse(self.target.exists())

    def add_owned_obsolete_file(self):
        obsolete = self.target / '1.6/Languages/Japanese/Keyed/Obsolete.xml'
        obsolete.write_bytes(b'<LanguageData><Old>old</Old></LanguageData>')
        marker = self.target / '.rimworld-translator.json'
        metadata = json.loads(marker.read_text())
        metadata['files'].append(obsolete.relative_to(self.target).as_posix())
        marker.write_text(json.dumps(metadata), encoding='utf-8')
        return obsolete

    def test_manifest_publication_failure_restores_all_version_files(self):
        export_versions_test(self.project, self.target)
        self.add_owned_obsolete_file()
        before = self.snapshot(self.target)
        self.translate('新訳')
        real_replace = core.os.replace
        failed = False

        def fail_marker(source, destination):
            nonlocal failed
            if Path(destination) == self.target / '.rimworld-translator.json' and not failed:
                failed = True
                raise OSError('injected manifest failure')
            return real_replace(source, destination)

        with patch.object(core.os, 'replace', side_effect=fail_marker):
            with self.assertRaisesRegex(OSError, 'injected manifest'):
                export_versions_test(self.project, self.target)
        self.assertEqual(self.snapshot(self.target), before)

    def test_obsolete_deletion_failure_restores_manifest_and_versions(self):
        export_versions_test(self.project, self.target)
        obsolete = self.add_owned_obsolete_file()
        before = self.snapshot(self.target)
        self.translate('新訳')
        real_unlink = Path.unlink
        failed = False

        def fail_obsolete(path, *args, **kwargs):
            nonlocal failed
            if path == obsolete and not failed:
                failed = True
                raise OSError('injected obsolete deletion failure')
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', new=fail_obsolete):
            with self.assertRaisesRegex(OSError, 'injected obsolete'):
                export_versions_test(self.project, self.target)
        self.assertEqual(self.snapshot(self.target), before)
        export_versions_test(self.project, self.target)
        self.assertFalse(obsolete.exists())

    def test_failed_recovery_retains_backup_bytes_and_reports_location(self):
        export_versions_test(self.project, self.target)
        first_relative = '1.6/Languages/Japanese/Keyed/Keyed.xml'
        original = (self.target / first_relative).read_bytes()
        self.translate('新訳')
        real_replace = core.os.replace

        def fail_publication_and_recovery(source, destination):
            source = Path(source)
            destination = Path(destination)
            if destination == self.target / '1.7/Languages/Japanese/Keyed/Keyed.xml':
                raise OSError('injected publication failure')
            if source.parent.name == 'before' and destination == self.target / first_relative:
                raise OSError('injected recovery failure')
            return real_replace(source, destination)

        with patch.object(core.os, 'replace', side_effect=fail_publication_and_recovery):
            with self.assertRaisesRegex(OSError, 'recovery incomplete; backups retained at') as error:
                export_versions_test(self.project, self.target)
        retained = list(self.root.glob('.rimworld-export-*'))
        self.assertEqual(len(retained), 1)
        self.assertIn(str(retained[0]), str(error.exception))
        recovery = json.loads((retained[0] / 'recovery.json').read_text(encoding='utf-8'))
        self.assertEqual(recovery['target'], str(self.target))
        self.assertEqual((retained[0] / recovery['backups'][first_relative]).read_bytes(), original)
        self.assertIsInstance(error.exception.__cause__, OSError)

    def test_unchanged_reexport_does_not_stage_or_change_unowned_files(self):
        export_versions_test(self.project, self.target)
        note = self.target / 'user-note.txt'
        note.write_text('keep', encoding='utf-8')
        before = self.snapshot(self.target)
        with patch.object(core, '_publish_transaction', side_effect=AssertionError('unnecessary staging')):
            export_versions_test(self.project, self.target)
        self.assertEqual(self.snapshot(self.target), before)

    def test_interrupted_recovery_keeps_unrestored_backup(self):
        export_versions_test(self.project, self.target)
        relative = '1.6/Languages/Japanese/Keyed/Keyed.xml'
        original = (self.target / relative).read_bytes()
        self.translate('新訳')
        real_replace = core.os.replace

        def interrupt_recovery(source, destination):
            source, destination = Path(source), Path(destination)
            if destination == self.target / '1.7/Languages/Japanese/Keyed/Keyed.xml':
                raise OSError('injected publication failure')
            if source.parent.name == 'before' and destination == self.target / relative:
                raise KeyboardInterrupt('injected recovery interrupt')
            return real_replace(source, destination)

        with patch.object(core.os, 'replace', side_effect=interrupt_recovery):
            with self.assertRaisesRegex(KeyboardInterrupt, 'injected recovery interrupt'):
                export_versions_test(self.project, self.target)
        retained = list(self.root.glob('.rimworld-export-*'))
        self.assertEqual(len(retained), 1)
        recovery = json.loads((retained[0] / 'recovery.json').read_text(encoding='utf-8'))
        self.assertEqual((retained[0] / recovery['backups'][relative]).read_bytes(), original)

    def test_six_future_versions_keep_independent_saved_state_and_numeric_output(self):
        saved = self.root / 'workspace/project.json'
        self.project.save(saved)
        restored = Project.load(saved)
        for version in reversed(self.versions):
            restored.switch_version(version)
            self.assertEqual(restored.get_translation(self.entry_id), f'旧訳 {version}')
        export_versions_test(restored, self.target)
        about = ET.parse(self.target / 'About/About.xml').getroot()
        self.assertEqual([node.text for node in about.findall('supportedVersions/li')], self.versions)
        folders = ET.parse(self.target / 'LoadFolders.xml').getroot()
        self.assertEqual([(node.tag, node.findtext('li')) for node in folders],
                         [(f'v{version}', version) for version in self.versions])
        for version in self.versions:
            text = ET.parse(self.target / version / 'Languages/Japanese/Keyed/Keyed.xml').getroot().findtext('Greeting')
            self.assertEqual(text, f'旧訳 {version}')
        marker = json.loads((self.target / '.rimworld-translator.json').read_text())
        self.assertTrue(marker['test_only'])
        self.assertEqual(marker['unverified_versions'], self.versions)

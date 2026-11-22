"""Unknown word resources stay diagnostic-only while known strings are refreshed."""
import copy
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Project, export_versions_test, scan_mod
from rimworld_translator.multiversion import scan_declared_versions


class WordInfoRound65Tests(unittest.TestCase):
    def test_rescan_replaces_only_current_diagnostics_and_invalidates_changed_string_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'

            def write(relative, content):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content if isinstance(content, bytes) else content.encode())

            write('About/About.xml', '<ModMetaData><packageId>test.wordinfo65</packageId>'
                  '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
            write('LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6>'
                  '<v1.10><li>1.10</li></v1.10></loadFolders>')
            for version in ('1.6', '1.10'):
                write(f'{version}/Languages/English/Strings/Names/Own.txt', f'Old {version}\n')
                write(f'{version}/Languages/English/WordInfo/Gender/Male.txt', b'unknown\xff')
            scans = scan_declared_versions(source)
            self.assertEqual(scans.failures, {})
            project = Project.create_versions(source, scans.scans)
            entry_id = 'Strings:Names/Own.txt:line_0'
            for version in ('1.6', '1.10'):
                project.switch_version(version)
                project.set_translation(entry_id, f'旧訳 {version}')
                project.mark_reviewed(entry_id, approved=True)
            other_diagnostics = copy.deepcopy(project.diagnostics)
            project.switch_version('1.6')
            (source / '1.6/Languages/English/WordInfo/Gender/Male.txt').unlink()
            write('1.6/Languages/English/WordInfo/Inflections.txt', b'unknown\xff;columns')
            write('1.6/Languages/English/Strings/Names/Own.txt', 'Changed 1.6\n')
            before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
            project.rescan(scan_mod(source, game_version='1.6'))
            self.assertEqual([(d['code'], d['source_file'], d['entry_id'])
                              for d in project.diagnostics if d['code'].startswith('wordinfo-')],
                             [('wordinfo-lut-unverified',
                               '1.6/Languages/English/WordInfo/Inflections.txt', '')])
            current_diagnostics = copy.deepcopy(project.diagnostics)
            entry = project.entry_index()[entry_id]
            self.assertEqual((entry.english, entry.previous_english, entry.japanese),
                             ('Changed 1.6', 'Old 1.6', '旧訳 1.6'))
            self.assertTrue(entry.changed and entry.review)
            self.assertFalse(entry.reviewed or entry.approved)
            saved = root / 'workspace/project.json'
            project.save(saved)
            restored = Project.load(saved)
            for version in ('1.10', '1.6', '1.10'):
                restored.switch_version(version)
                self.assertEqual(restored.diagnostics,
                                 other_diagnostics if version == '1.10' else current_diagnostics)
                self.assertEqual([e.id for e in restored.entries], [entry_id])
                self.assertEqual(restored.entries[0].approved, version == '1.10')
            output = root / 'output'
            export_versions_test(restored, output)
            for version in ('1.6', '1.10'):
                files = [p for p in (output / version / 'Languages/Japanese').rglob('*') if p.is_file()]
                self.assertEqual([p.relative_to(output / version).as_posix() for p in files],
                                 ['Languages/Japanese/Strings/Names/Own.txt'])
                self.assertEqual(files[0].read_bytes(), f'旧訳 {version}\n'.encode())
            self.assertEqual({p: p.read_bytes() for p in source.rglob('*') if p.is_file()}, before)

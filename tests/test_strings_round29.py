"""Strings paths stay portable without renaming source resource identities."""
import os
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, Project, Scan, export_mod, export_versions_test, scan_mod
from rimworld_translator.string_resources import serialize_string_entries, validate_string_entry


class StringsRound29Tests(unittest.TestCase):
    def test_nonportable_components_are_rejected_without_rejecting_similar_names(self):
        reserved = ['CON', 'prn', 'Aux', 'NUL', 'COM1', 'com9', 'LPT1', 'lpt9',
                    'COM¹', 'COM²', 'COM³', 'LPT¹', 'LPT²', 'LPT³', 'CONIN$', 'CONOUT$', 'NUL ']
        unsafe = ['WordLists/Bad' + char + 'Name.txt' for char in '<>"|?*']
        unsafe += ['WordLists' + suffix + '/Names.txt' for suffix in (' ', '.')]
        unsafe += ['WordLists/' + name + '.txt' for name in reserved]
        unsafe += [name + '.data/Names.txt' for name in reserved]
        for group in unsafe:
            with self.subTest(group=group):
                self.assertFalse(validate_string_entry(group, 'line_0'))
                entry = Entry(f'Strings:{group}:line_0', 'Strings', group, 'line_0', 'Alpha', 'source')
                with self.assertRaises(ValueError):
                    serialize_string_entries([entry], {entry.id: '甲'})
        for group in ('WordLists/CONifer.txt', 'WordLists/COM0.txt', 'WordLists/COM10.txt',
                      'WordLists/LPT10.txt', 'WordLists/NULled.txt', 'Word Lists/Names.txt',
                      'WordLists/Names.v2.txt', 'WordLists/CONIN$Extra.txt',
                      'WordLists/CLOCK$.txt', 'WordLists/NUL name.txt', '日本語/名前.txt'):
            with self.subTest(group=group):
                self.assertTrue(validate_string_entry(group, 'line_0'))

    @unittest.skipIf(os.name == 'nt', 'The input fixture intentionally contains a POSIX-only device filename')
    def test_source_diagnostics_and_version_outputs_keep_original_portable_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            context = root / 'context'
            def write(base, relative, text):
                path = base / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')
            write(source, 'About/About.xml', '<ModMetaData><name>Portable Strings</name>'
                  '<packageId>test.portable</packageId><supportedVersions><li>1.6</li>'
                  '<li>1.10</li></supportedVersions></ModMetaData>')
            write(source, 'LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6>'
                  '<v1.10><li>1.10</li></v1.10></loadFolders>')
            for version, english in (('1.6', 'Old'), ('1.10', 'New')):
                write(source, f'{version}/Languages/English/Strings/WordLists/Names.txt', english)
                write(source, f'{version}/Languages/English/Strings/WordLists/NUL.txt', 'Nonportable')
                write(context, f'{version}/Languages/English/Strings/WordLists/Foreign.txt', 'Foreign')
            before = {p: p.read_bytes() for p in root.rglob('*.txt')}
            for cache in (None, root / 'cache.sqlite'):
                scans = {}
                for version, english in (('1.6', 'Old'), ('1.10', 'New')):
                    result = scan_mod(source, game_version=version, context_sources=[context], cache_path=cache)
                    self.assertEqual([(e.group, e.key, e.english, e.source_file) for e in result.entries], [
                        ('WordLists/Names.txt', 'line_0', english,
                         f'{version}/Languages/English/Strings/WordLists/Names.txt')])
                    self.assertTrue(any(d['code'] == 'strings-unsupported' and d['source_file'] ==
                                        f'{version}/Languages/English/Strings/WordLists/NUL.txt'
                                        for d in result.diagnostics))
                    scans[version] = result
                project = Project.create_versions(source, scans)
                for version, japanese in (('1.6', '旧版'), ('1.10', '新版')):
                    project.switch_version(version)
                    project.set_translation('Strings:WordLists/Names.txt:line_0', japanese)
                output = root / ('cached-output' if cache else 'uncached-output')
                export_versions_test(project, output)
                self.assertEqual(sorted(p.relative_to(output).as_posix() for p in output.rglob('*.txt')), [
                    '1.10/Languages/Japanese/Strings/WordLists/Names.txt',
                    '1.6/Languages/Japanese/Strings/WordLists/Names.txt'])
                self.assertEqual((output / '1.6/Languages/Japanese/Strings/WordLists/Names.txt').read_bytes(),
                                 '旧版\n'.encode())
                self.assertEqual((output / '1.10/Languages/Japanese/Strings/WordLists/Names.txt').read_bytes(),
                                 '新版\n'.encode())
            self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_existing_project_with_device_name_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            identity = 'Strings:WordLists/NUL.txt:line_0'
            scan = Scan(name='Existing project', package_id='test.portable', versions=['1.6'], entries=[
                Entry(identity, 'Strings', 'WordLists/NUL.txt', 'line_0', 'Alpha', 'source')])
            project = Project.create(source, scan)
            project.set_translation(identity, '甲')
            output = root / 'output'
            with self.assertRaises(ValueError):
                export_mod(project, output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

"""Strings resource identities require Unicode scalar file paths."""
import os
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Entry, Project, Scan, export_mod, scan_mod
from rimworld_translator.string_resources import validate_string_entry


class StringsRound30Tests(unittest.TestCase):
    def test_surrogate_resource_paths_are_rejected_without_rejecting_unicode_names(self):
        for surrogate in ('\ud800', '\udbff', '\udc00', '\udcff', '\udfff'):
            for group in ('WordLists/Name' + surrogate + '.txt', 'Word' + surrogate + '/Names.txt'):
                with self.subTest(group=group):
                    self.assertFalse(validate_string_entry(group, 'line_0'))
        for group in ('WordLists/Names😀.txt', '日本語/名前.txt', 'WordLists/Café.txt'):
            with self.subTest(group=group):
                self.assertTrue(validate_string_entry(group, 'line_0'))

    @unittest.skipIf(os.name == 'nt', 'The fixture requires a POSIX undecodable byte filename')
    def test_undecodable_source_filename_is_diagnosed_without_extracting_fake_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            strings = source / 'Languages/English/Strings/WordLists'
            strings.mkdir(parents=True)
            invalid = strings / os.fsdecode(b'Names\xff.txt')
            invalid.write_bytes(b'Never portable\n')
            valid = strings / 'Names.txt'
            valid.write_bytes(b'Alpha\n')
            before = {path: path.read_bytes() for path in (invalid, valid)}
            for cache in (None, root / 'cache.sqlite'):
                with self.subTest(cache=cache):
                    result = scan_mod(source, cache_path=cache)
                    self.assertEqual([(entry.id, entry.english) for entry in result.entries],
                                     [('Strings:WordLists/Names.txt:line_0', 'Alpha')])
                    self.assertTrue(any(d['code'] == 'strings-unsupported' and
                                        d['source_file'] == 'Languages/English/Strings/WordLists/Names\udcff.txt'
                                        for d in result.diagnostics))
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_existing_project_with_surrogate_identity_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            group = 'WordLists/Names\udcff.txt'
            identity = f'Strings:{group}:line_0'
            scan = Scan(name='Legacy malformed path', package_id='test.scalar', versions=['1.6'], entries=[
                Entry(identity, 'Strings', group, 'line_0', 'Alpha', 'source')])
            project = Project.create(source, scan)
            project.set_translation(identity, '甲')
            output = root / 'output'
            with self.assertRaisesRegex(ValueError, 'Unsafe Strings entry'):
                export_mod(project, output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

"""Unknown WordInfo stays version-local diagnostic evidence after persistence."""
import copy
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import Project, export_versions_test
from rimworld_translator.multiversion import scan_declared_versions


class WordInfoRound64Tests(unittest.TestCase):
    def test_distinct_version_diagnostics_survive_json_and_complete_strings_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'

            def write(relative, value):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(value if isinstance(value, bytes) else value.encode())

            write('About/About.xml', '<ModMetaData><packageId>test.wordinfo64</packageId>'
                  '<supportedVersions><li>1.10</li><li>1.6</li><li>1.9</li>'
                  '</supportedVersions></ModMetaData>')
            write('LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6>'
                  '<v1.9><li>1.9</li></v1.9><v1.10><li>1.10</li></v1.10></loadFolders>')
            resources = {
                '1.6': ('Gender/Male.txt', 'wordinfo-gender-unsupported'),
                '1.9': ('Inflections.txt', 'wordinfo-lut-unverified'),
                '1.10': ('Custom/Names.txt', 'wordinfo-unsupported'),
            }
            for version, (relative, _) in resources.items():
                write(f'{version}/Languages/English/WordInfo/{relative}', b'unknown\xff;columns')
                write(f'{version}/Languages/English/Strings/Names/Own.txt', f'Own {version}\n')
            before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
            result = scan_declared_versions(source)
            self.assertEqual(result.failures, {})
            self.assertEqual(list(result.scans), ['1.6', '1.9', '1.10'])
            project = Project.create_versions(source, result.scans)
            expected = {}
            for version, (relative, code) in resources.items():
                project.switch_version(version)
                self.assertEqual([(e.id, e.english) for e in project.entries],
                                 [('Strings:Names/Own.txt:line_0', f'Own {version}')])
                own = [d for d in project.diagnostics if d['code'].startswith('wordinfo-')]
                self.assertEqual([(d['code'], d['source_file'], d['entry_id']) for d in own],
                                 [(code, f'{version}/Languages/English/WordInfo/{relative}', '')])
                expected[version] = copy.deepcopy(project.diagnostics)
                project.set_translation('Strings:Names/Own.txt:line_0', f'版 {version}')
            saved = root / 'workspace/project.json'
            project.save(saved)
            restored = Project.load(saved)
            for version in ('1.10', '1.6', '1.9', '1.10'):
                restored.switch_version(version)
                self.assertEqual(restored.diagnostics, expected[version])
                self.assertEqual([e.id for e in restored.entries], ['Strings:Names/Own.txt:line_0'])
            output = root / 'output'
            warnings = export_versions_test(restored, output)
            self.assertEqual(len(warnings), 1)  # Source/game verification remains pending.
            self.assertFalse(any('WordInfo' in message for message in warnings))
            self.assertEqual(sorted(p.relative_to(output).as_posix()
                                    for p in output.rglob('*.txt')),
                             [f'{v}/Languages/Japanese/Strings/Names/Own.txt'
                              for v in ('1.10', '1.6', '1.9')])
            for version in resources:
                self.assertEqual((output / f'{version}/Languages/Japanese/Strings/Names/Own.txt').read_bytes(),
                                 f'版 {version}\n'.encode())
            self.assertFalse(any(p.name == 'WordInfo' for p in output.rglob('*')))
            self.assertEqual({p: p.read_bytes() for p in source.rglob('*') if p.is_file()}, before)


if __name__ == '__main__':
    unittest.main()

"""Static IL provenance must not migrate between persisted version profiles."""
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_versions_test
from rimworld_translator.multiversion import scan_declared_versions
from test_il_round34 import ASSEMBLY


class ILCandidatesRound64Tests(unittest.TestCase):
    def test_target_candidate_broken_dll_and_foreign_dll_remain_separate_after_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, context = root / 'source', root / 'context'

            def write(base, relative, value):
                path = base / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(value if isinstance(value, bytes) else value.encode())

            write(source, 'About/About.xml', '<ModMetaData><packageId>test.il64</packageId>'
                  '<supportedVersions><li>1.10</li><li>1.6</li><li>1.9</li>'
                  '</supportedVersions></ModMetaData>')
            folders = '<loadFolders><v1.6><li>1.6</li></v1.6><v1.9><li>1.9</li></v1.9>'
            folders += '<v1.10><li>1.10</li></v1.10></loadFolders>'
            write(source, 'LoadFolders.xml', folders)
            write(context, 'LoadFolders.xml', folders)
            write(source, '1.6/Assemblies/Own.dll', ASSEMBLY)
            write(source, '1.9/Assemblies/Broken.dll', b'MZ-own-broken')
            write(context, '1.10/Assemblies/Foreign.dll', ASSEMBLY)
            for version in ('1.6', '1.9', '1.10'):
                write(source, f'{version}/Languages/English/Keyed/Own.xml',
                      f'<LanguageData><Own>Own {version}</Own></LanguageData>')
            before = {p: p.read_bytes() for base in (source, context)
                      for p in base.rglob('*') if p.is_file()}
            result = scan_declared_versions(source, contexts={
                v: {'context_sources': [context]} for v in ('1.6', '1.9', '1.10')})
            self.assertEqual(result.failures, {})
            project = Project.create_versions(source, result.scans)
            expected = {}
            for version in ('1.6', '1.9', '1.10'):
                project.switch_version(version)
                self.assertEqual([e.id for e in project.entries], ['Keyed:Keyed:Own'])
                dll = [d for d in project.diagnostics if d['code'].startswith('dll-')]
                if version == '1.6':
                    candidates = [d for d in dll if d['code'] == 'dll-translate-candidate']
                    self.assertEqual(len(candidates), 1)
                    self.assertEqual(candidates[0]['source_file'], '1.6/Assemblies/Own.dll')
                    self.assertIn('Fixture.Direct', candidates[0]['message'])
                    self.assertIn('IL_0005', candidates[0]['message'])
                elif version == '1.9':
                    self.assertEqual([(d['code'], d['source_file']) for d in dll],
                                     [('dll-text', '1.9/Assemblies/Broken.dll'),
                                      ('dll-il-unverified', '1.9/Assemblies/Broken.dll')])
                else:
                    self.assertEqual(dll, [])
                self.assertTrue(all(d['entry_id'] == '' for d in dll))
                expected[version] = copy.deepcopy(project.diagnostics)
                project.set_translation('Keyed:Keyed:Own', f'対象 {version}')
            saved = root / 'workspace/project.json'
            project.save(saved)
            restored = Project.load(saved)
            for version in ('1.10', '1.6', '1.9', '1.6'):
                restored.switch_version(version)
                self.assertEqual(restored.diagnostics, expected[version])
                self.assertEqual([e.id for e in restored.entries], ['Keyed:Keyed:Own'])
            output = root / 'output'
            warnings = export_versions_test(restored, output)
            self.assertEqual(len(warnings), 1)
            self.assertFalse(any('.dll' in message or 'Direct' in message for message in warnings))
            self.assertFalse(list(output.rglob('*.dll')))
            for version in ('1.6', '1.9', '1.10'):
                language = output / f'{version}/Languages/Japanese'
                self.assertEqual([p.relative_to(language).as_posix() for p in language.rglob('*')
                                  if p.is_file()], ['Keyed/Keyed.xml'])
                xml = ET.parse(language / 'Keyed/Keyed.xml').getroot()
                self.assertEqual([(e.tag, e.text) for e in xml], [('Own', f'対象 {version}')])
            self.assertEqual({p: p.read_bytes() for base in (source, context)
                              for p in base.rglob('*') if p.is_file()}, before)


if __name__ == '__main__':
    unittest.main()

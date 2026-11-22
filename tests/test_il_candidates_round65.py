"""Refreshing a broken target DLL cannot borrow another version's IL evidence."""
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Project, export_versions_test, scan_mod
from rimworld_translator.multiversion import scan_declared_versions
from test_il_round34 import ASSEMBLY


class ILCandidatesRound65Tests(unittest.TestCase):
    def test_rescan_replaces_candidate_with_unverified_diagnostic_without_touching_other_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'

            def write(relative, content):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content if isinstance(content, bytes) else content.encode())

            write('About/About.xml', '<ModMetaData><packageId>test.il65</packageId>'
                  '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
            write('LoadFolders.xml', '<loadFolders><v1.6><li>1.6</li></v1.6>'
                  '<v1.10><li>1.10</li></v1.10></loadFolders>')
            for version in ('1.6', '1.10'):
                write(f'{version}/Assemblies/Own.dll', ASSEMBLY)
                write(f'{version}/Languages/English/Keyed/Own.xml',
                      f'<LanguageData><Own>Owned {version}</Own></LanguageData>')
            scans = scan_declared_versions(source)
            self.assertEqual(scans.failures, {})
            project = Project.create_versions(source, scans.scans)
            for version in ('1.6', '1.10'):
                project.switch_version(version)
                project.set_translation('Keyed:Keyed:Own', f'対象 {version}')
            other_diagnostics = copy.deepcopy(project.diagnostics)
            project.switch_version('1.6')
            self.assertEqual(len([d for d in project.diagnostics
                                  if d['code'] == 'dll-translate-candidate']), 1)
            write('1.6/Assemblies/Own.dll', b'MZ-broken-after-refresh')
            before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
            project.rescan(scan_mod(source, game_version='1.6'))
            current_diagnostics = copy.deepcopy(project.diagnostics)
            self.assertEqual([(d['code'], d['source_file'], d['entry_id'])
                              for d in project.diagnostics if d['code'].startswith('dll-')],
                             [('dll-text', '1.6/Assemblies/Own.dll', ''),
                              ('dll-il-unverified', '1.6/Assemblies/Own.dll', '')])
            saved = root / 'workspace/project.json'
            project.save(saved)
            restored = Project.load(saved)
            for version in ('1.10', '1.6', '1.10'):
                restored.switch_version(version)
                self.assertEqual(restored.diagnostics,
                                 other_diagnostics if version == '1.10' else current_diagnostics)
                self.assertEqual([e.id for e in restored.entries], ['Keyed:Keyed:Own'])
            output = root / 'output'
            export_versions_test(restored, output)
            self.assertFalse(list(output.rglob('*.dll')))
            for version in ('1.6', '1.10'):
                language = output / version / 'Languages/Japanese'
                files = [p for p in language.rglob('*') if p.is_file()]
                self.assertEqual([p.relative_to(language).as_posix() for p in files], ['Keyed/Keyed.xml'])
                self.assertEqual([(e.tag, e.text) for e in ET.parse(files[0]).getroot()],
                                 [('Own', f'対象 {version}')])
            self.assertEqual({p: p.read_bytes() for p in source.rglob('*') if p.is_file()}, before)

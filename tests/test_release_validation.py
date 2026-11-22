"""Release archives cannot claim native validation from Wine or stale reports."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.builder = importlib.import_module('tools.build_portable')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'dist'
        self.bundle = self.output / 'RimWorldTranslationEditor'
        self.bundle.mkdir(parents=True)
        self.executable = self.bundle / 'RimWorldTranslationEditor.exe'
        self.executable.write_bytes(b'synthetic PE file for archive validation')
        self.manifest = {'application': 'rimworld-translation-editor', 'platform': 'windows',
                         'version': '0.3.0', 'architecture': 'x86_64', 'runtime': 'windows',
                         'wine': False, 'native_windows_verified': False, 'gui_verified': False,
                         'self_test': {'ok': True, 'frozen': True}}
        self.write_manifest()

    def write_manifest(self):
        (self.bundle / 'release-manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def gui_reports(self, *, wine=False, native=True):
        reports = []
        for scale in ('1', '2'):
            report = {'version': '0.3.0', 'os': 'win32', 'qt_backend': 'windows', 'wine': wine,
                      'native': native, 'frozen': True, 'ok': True, 'scale_factor': scale,
                      'executable_sha256': self.builder.sha256_file(self.executable),
                      'save_verified': True, 'export_verified': True, 'history_verified': True,
                      'compact_save_shortcut_verified': True, 'keyboard_tab_moves_focus': True,
                      'initial_window_fits_screen': True, 'issues': []}
            path = self.root / f'gui-scale-{scale}.json'
            path.write_text(json.dumps(report), encoding='utf-8')
            reports.append(path)
        return reports

    def test_native_windows_archive_is_only_marked_after_both_matching_gui_reports(self):
        result = self.builder.finalize(self.output, self.gui_reports())
        self.assertTrue(result['native_windows_verified'])
        self.assertTrue(result['gui_verified'])
        self.assertEqual(result['validation_scope'], 'native-gui')
        self.assertTrue(Path(result['archive']).is_file())

    def test_missing_second_scale_cannot_finalize_release(self):
        with self.assertRaisesRegex(ValueError, '100%.*200%'):
            self.builder.finalize(self.output, self.gui_reports()[:1])
        self.assertFalse(json.loads((self.bundle / 'release-manifest.json').read_text())['gui_verified'])

    def test_gui_report_for_another_executable_is_rejected(self):
        reports = self.gui_reports()
        data = json.loads(reports[0].read_text())
        data['executable_sha256'] = '0' * 64
        reports[0].write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'executable'):
            self.builder.finalize(self.output, reports)

    def test_wine_cannot_finalize_a_native_windows_release(self):
        with self.assertRaisesRegex(ValueError, 'native|Wine'):
            self.builder.finalize(self.output, self.gui_reports(wine=True, native=False))

    def test_explicit_wine_preview_has_no_native_windows_claim(self):
        self.manifest.update(runtime='wine', wine=True)
        self.write_manifest()
        result = self.builder.finalize(self.output, self.gui_reports(wine=True, native=False), allow_wine=True)
        self.assertFalse(result['native_windows_verified'])
        self.assertFalse(result['gui_verified'])
        self.assertTrue(result['supplementary_gui_verified'])
        self.assertEqual(result['validation_scope'], 'wine-supplementary')
        self.assertIn('wine-preview', Path(result['archive']).name)

    def test_wine_build_requires_explicit_opt_in_even_for_dry_run(self):
        evidence = {'os': 'win32', 'runtime': 'wine', 'wine': True, 'native_os': False, 'native_gui': False}
        with patch.object(self.builder, 'native_platform', return_value='windows'), patch.object(self.builder, 'runtime_evidence', return_value=evidence, create=True):
            with self.assertRaisesRegex(ValueError, 'Wine'):
                self.builder.build(ROOT, self.root / 'preview', self.root / 'work', dry_run=True, target='windows')
            plan = self.builder.build(ROOT, self.root / 'preview', self.root / 'work', dry_run=True, target='windows', allow_wine=True)
            self.assertTrue(plan['wine'])

    def test_runtime_self_test_alone_does_not_mark_windows_gui_verified(self):
        output = self.root / 'unverified'
        work = self.root / 'work'
        evidence = {'os': 'win32', 'runtime': 'windows', 'wine': False,
                    'native_os': True, 'native_gui': False}
        def process(command, **kwargs):
            if 'PyInstaller' in command:
                bundle = output / 'RimWorldTranslationEditor'
                bundle.mkdir(parents=True)
                (bundle / 'RimWorldTranslationEditor.exe').write_bytes(b'synthetic executable')
            elif '--self-test' in command:
                Path(command[-1]).write_text(json.dumps({'frozen': True, 'ok': True}), encoding='utf-8')
            else:
                raise AssertionError(f'Unexpected process in build fixture: {command}')
        with patch.object(self.builder, 'native_platform', return_value='windows'), patch.object(self.builder, 'runtime_evidence', return_value=evidence), patch.object(self.builder.subprocess, 'run', side_effect=process), patch.object(self.builder, 'collect_licenses', return_value=[]), patch.object(self.builder.platform, 'platform', return_value='Windows-test'):
            result = self.builder.build(ROOT, output, work, target='windows')
        self.assertFalse(result['native_windows_verified'])
        self.assertFalse(result['gui_verified'])
        self.assertEqual(result['validation_scope'], 'runtime-self-test')


if __name__ == '__main__':
    unittest.main()

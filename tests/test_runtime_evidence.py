"""Wine, native OS and GUI evidence must remain separate."""
import importlib
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace


class RuntimeEvidenceTests(unittest.TestCase):
    def runtime(self, system, backend, *, version=None, environment=None):
        module = importlib.import_module('rimworld_translator.runtime')
        with patch.object(module.sys, 'platform', system), patch.object(module, '_wine_version', return_value=version), patch.dict(os.environ, environment or {}, clear=True):
            return module.runtime_evidence(backend)

    def test_wine_export_prevents_native_windows_claim_without_environment_markers(self):
        result = self.runtime('win32', 'windows', version='11.17')
        self.assertTrue(result['wine'])
        self.assertEqual(result['wine_version'],'11.17')
        self.assertEqual(result['runtime'], 'wine')
        self.assertFalse(result['native_os'])
        self.assertFalse(result['native_gui'])

    def test_wine_environment_marker_prevents_native_windows_claim(self):
        result = self.runtime('win32', 'windows', environment={'WINEPREFIX': 'disposable-prefix'})
        self.assertTrue(result['wine'])
        self.assertFalse(result['native_gui'])
        self.assertNotIn('disposable-prefix', str(result))

    def test_native_windows_runtime_without_gui_is_not_gui_verification(self):
        result = self.runtime('win32', None)
        self.assertTrue(result['native_os'])
        self.assertFalse(result['native_gui'])

    def test_windows_gui_requires_windows_platform_plugin(self):
        self.assertTrue(self.runtime('win32', 'windows')['native_gui'])
        self.assertFalse(self.runtime('win32', 'offscreen')['native_gui'])

    def test_linux_native_gui_and_offscreen_are_distinguished(self):
        self.assertTrue(self.runtime('linux', 'wayland')['native_gui'])
        self.assertTrue(self.runtime('linux', 'xcb')['native_gui'])
        self.assertFalse(self.runtime('linux', 'offscreen')['native_gui'])

    def test_windows_server_gui_is_not_windows_10_or_11_client_evidence(self):
        module = importlib.import_module('rimworld_translator.runtime')
        version = SimpleNamespace(major=10, minor=0, build=26100, product_type=3, platform_version=(10,0,26100))
        with patch.object(module.sys,'getwindowsversion',return_value=version,create=True):
            result = self.runtime('win32','windows')
        self.assertTrue(result['native_gui'])
        self.assertEqual(result['windows_product_type'],3)
        self.assertFalse(result['native_windows_client_gui'])

    def test_real_windows_11_client_gui_has_explicit_client_evidence(self):
        module = importlib.import_module('rimworld_translator.runtime')
        version = SimpleNamespace(major=10, minor=0, build=26100, product_type=1, platform_version=(10,0,26100))
        with patch.object(module.sys,'getwindowsversion',return_value=version,create=True):
            result = self.runtime('win32','windows')
        self.assertEqual(result['windows_name'],'Windows 11')
        self.assertTrue(result['native_windows_client_gui'])


if __name__ == '__main__':
    unittest.main()

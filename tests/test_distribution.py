"""Portable packaging and opt-in update boundary regression tests."""
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_gui_diagnostics_preserve_unicode_on_legacy_windows_stdout(self):
        verifier = importlib.import_module('tools.verify_native_gui')
        result = {'ok': True, 'accessibility': {'translation': '日本語の訳 / français'}}
        buffer = io.BytesIO()
        stdout = io.TextIOWrapper(buffer, encoding='cp1252')
        with patch.object(verifier, 'run_smoke', return_value=result), patch.object(verifier.sys, 'stdout', stdout):
            self.assertEqual(verifier.main(['--output', 'unused-synthetic-output']), 0)
        stdout.flush()
        self.assertEqual(json.loads(buffer.getvalue().decode('cp1252')), result)

    def module(self, name):
        path = ROOT / (name.replace(".", "/") + ".py")
        self.assertTrue(path.is_file(), f"Distribution implementation missing: {path}")
        return importlib.import_module(name)

    def test_build_dry_run_uses_native_host_without_mod_inputs(self):
        self.module("tools.build_portable")
        from rimworld_translator.runtime import runtime_evidence
        arguments = ['--dry-run']
        if runtime_evidence()['wine']:
            arguments.append('--allow-wine')
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/build_portable.py"), *arguments],
            capture_output=True, text=True, check=True, cwd=ROOT,
        )
        plan = json.loads(result.stdout)
        self.assertEqual(plan["platform"], "windows" if sys.platform == "win32" else "linux")
        self.assertEqual(plan["version"], "0.4.0")
        self.assertEqual(Path(plan["root"]), ROOT)
        self.assertEqual(Path(plan['command'][-1]).parts[-2:], ('packaging', 'portable.spec'))
        self.assertNotIn("steamapps", json.dumps(plan).lower())

    def test_build_rejects_cross_os_target(self):
        self.module("tools.build_portable")
        other = "linux" if sys.platform == "win32" else "windows"
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/build_portable.py"), "--dry-run", "--target", other],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("native", result.stderr.lower())

    def test_build_refuses_source_mod_as_build_root(self):
        builder = self.module("tools.build_portable")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "About").mkdir()
            (root / "About/About.xml").write_text("<ModMetaData/>")
            with self.assertRaises(ValueError):
                builder.validate_root(root)

    def test_bundle_validation_rejects_game_data_and_project_files(self):
        builder = self.module("tools.build_portable")
        for name in ("About/About.xml", "Defs/Things.xml", "project.json", "Assembly-CSharp.dll"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"must not redistribute")
                with self.assertRaises(ValueError):
                    builder.validate_bundle(root)

    def test_linux_archive_preserves_contents_and_checksum(self):
        builder = self.module("tools.build_portable")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / "RimWorldTranslationEditor"
            bundle.mkdir()
            (bundle / "RimWorldTranslationEditor").write_bytes(b"synthetic executable")
            archive = builder.create_archive(bundle, root, "linux", "x86_64")
            with tarfile.open(archive) as stream:
                content = stream.extractfile("RimWorldTranslationEditor/RimWorldTranslationEditor").read()
            self.assertEqual(content, b"synthetic executable")
            self.assertEqual(builder.sha256_file(archive), hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_build_does_not_overwrite_translation_work_in_existing_output(self):
        builder = self.module("tools.build_portable")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / "dist/RimWorldTranslationEditor"
            bundle.mkdir(parents=True)
            project = bundle / "project.json"
            project.write_text('{"user_translation": true}')
            with self.assertRaises(ValueError):
                builder.build(ROOT, root / "dist", root / "work", dry_run=True)
            self.assertEqual(project.read_text(), '{"user_translation": true}')

    def test_licenses_include_python_qt_and_flag_terms(self):
        builder = self.module("tools.build_portable")
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder)
            builder.collect_licenses(bundle, ROOT)
            self.assertTrue((bundle / "licenses/Python-LICENSE.txt").is_file())
            self.assertTrue((bundle / "licenses/qt/LGPL-3.0-only.txt").is_file())
            self.assertTrue((bundle / "licenses/flag-icons-MIT.txt").is_file())
            self.assertIn("Mozilla Public License", (bundle / "licenses/RimWorldTranslationEditor-MPL-2.0.txt").read_text(encoding="utf-8"))

    def test_gui_smoke_records_geometry_accessibility_and_dpi_screenshots(self):
        self.module("tools.verify_native_gui")
        with tempfile.TemporaryDirectory() as folder:
            for scale in ("1", "2"):
                environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=scale)
                output = Path(folder) / scale
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tools/verify_native_gui.py"), "--output", str(output)],
                    cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                report = json.loads((output / "gui-report.json").read_text())
                self.assertTrue(report["ok"], report)
                self.assertTrue(report.get("save_verified"), report)
                self.assertTrue(report.get("export_verified"), report)
                self.assertTrue(report.get('history_verified'),report)
                self.assertFalse(report["native"])
                self.assertGreaterEqual(report["device_pixel_ratio"], float(scale))
                self.assertTrue(report["accessibility"]["search"]["name"])
                self.assertTrue(report["accessibility"]["translation"]["name"])
                self.assertEqual(len(report["screenshots"]), 3)
                for shot in report["screenshots"]:
                    self.assertTrue(shot['table_selection_verified'], shot)
                    self.assertTrue((output / shot["file"]).is_file())
                    self.assertGreater(shot["pixel_width"], 0)


class UpdateTests(unittest.TestCase):
    def module(self):
        path = ROOT / "rimworld_translator/updates.py"
        self.assertTrue(path.is_file(), "Opt-in update implementation missing")
        return importlib.import_module("rimworld_translator.updates")

    @staticmethod
    def response(payload):
        return lambda request, timeout: io.BytesIO(json.dumps(payload).encode())

    @staticmethod
    def no_network(request, timeout):
        raise AssertionError("Network access must remain opt-in")

    def test_updates_are_off_by_default_even_with_a_repository(self):
        updates = self.module()
        result = updates.check_for_update("example/editor", opener=self.no_network)
        self.assertEqual(result.status, "disabled")

    def test_unconfigured_release_repository_does_not_contact_network(self):
        updates = self.module()
        result = updates.check_for_update(enabled=True, opener=self.no_network)
        self.assertEqual(result.status, "unconfigured")

    def test_newer_stable_release_returns_configured_repository_link(self):
        updates = self.module()
        payload = {"tag_name": "v0.10.0", "draft": False, "prerelease": False,
                   "html_url": "https://github.com/example/editor/releases/tag/v0.10.0"}
        result = updates.check_for_update("example/editor", enabled=True,
                                          current_version="0.3.0", opener=self.response(payload))
        self.assertEqual(result.status, "available")
        self.assertEqual(result.latest_version, "0.10.0")
        self.assertEqual(result.release_url, payload["html_url"])

    def test_pre_release_does_not_offer_stable_users_an_upgrade(self):
        updates = self.module()
        payload = {"tag_name": "v0.4.0-rc.1", "draft": False, "prerelease": True,
                   "html_url": "https://github.com/example/editor/releases/tag/v0.4.0-rc.1"}
        result = updates.check_for_update("example/editor", enabled=True, opener=self.response(payload))
        self.assertEqual(result.status, "current")

    def test_current_or_older_stable_version_is_not_an_upgrade(self):
        updates = self.module()
        for tag in ("v0.3.0", "v0.2.99"):
            with self.subTest(tag=tag):
                payload = {"tag_name": tag, "draft": False, "prerelease": False,
                           "html_url": f"https://github.com/example/editor/releases/tag/{tag}"}
                result = updates.check_for_update("example/editor", enabled=True,
                                                  opener=self.response(payload))
                self.assertEqual(result.status, "current")

    def test_foreign_release_link_is_not_offered_as_upgrade(self):
        updates = self.module()
        payload = {"tag_name": "v1.0.0", "draft": False, "prerelease": False,
                   "html_url": "https://github.com/another/editor/releases/tag/v1.0.0"}
        result = updates.check_for_update("example/editor", enabled=True, opener=self.response(payload))
        self.assertEqual(result.status, "error")
        self.assertEqual(result.release_url, "")

    def test_network_failure_returns_a_nonfatal_result(self):
        updates = self.module()
        def unavailable(request, timeout):
            raise OSError("offline")
        result = updates.check_for_update("example/editor", enabled=True, opener=unavailable)
        self.assertEqual(result.status, "error")
        self.assertTrue(result.message)


if __name__ == "__main__":
    unittest.main()

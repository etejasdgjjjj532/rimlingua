"""Disposable game tests: copies/config isolation and a real synthetic process."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.game_testing import launch_game_test, prepare_game_test
from rimworld_translator.platforms import GameInstallation
from test_installation import write_mod


class GameTestingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "game original"
        write_mod(self.game / "Data/Core", "ludeon.rimworld")
        (self.game / "Mods").mkdir()
        (self.game / "Mods/user_notes.txt").write_text("keep original")
        executable = self.game / ("RimWorldWin64.exe" if os.name == "nt" else "RimWorldLinux")
        shutil.copy2(sys.executable, executable)
        self.installation = GameInstallation(self.game, self.game / "Mods", None, "1.6.4871", executable,
                                             "win32" if os.name == "nt" else "linux")
        self.source = write_mod(self.root / "Workshop read only/1234567890", "author.original")
        self.generated = write_mod(self.root / "output/mod", "local.translation.test", ["author.original"],
                                   ["author.original"], "translated", True)

    def prepare(self, name="isolated"):
        return prepare_game_test(self.installation, self.generated, self.root / name, source_mods=[self.source])

    def test_prepare_copies_game_and_source_without_user_mods_or_config_edits(self):
        original = (self.source / "About/About.xml").read_bytes()
        plan = self.prepare()
        self.assertNotEqual(plan.executable, self.installation.executable)
        self.assertTrue(plan.executable.is_file())
        self.assertFalse((plan.game / "Mods/user_notes.txt").exists())
        self.assertEqual((self.game / "Mods/user_notes.txt").read_text(), "keep original")
        copied_sources = list((plan.game / "Mods").glob("source-*/About/About.xml"))
        self.assertEqual(len(copied_sources), 1)
        copied_sources[0].write_text("changed in test only")
        self.assertEqual((self.source / "About/About.xml").read_bytes(), original)
        config = (plan.savedata / "Config/ModsConfig.xml").read_text()
        self.assertIn("ludeon.rimworld", config)
        self.assertLess(config.index("author.original"), config.index("local.translation.test"))
        prefs = (plan.savedata / "Config/Prefs.xml").read_text()
        self.assertIn("Japanese", prefs)
        self.assertIn("-savedatafolder=" + str(plan.savedata), plan.argv)
        self.assertEqual(plan.argv[plan.argv.index("-logFile") + 1], str(plan.player_log))

    def test_existing_user_output_and_source_overlap_refused(self):
        destination = self.root / "existing"
        destination.mkdir()
        (destination / "keep.txt").write_text("keep")
        with self.assertRaises(ValueError):
            prepare_game_test(self.installation, self.generated, destination, source_mods=[self.source])
        self.assertEqual((destination / "keep.txt").read_text(), "keep")
        with self.assertRaises(ValueError):
            prepare_game_test(self.installation, self.generated, self.source / "test", source_mods=[self.source])

    def test_missing_executable_refused_before_copy(self):
        (self.game / self.installation.executable.name).unlink()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.root / "isolated").exists())

    def test_real_process_collects_isolated_log_and_report_without_display_claim(self):
        plan = self.prepare()
        script = (
            "import pathlib,sys; a=sys.argv; "
            "log=pathlib.Path(a[a.index('-logFile')+1]); "
            "saved=next(x.split('=',1)[1] for x in a if x.startswith('-savedatafolder=')); "
            "log.write_text('RimWorld 1.6.4871\\nSave data folder overridden to '+saved+'\\nTranslation loaded\\n'); "
            "print('synthetic game stdout')"
        )
        plan = replace(plan, argv=(str(plan.executable), "-c", script, *plan.argv[1:]))
        report = launch_game_test(plan, timeout=5)
        self.assertTrue(report.process_started)
        self.assertEqual(report.process_exit_code, 0)
        self.assertFalse(report.display_verified)
        self.assertFalse(report.timed_out)
        self.assertTrue(report.game_version_loaded)
        self.assertTrue(report.isolated_savedatafolder_confirmed)
        self.assertIn("synthetic game stdout", plan.stdout_log.read_text())
        stored = json.loads(plan.report_path.read_text())
        self.assertFalse(stored["display_verified"])
        self.assertEqual(stored["process_exit_code"], 0)

    def test_timeout_and_cancel_stop_child_process_and_record_reason(self):
        first = self.prepare("timeout")
        first = replace(first, argv=(str(first.executable), "-c", "import time;time.sleep(30)", *first.argv[1:]))
        timed = launch_game_test(first, timeout=0.15)
        self.assertTrue(timed.timed_out)
        self.assertFalse(timed.cancelled)
        self.assertIsNotNone(timed.process_exit_code)
        second = self.prepare("cancel")
        second = replace(second, argv=(str(second.executable), "-c", "import time;time.sleep(30)", *second.argv[1:]))
        event = threading.Event()
        timer = threading.Timer(0.15, event.set)
        timer.start()
        self.addCleanup(timer.cancel)
        cancelled = launch_game_test(second, timeout=5, cancel=event)
        self.assertTrue(cancelled.cancelled)
        self.assertFalse(cancelled.timed_out)
        self.assertIsNotNone(cancelled.process_exit_code)

    def test_cancel_before_launch_and_missing_binary_create_failed_reports(self):
        plan = self.prepare()
        event = threading.Event()
        event.set()
        report = launch_game_test(plan, cancel=event)
        self.assertTrue(report.cancelled)
        self.assertFalse(report.process_started)
        plan.executable.unlink()
        failed = launch_game_test(plan)
        self.assertFalse(failed.process_started)
        self.assertTrue(failed.launch_error)
        self.assertTrue(plan.report_path.is_file())

    def test_disabled_isolation_args_refused_before_process_starts(self):
        plan = self.prepare()
        unsafe = replace(plan, argv=(str(plan.executable),))
        with self.assertRaises(ValueError):
            launch_game_test(unsafe)

    def test_retry_never_uses_previous_run_logs_as_new_evidence(self):
        plan = self.prepare()
        script = "import pathlib,sys;pathlib.Path(sys.argv[sys.argv.index('-logFile')+1]).write_text('RimWorld 1.6.4871\\n')"
        plan = replace(plan, argv=(str(plan.executable), "-c", script, *plan.argv[1:]))
        first = launch_game_test(plan, timeout=5)
        self.assertTrue(first.game_version_loaded)
        plan.executable.unlink()
        failed = launch_game_test(plan)
        self.assertFalse(failed.game_version_loaded)
        self.assertTrue(failed.launch_error)
        previous = list((plan.root / "previous-runs").glob("*/Player.log"))
        self.assertEqual(len(previous), 1)
        self.assertIn("RimWorld 1.6.4871", previous[0].read_text())

    def test_dependency_order_includes_official_dlc_and_copied_framework(self):
        write_mod(self.game / "Data/Royalty", "ludeon.rimworld.royalty", ["ludeon.rimworld"])
        write_mod(self.source, "author.original", ["author.framework", "ludeon.rimworld.royalty"])
        framework = write_mod(self.root / "framework", "author.framework")
        plan = prepare_game_test(self.installation, self.generated, self.root / "isolated",
                                 source_mods=[self.source, framework])
        active = plan.active_packages
        self.assertLess(active.index("ludeon.rimworld"), active.index("ludeon.rimworld.royalty"))
        self.assertLess(active.index("author.framework"), active.index("author.original"))
        self.assertLess(active.index("ludeon.rimworld.royalty"), active.index("author.original"))
        self.assertLess(active.index("author.original"), active.index("local.translation.test"))
        self.assertFalse(plan.diagnostics)

    def test_optional_screenshot_is_retained_without_automatic_display_claim(self):
        plan = self.prepare()
        image = self.root / "captured.png"
        image.write_bytes(b"synthetic image bytes")
        event = threading.Event()
        event.set()
        report = launch_game_test(plan, cancel=event, screenshot_paths=[image])
        self.assertEqual(len(report.screenshots), 1)
        self.assertEqual(report.screenshots[0].read_bytes(), image.read_bytes())
        self.assertFalse(report.display_verified)

    def test_official_archive_name_is_used_for_prefs_but_export_id_is_unchanged(self):
        archive = self.game / "Data/Core/Languages/Japanese (日本語).tar"
        archive.write_bytes(b"language archive fixture")
        before = (self.generated / "Languages/Japanese/Keyed/Main.xml").read_bytes()
        plan = self.prepare()
        prefs = ET.parse(plan.savedata / "Config/Prefs.xml").getroot()
        self.assertEqual(prefs.findtext("langFolderName"), "Japanese (日本語)")
        self.assertEqual(plan.language, "Japanese")
        self.assertEqual(plan.language_folder_name, "Japanese (日本語)")
        self.assertEqual((self.generated / "Languages/Japanese/Keyed/Main.xml").read_bytes(), before)
        self.assertTrue((plan.game / "Mods/translation-local.translation.test/Languages/Japanese/Keyed/Main.xml").is_file())
        event = threading.Event()
        event.set()
        report = launch_game_test(plan, cancel=event)
        self.assertFalse(report.display_verified)
        self.assertEqual(report.requested_language, "Japanese")
        self.assertEqual(report.configured_language_folder, "Japanese (日本語)")

    def test_plain_legacy_language_folder_keeps_its_exact_name(self):
        plan = self.prepare()
        prefs = ET.parse(plan.savedata / "Config/Prefs.xml").getroot()
        self.assertEqual(prefs.findtext("langFolderName"), "Japanese")
        self.assertEqual(plan.language_folder_name, "Japanese")

    def test_native_custom_language_directory_is_resolved_and_missing_pack_is_rejected(self):
        native = self.game / "Data/Core/Languages/CommunityLang (Community)"
        native.mkdir()
        plan = prepare_game_test(self.installation, self.generated, self.root / "custom-language",
                                 source_mods=[self.source], language="CommunityLang")
        prefs = ET.parse(plan.savedata / "Config/Prefs.xml").getroot()
        self.assertEqual(prefs.findtext("langFolderName"), "CommunityLang (Community)")
        with self.assertRaisesRegex(ValueError, "MissingLang"):
            prepare_game_test(self.installation, self.generated, self.root / "missing-language",
                              source_mods=[self.source], language="MissingLang")
        self.assertFalse((self.root / "missing-language").exists())


if __name__ == "__main__":
    unittest.main()

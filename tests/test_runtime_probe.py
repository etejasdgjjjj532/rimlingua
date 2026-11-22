"""Independent evidence classification for the opt-in real-game probe."""
from pathlib import Path
import tempfile
import unittest

from PySide6.QtGui import QImage

from tools.verify_runtime_ui import evaluate_evidence, select_label
from rimworld_translator.core import Entry, Scan


class RuntimeProofTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.image = self.root / "frame.png"
        frame = QImage(1024, 768, QImage.Format.Format_RGB32)
        frame.fill(0xffffffff)
        self.assertTrue(frame.save(str(self.image), "PNG"))
        self.expected = [{"source_id": "123", "def_name": "TestGun", "expected": "SOLPROOF01 翻訳装備"}]
        self.observed = {"schema": 1, "rendered_frames": 30, "screenshot_requested": True,
                         "observations": [{**self.expected[0], "found": True,
                                           "actual": self.expected[0]["expected"], "injection_match": True}]}

    def test_ocr_and_actual_loaded_value_are_independently_required(self):
        report = evaluate_evidence(self.expected, self.observed, self.image, "SOLPROOF01 翻訳装備")
        self.assertTrue(report["display_verified"])
        self.assertTrue(report["injection_verified"])
        report = evaluate_evidence(self.expected, self.observed, self.image, "Main menu")
        self.assertTrue(report["injection_verified"])
        self.assertFalse(report["display_verified"])
        self.assertFalse(report["samples"][0]["marker_visible_in_screenshot"])

    def test_probe_flag_cannot_override_mismatched_actual_value(self):
        self.observed["observations"][0]["actual"] = "original English"
        report = evaluate_evidence(self.expected, self.observed, self.image, "SOLPROOF01")
        self.assertFalse(report["injection_verified"])
        self.assertFalse(report["display_verified"])

    def test_ascii_ocr_glyph_confusion_is_limited_to_two_digit_marker_suffix(self):
        report = evaluate_evidence(self.expected,self.observed,self.image,'SOLPROOFO1')
        self.assertTrue(report['display_verified'])
        report = evaluate_evidence(self.expected,self.observed,self.image,'SOLPROOF02')
        self.assertFalse(report['display_verified'])
        report = evaluate_evidence(self.expected,self.observed,self.image,'SOLPROOF010')
        self.assertFalse(report['display_verified'])

    def test_expected_value_is_from_fixture_not_probe_self_report(self):
        self.observed["observations"][0].update(expected="wrong", actual="wrong")
        report = evaluate_evidence(self.expected, self.observed, self.image, "SOLPROOF01")
        self.assertFalse(report["display_verified"])

    def test_missing_or_non_png_image_never_counts_as_display(self):
        self.image.write_bytes(b"not an image")
        report = evaluate_evidence(self.expected, self.observed, self.image, "SOLPROOF01")
        self.assertFalse(report["display_verified"])
        self.assertIsNone(report["screenshot_dimensions"])

    def test_all_distinct_mod_markers_are_required(self):
        second = {"source_id": "456", "def_name": "TestHelmet", "expected": "SOLPROOF02 翻訳装備"}
        self.expected.append(second)
        self.observed["observations"].append({**second, "found": True, "actual": second["expected"]})
        report = evaluate_evidence(self.expected, self.observed, self.image, "SOLPROOF01")
        self.assertFalse(report["display_verified"])
        self.assertEqual(report["display_verified_samples"], 1)

    def test_selects_top_level_thing_label_not_tool_or_blocked_label(self):
        scan = Scan(entries=[
            Entry("tool", "DefInjected", "ThingDef", "Gun.tools.0.label", "stock", "x"),
            Entry("blocked", "DefInjected", "ThingDef", "Blocked.label", "gun", "x", blocked=True),
            Entry("valid", "DefInjected", "ThingDef", "Gun.label", "gun", "x"),
        ])
        self.assertEqual(select_label(scan).id, "valid")


if __name__ == "__main__":
    unittest.main()

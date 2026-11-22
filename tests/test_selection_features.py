"""Checks for multilingual selection, load order and flag-tagged source previews."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QListWidget
from unittest.mock import patch

from rimworld_translator.core import Project, export_mod, scan_mod
from rimworld_translator.dialogs import select_languages, select_workshop_mod
from rimworld_translator.languages import LANGUAGES, validate_languages


class SelectedLanguagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.source = self.dir / "source"
        (self.source / "Defs").mkdir(parents=True)
        (self.source / "About").mkdir()
        (self.source / "About/About.xml").write_text(
            '<ModMetaData><name>Sample</name><packageId>author.testmod</packageId>'
            '<supportedVersions><li>1.6</li></supportedVersions></ModMetaData>'
        )
        (self.source / "Defs/Things.xml").write_text(
            "<Defs><ThingDef><defName>Weapon</defName><label>weapon</label>"
            "<description>Sample description {0}</description></ThingDef></Defs>"
        )

    def test_minimum_one_and_invalid_languages(self):
        with self.assertRaises(ValueError):
            validate_languages([])
        with self.assertRaises(ValueError):
            Project.create(self.source, scan_mod(self.source), [])
        with self.assertRaises(ValueError):
            validate_languages(["Japanese", "Japanese"])
        self.assertGreaterEqual(len(LANGUAGES), 29)

    def test_checkbox_dialog_enforces_one_or_more(self):
        def simulate(dialog):
            listing = dialog.findChild(QListWidget)
            buttons = dialog.findChild(QDialogButtonBox)
            confirm = buttons.button(QDialogButtonBox.Ok)
            for row in range(listing.count()):
                listing.item(row).setCheckState(Qt.Unchecked)
            self.assertFalse(confirm.isEnabled())
            french = next(listing.item(i) for i in range(listing.count())
                          if listing.item(i).data(Qt.UserRole) == "French")
            french.setCheckState(Qt.Checked)
            self.assertTrue(confirm.isEnabled())
            return QDialog.Accepted
        with patch.object(QDialog, "exec", new=simulate):
            selected = select_languages(None, ["Japanese"])
        self.assertEqual(selected, ["French"])

    def test_source_picker_has_thumbnail_icons(self):
        workshop = self.dir / "workshop"
        mod = workshop / "1234567890"
        (mod / "About").mkdir(parents=True)
        (mod / "About/About.xml").write_text(
            "<ModMetaData><name>Visual MOD</name><packageId>author.visual</packageId></ModMetaData>"
        )
        sample = Path.home() / ".local/share/Steam/steamapps/workshop/content/294100/3687005016/About/Preview.png"
        if sample.is_file():
            (mod / "About/Preview.png").write_bytes(sample.read_bytes())
        def simulate(dialog):
            collection = dialog.findChild(QListWidget)
            self.assertEqual(collection.count(),1)
            item=collection.item(0)
            self.assertFalse(item.icon().isNull())
            collection.setCurrentRow(0)
            return QDialog.Accepted
        with patch.object(QDialog, "exec", new=simulate):
            selected=select_workshop_mod(None, workshop)
        self.assertEqual(selected,mod)

    def test_real_multilang_output_and_preview(self):
        source = Path.home() / ".local/share/Steam/steamapps/workshop/content/294100/3687005016"
        if not source.is_dir():
            self.skipTest("Workshop sample not installed")
        preview = source / "About/Preview.png"
        before = hashlib.sha256(preview.read_bytes()).hexdigest()
        project = Project.create(source, scan_mod(source), ["Japanese", "German", "French"])
        project.metadata["use_source_preview"] = "true"
        name = next(e for e in project.entries if e.key.endswith(".label") and not e.blocked)
        name.japanese = "テスト用装備"
        project.switch_language("German")
        next(e for e in project.entries if e.id == name.id).japanese = "Testausrüstung"
        project.switch_language("French")
        next(e for e in project.entries if e.id == name.id).japanese = "Équipement test"
        project.save(self.dir / "project.json")
        restored = Project.load(self.dir / "project.json")
        self.assertEqual(restored.languages, ["Japanese", "German", "French"])
        export_mod(restored, self.dir / "mod")
        about = ET.parse(self.dir / "mod/About/About.xml").getroot()
        source_id = restored.original_package_id
        self.assertEqual(about.findtext("loadAfter/li"), source_id)
        self.assertEqual(about.findtext("forceLoadAfter/li"), source_id)
        self.assertEqual(about.findtext("modDependencies/li/packageId"), source_id)
        for lang, phrase in [("Japanese","テスト用装備"),("German","Testausrüstung"),("French","Équipement test")]:
            xml = ET.parse(self.dir / f"mod/Languages/{lang}/DefInjected/ThingDef/Translations.xml").getroot()
            self.assertEqual(xml.findtext(name.key), phrase)
        generated = (self.dir / "mod/About/Preview.png").read_bytes()
        self.assertTrue(generated.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(generated), 25000)
        self.assertNotEqual(hashlib.sha256(generated).hexdigest(), before)
        self.assertEqual(hashlib.sha256(preview.read_bytes()).hexdigest(),before)
        restored.languages = ["German"]
        restored.switch_language("German")
        export_mod(restored, self.dir / "mod")
        self.assertFalse((self.dir / "mod/Languages/Japanese/DefInjected/ThingDef/Translations.xml").exists())
        self.assertFalse((self.dir / "mod/Languages/French/DefInjected/ThingDef/Translations.xml").exists())
        self.assertTrue((self.dir / "mod/Languages/German/DefInjected/ThingDef/Translations.xml").exists())


if __name__ == "__main__":
    unittest.main()

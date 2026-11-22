"""Safe translation installation and human-actionable game diagnostics."""
import hashlib
import json
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch

from rimworld_translator.platforms import GameInstallation
from rimworld_translator.installation import (
    available_mod_paths, dependencies_for, diagnose_load_order, install_translation, read_mod_metadata,
    review_installation, restore_installation,
)


def write_mod(root, package, dependencies=(), after=(), value="hello", owned=False):
    (root / "About").mkdir(parents=True, exist_ok=True)
    about = '<ModMetaData><name>Example</name><packageId>' + package + '</packageId>'
    if dependencies:
        about += '<modDependencies>' + ''.join(
            '<li><packageId>' + dep + '</packageId><displayName>' + dep + '</displayName></li>'
            for dep in dependencies
        ) + '</modDependencies>'
    about += '<loadAfter>' + ''.join('<li>' + item + '</li>' for item in after) + '</loadAfter></ModMetaData>'
    (root / "About/About.xml").write_text(about, encoding="utf-8")
    translated = root / "Languages/Japanese/Keyed/Main.xml"
    translated.parent.mkdir(parents=True, exist_ok=True)
    translated.write_text('<LanguageData><Hello>' + value + '</Hello></LanguageData>', encoding="utf-8")
    if owned:
        (root / ".rimworld-translator.json").write_text(json.dumps({
            "package_id": package, "files": ["About/About.xml", "Languages/Japanese/Keyed/Main.xml"],
        }))
    return root


class InstallationTests(unittest.TestCase):
    def test_export_manifest_paths_remain_canonical_with_windows_path_semantics(self):
        from rimworld_translator import installation
        relative = 'Languages/Japanese/DefInjected/ThingDef/Translations.xml'
        with patch.object(installation, 'Path', PureWindowsPath):
            self.assertEqual(installation._relative_file(relative), relative)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "steamapps/common/RimWorld"
        (self.game / "Data/Core").mkdir(parents=True)
        (self.game / "Mods").mkdir()
        self.workshop = self.root / "steamapps/workshop/content/294100"
        self.source = write_mod(self.workshop / "1234567890", "author.original", dependencies=["author.framework"])
        self.generated = write_mod(self.root / "output/mod", "local.translation.test", ["author.original"],
                                   ["author.original"], "最初の翻訳", True)
        self.installation = GameInstallation(self.game, self.game / "Mods", self.workshop,
                                             "1.6.4871", None, "linux", "Steam")

    def tree_hashes(self, root):
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file()}

    def test_review_is_read_only_then_installs_dedicated_owned_output(self):
        before = self.tree_hashes(self.source)
        plan = review_installation(self.generated, self.installation, source=self.source)
        self.assertFalse(plan.updating)
        self.assertEqual(plan.destination.parent, self.game / "Mods")
        self.assertFalse(plan.destination.exists())
        self.assertEqual(plan.file_count, 3)
        result = install_translation(plan)
        self.assertIsNone(result.backup)
        self.assertEqual(result.destination, plan.destination)
        self.assertTrue((result.destination / "About/About.xml").is_file())
        self.assertEqual(self.tree_hashes(result.destination), self.tree_hashes(self.generated))
        self.assertEqual(before, self.tree_hashes(self.source))

    def test_update_has_backup_and_restore_preserves_previous_versions(self):
        first = install_translation(review_installation(self.generated, self.installation))
        old_hashes = self.tree_hashes(first.destination)
        (self.generated / "Languages/Japanese/Keyed/Main.xml").write_text(
            "<LanguageData><Hello>修正版</Hello></LanguageData>", encoding="utf-8")
        plan = review_installation(self.generated, self.installation)
        self.assertTrue(plan.updating)
        updated = install_translation(plan)
        self.assertIsNotNone(updated.backup)
        self.assertNotEqual(self.tree_hashes(updated.destination), old_hashes)
        restored = restore_installation(updated.backup, self.installation)
        self.assertEqual(self.tree_hashes(restored.destination), old_hashes)
        self.assertIsNotNone(restored.backup)
        self.assertTrue(updated.backup.exists())
        self.assertTrue(restored.backup.exists())

    def test_update_keeps_the_workshop_link_of_a_published_translation(self):
        first = install_translation(review_installation(self.generated, self.installation))
        link = first.destination / "About/PublishedFileId.txt"
        link.write_text("1234567890", encoding="utf-8")
        (self.generated / "Languages/Japanese/Keyed/Main.xml").write_text(
            "<LanguageData><Hello>修正版</Hello></LanguageData>", encoding="utf-8")
        updated = install_translation(review_installation(self.generated, self.installation))
        self.assertEqual((updated.destination / "About/PublishedFileId.txt").read_text(encoding="utf-8"), "1234567890")

    def test_existing_user_mod_same_package_refused(self):
        user_mod = write_mod(self.game / "Mods/user_translation", "local.translation.test")
        before = self.tree_hashes(user_mod)
        with self.assertRaises(ValueError):
            review_installation(self.generated, self.installation)
        self.assertEqual(before, self.tree_hashes(user_mod))

    def test_owned_destination_with_unlisted_user_file_refused(self):
        result = install_translation(review_installation(self.generated, self.installation))
        (result.destination / "user_notes.txt").write_text("keep")
        with self.assertRaises(ValueError):
            review_installation(self.generated, self.installation)
        self.assertEqual((result.destination / "user_notes.txt").read_text(), "keep")

    def test_review_payload_change_refused_before_install(self):
        plan = review_installation(self.generated, self.installation)
        (self.generated / "Languages/Japanese/Keyed/Main.xml").write_text("changed")
        with self.assertRaises(ValueError):
            install_translation(plan)
        self.assertFalse(plan.destination.exists())

    def test_review_existing_destination_change_refused_before_update(self):
        result = install_translation(review_installation(self.generated, self.installation))
        plan = review_installation(self.generated, self.installation)
        (result.destination / "Languages/Japanese/Keyed/Main.xml").write_text("user changed")
        with self.assertRaises(ValueError):
            install_translation(plan)
        self.assertEqual((result.destination / "Languages/Japanese/Keyed/Main.xml").read_text(), "user changed")

    def test_workshop_destination_and_source_overlap_refused(self):
        invalid = GameInstallation(self.game, self.workshop, self.workshop, "1.6", None)
        with self.assertRaises(ValueError):
            review_installation(self.generated, invalid)
        plan = review_installation(self.generated, self.installation)
        with self.assertRaises(ValueError):
            review_installation(self.generated, self.installation, source=plan.destination)

    def test_unowned_generated_directory_and_manifest_traversal_refused(self):
        (self.generated / "user.txt").write_text("keep")
        with self.assertRaises(ValueError):
            review_installation(self.generated, self.installation)
        (self.generated / "user.txt").unlink()
        marker = self.generated / ".rimworld-translator.json"
        marker.write_text(json.dumps({"package_id": "local.translation.test", "files": ["../../source"]}))
        with self.assertRaises(ValueError):
            review_installation(self.generated, self.installation)

    def config(self, active):
        path = self.root / "user profile/Config/ModsConfig.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<ModsConfigData><activeMods>' + ''.join('<li>' + item + '</li>' for item in active)
                        + '</activeMods></ModsConfigData>')
        return path

    def test_metadata_reads_versions_alternatives_and_version_specific_dependencies(self):
        root = self.root / "versioned"
        (root / "About").mkdir(parents=True)
        (root / "About/About.xml").write_bytes((
            '﻿<ModMetaData><packageId>Sample.Versioned</packageId>\r\n'
            '<supportedVersions><li>1.4</li><li> 1.6 </li></supportedVersions>'
            '<modDependencies><li><packageId>sample.new</packageId><displayName>New</displayName>'
            '<alternativePackageIds><li>Sample.New.Fork</li><li>bad id!</li></alternativePackageIds></li></modDependencies>'
            '<modDependenciesByVersion><v1.4><li><packageId>sample.old14</packageId></li></v1.4></modDependenciesByVersion>'
            '</ModMetaData>').encode("utf-8"))
        meta = read_mod_metadata(root)
        self.assertEqual(meta.supported_versions, ("1.4", "1.6"))
        self.assertEqual(meta.dependencies[0].alternatives, ("sample.new.fork",))
        self.assertEqual([d.package_id for d in dependencies_for(meta, "1.4")], ["sample.old14"])
        self.assertEqual([d.package_id for d in dependencies_for(meta, "1.6")], ["sample.new"])

    def test_missing_original_and_source_dependency_are_actionable(self):
        missing = diagnose_load_order(self.generated, [], self.config(["local.translation.test"]))
        self.assertIn("missing-source", [item.code for item in missing])
        messages = diagnose_load_order(self.generated, [self.source], self.config(["author.original", "local.translation.test"]))
        dependency = next(item for item in messages if item.code == "missing-dependency")
        self.assertEqual(dependency.related_package_id, "author.framework")
        self.assertTrue(dependency.message)

    def test_wrong_load_order_and_disabled_dependencies_are_diagnosed_without_config_write(self):
        framework = write_mod(self.root / "framework", "author.framework")
        config = self.config(["LOCAL.TRANSLATION.TEST", "author.original"])
        before = config.read_bytes()
        messages = diagnose_load_order(self.generated, [self.source, framework], config)
        self.assertIn("load-order", [item.code for item in messages])
        self.assertIn("disabled-dependency", [item.code for item in messages])
        self.assertEqual(config.read_bytes(), before)
        good = self.config(["author.framework", "author.original", "local.translation.test"])
        self.assertFalse(diagnose_load_order(self.generated, [self.source, framework], good))

    def test_available_mod_paths_ignores_download_stubs_and_user_nonmod_folders(self):
        (self.workshop / "incomplete-download").mkdir()
        (self.game / "Mods/notes-only").mkdir()
        local = write_mod(self.game / "Mods/local-original", "author.local")
        core = write_mod(self.game / "Data/Core", "ludeon.rimworld")
        found = available_mod_paths(self.installation)
        self.assertEqual(set(found), {self.source, local, core})


if __name__ == "__main__":
    unittest.main()

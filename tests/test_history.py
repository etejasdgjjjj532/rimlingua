"""Git and no-Git checkpoints with safe, format-compatible restoration."""
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rimworld_translator.core import Entry, Project, export_mod
from rimworld_translator.history import list_snapshots, restore_snapshot, snapshot


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.path = self.root / "workspace/project.json"
        self.project = Project(str(self.source), "Example", "local.translation.history", "author.original", ["1.6"],
                               [Entry("Keyed:Keyed:Hello", "Keyed", "Keyed", "Hello", "Hello", "Languages/English/Keyed/Main.xml", "最初")], [])
        self.project.save(self.path)
        export_mod(self.project, self.path.parent / "mod")

    def modify(self, text):
        self.project.entries[0].japanese = text
        self.project.save(self.path)
        export_mod(self.project, self.path.parent / "mod")

    def test_no_git_history_noop_browse_restore_and_backup(self):
        with patch("rimworld_translator.history.shutil.which", return_value=None):
            self.assertTrue(snapshot(self.path, "最初の保存"))
            self.assertFalse(snapshot(self.path, "同じ内容"))
            first = list_snapshots(self.path)[0]
            self.assertEqual(first.backend, "file")
            self.assertEqual(first.message, "最初の保存")
            self.assertTrue(first.time)
            self.modify("復元前の未保存版")
            unrelated = self.path.parent / "notes.txt"
            unrelated.write_text("keep")
            recovered = restore_snapshot(self.path, first.id)
            self.assertEqual(recovered.entries[0].japanese, "最初")
            self.assertEqual(Project.load(self.path).entries[0].japanese, "最初")
            translated = self.path.parent / "mod/Languages/Japanese/Keyed/Keyed.xml"
            self.assertIn("最初", translated.read_text())
            records = list_snapshots(self.path)
            self.assertEqual(len(records), 2)
            self.assertIn("Before restore", records[0].message)
            self.assertEqual(restore_snapshot(self.path, records[0].id).entries[0].japanese, "復元前の未保存版")
            self.assertEqual(unrelated.read_text(), "keep")
            self.assertFalse((self.path.parent / ".git").exists())

    @unittest.skipUnless(shutil.which("git"), "Git is not installed")
    def test_git_browse_does_not_commit_restore_keeps_head_and_unrelated_files(self):
        self.assertTrue(snapshot(self.path, "initial"))
        first = list_snapshots(self.path)[0]
        self.assertEqual(first.backend, "git")
        self.modify("現在の保存版")
        self.assertTrue(snapshot(self.path, "second"))
        workspace = self.path.parent
        unrelated = workspace / "notes.txt"
        unrelated.write_text("keep")
        command = ["git", "-C", str(workspace)]
        subprocess.run([*command, "add", "--", "notes.txt"], check=True, capture_output=True)
        head = subprocess.check_output([*command, "rev-parse", "HEAD"]).strip()
        count = subprocess.check_output([*command, "rev-list", "--count", "HEAD"]).strip()
        self.assertEqual(len(list_snapshots(self.path)), 2)
        self.assertEqual(subprocess.check_output([*command, "rev-list", "--count", "HEAD"]).strip(), count)
        recovered = restore_snapshot(self.path, first.id)
        self.assertEqual(recovered.entries[0].japanese, "最初")
        self.assertEqual(subprocess.check_output([*command, "rev-parse", "HEAD"]).strip(), head)
        self.assertEqual(unrelated.read_text(), "keep")
        self.assertIn("notes.txt", subprocess.check_output([*command, "diff", "--cached", "--name-only"], text=True))
        self.assertIn("最初", (workspace / "mod/Languages/Japanese/Keyed/Keyed.xml").read_text())

    @unittest.skipUnless(shutil.which("git"), "Git is not installed")
    def test_unsnapshotted_git_changes_backed_up_before_restore(self):
        snapshot(self.path, "first")
        first = list_snapshots(self.path)[0]
        self.modify("バックアップされる変更")
        recovered = restore_snapshot(self.path, first.id)
        self.assertEqual(recovered.entries[0].japanese, "最初")
        records = list_snapshots(self.path)
        self.assertEqual(len(records), 2)
        self.assertIn("Before restore", records[0].message)
        self.assertEqual(restore_snapshot(self.path, records[0].id).entries[0].japanese, "バックアップされる変更")

    def test_old_project_format_restored_with_regenerated_export(self):
        legacy = asdict(self.project)
        for name in ("translations", "languages", "language"):
            legacy.pop(name)
        self.path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        with patch("rimworld_translator.history.shutil.which", return_value=None):
            snapshot(self.path, "legacy format")
            revision = list_snapshots(self.path)[0].id
            self.modify("新しい形式")
            restored = restore_snapshot(self.path, revision)
        self.assertEqual(restored.entries[0].japanese, "最初")
        self.assertEqual(restored.languages, ["Japanese"])
        self.assertEqual(restored.language, "Japanese")
        self.assertTrue((self.path.parent / "mod/.rimworld-translator.json").is_file())

    def test_invalid_ids_and_unowned_export_refused_without_changes(self):
        with patch("rimworld_translator.history.shutil.which", return_value=None):
            snapshot(self.path)
            revision = list_snapshots(self.path)[0].id
            before = self.path.read_bytes()
            for unsafe in ("HEAD", "HEAD~1", "../project.json", "--help", revision + ":x"):
                with self.assertRaises(ValueError):
                    restore_snapshot(self.path, unsafe)
                self.assertEqual(self.path.read_bytes(), before)
            self.modify("keep current")
            before = self.path.read_bytes()
            (self.path.parent / "mod/user_notes.txt").write_text("keep")
            with self.assertRaises(ValueError):
                restore_snapshot(self.path, revision)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual((self.path.parent / "mod/user_notes.txt").read_text(), "keep")

    @unittest.skipUnless(shutil.which("git"), "Git is not installed")
    def test_file_history_coexists_with_existing_git_snapshots(self):
        snapshot(self.path, "git checkpoint")
        original = list_snapshots(self.path)[0]
        self.modify("Gitなしの保存")
        with patch("rimworld_translator.history.shutil.which", return_value=None):
            snapshot(self.path, "file checkpoint")
            self.assertEqual(len(list_snapshots(self.path)), 1)
        records = list_snapshots(self.path)
        self.assertEqual({item.backend for item in records}, {"git", "file"})
        self.assertIn(original.id, [item.id for item in records])

    def test_failed_export_swap_rolls_back_project_and_mod(self):
        with patch("rimworld_translator.history.shutil.which", return_value=None):
            snapshot(self.path, "first")
            revision = list_snapshots(self.path)[0].id
            self.modify("保持される現在の版")
            before = self.path.read_bytes()
            mod = self.path.parent / "mod"
            exported = {str(p.relative_to(mod)): p.read_bytes() for p in mod.rglob("*") if p.is_file()}
            import os
            original_replace = os.replace
            def reject_new_mod(source, target):
                source, target = Path(source), Path(target)
                if source.name == "mod" and source.parent.name.startswith(".restore-") and target == mod:
                    raise OSError("simulated export rename failure")
                return original_replace(source, target)
            with patch("rimworld_translator.history.os.replace", side_effect=reject_new_mod):
                with self.assertRaises(OSError):
                    restore_snapshot(self.path, revision)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual({str(p.relative_to(mod)): p.read_bytes() for p in mod.rglob("*") if p.is_file()}, exported)
            self.assertEqual(len(list_snapshots(self.path)), 2)


if __name__ == "__main__":
    unittest.main()

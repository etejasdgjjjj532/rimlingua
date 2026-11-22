import csv
import difflib
import hashlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import Entry, Project, Scan, scan_mod
from rimworld_translator import workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.entries = [
            Entry("DefInjected:ThingDef:Gun.label", "DefInjected", "ThingDef", "Gun.label", "gun", "Defs/Things.xml"),
            Entry("DefInjected:ThingDef:Gun.description", "DefInjected", "ThingDef", "Gun.description", "A gun {0}", "Defs/Things.xml"),
            Entry("Keyed:Keyed:Hello", "Keyed", "Keyed", "Hello", "Hello {name}", "Languages/English/Keyed/Main.xml"),
            Entry("Keyed:Keyed:GunAgain", "Keyed", "Keyed", "GunAgain", "gun", "Languages/English/Keyed/Main.xml"),
        ]
        self.project = Project.create(self.source, Scan(entries=self.entries), ["Japanese", "French"])
        # Edits and assertions refer to the project's independent working copy.
        self.entries = self.project.entries

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def csv_path(self, rows):
        path = self.root / "translations.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["id", "kind", "group", "key", "english", "translation", "language"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def diff_fixture(self):
        base = self.write("source/Languages/Japanese/DefInjected/ThingDef/Things.xml",
                          "<LanguageData>\n  <Gun.label>前の銃</Gun.label>\n</LanguageData>\n")
        patch = self.write("translations.patch",
                           "diff --git a/Languages/Japanese/DefInjected/ThingDef/Things.xml b/Languages/Japanese/DefInjected/ThingDef/Things.xml\n"
                           "index 1111111..2222222 100644\n"
                           "--- a/Languages/Japanese/DefInjected/ThingDef/Things.xml\n"
                           "+++ b/Languages/Japanese/DefInjected/ThingDef/Things.xml\n"
                           "@@ -1,3 +1,3 @@\n <LanguageData>\n-  <Gun.label>前の銃</Gun.label>\n"
                           "+  <Gun.label>新しい銃</Gun.label>\n </LanguageData>\n")
        return base, patch

    def test_diff_requires_an_explicit_base_folder(self):
        _, patch = self.diff_fixture()
        with self.assertRaisesRegex(ValueError, "元|基準|base"):
            workflow.preview_import(self.project, patch)

    def test_diff_update_and_file_creation_are_previewed_and_undoable_without_source_writes(self):
        base, patch = self.diff_fixture()
        created = self.source / "Languages/Japanese/Keyed/New.xml"
        patch.write_text(patch.read_text(encoding="utf-8") +
                         "diff --git a/Languages/Japanese/Keyed/New.xml b/Languages/Japanese/Keyed/New.xml\n"
                         "new file mode 100644\n--- /dev/null\n+++ b/Languages/Japanese/Keyed/New.xml\n"
                         "@@ -0,0 +1,3 @@\n+<LanguageData>\n+  <Hello>こんにちは {name}</Hello>\n+</LanguageData>\n",
                         encoding="utf-8", newline="")
        original = base.read_bytes()
        preview = workflow.preview_import(self.project, patch, base_folder=self.source)
        self.assertEqual({(change.id, change.language, change.after) for change in preview.changes}, {
            (self.entries[0].id, "Japanese", "新しい銃"),
            (self.entries[2].id, "Japanese", "こんにちは {name}"),
        })
        self.assertEqual(preview.warnings, [])
        self.assertEqual(self.entries[0].japanese, "")
        self.assertFalse(created.exists())
        batch = workflow.apply_changes(self.project, preview.changes)
        self.assertEqual(self.entries[0].japanese, "新しい銃")
        self.assertEqual(self.entries[2].japanese, "こんにちは {name}")
        batch.undo(self.project)
        self.assertEqual(self.entries[0].japanese, "")
        self.assertEqual(self.entries[2].japanese, "")
        batch.redo(self.project)
        self.assertEqual(self.entries[0].japanese, "新しい銃")
        self.assertEqual(base.read_bytes(), original)
        self.assertFalse(created.exists())

    def test_diff_conflict_requires_overwrite_and_undo_restores_approval_and_other_languages(self):
        base, patch = self.diff_fixture()
        self.project.set_translation(self.entries[0].id, "自分の銃")
        self.project.mark_reviewed(self.entries[0].id, approved=True)
        self.project.translations["French"] = {self.entries[0].id: "fusil"}
        original = base.read_bytes()
        preview = workflow.preview_import(self.project, patch, base_folder=self.source)
        self.assertEqual(preview.changes, [])
        self.assertEqual(len(preview.conflicts), 1)
        overwrite = workflow.preview_import(self.project, patch, overwrite=True, base_folder=self.source)
        batch = workflow.apply_changes(self.project, overwrite.changes)
        self.assertEqual(self.entries[0].japanese, "新しい銃")
        self.assertFalse(self.entries[0].approved)
        batch.undo(self.project)
        self.assertEqual(self.entries[0].japanese, "自分の銃")
        self.assertTrue(self.entries[0].approved)
        self.assertEqual(self.project.translations["French"][self.entries[0].id], "fusil")
        self.assertEqual(base.read_bytes(), original)

    def test_diff_mismatching_base_content_position_and_line_endings_are_not_guessed(self):
        base, patch = self.diff_fixture()
        for content in (b"<LanguageData>\n  <Gun.label>different</Gun.label>\n</LanguageData>\n",
                        b"\n<LanguageData>\n  <Gun.label>\xe5\x89\x8d\xe3\x81\xae\xe9\x8a\x83</Gun.label>\n</LanguageData>\n",
                        "<LanguageData>\r\n  <Gun.label>前の銃</Gun.label>\r\n</LanguageData>\r\n".encode("utf-8")):
            with self.subTest(content=content):
                base.write_bytes(content)
                preview = workflow.preview_import(self.project, patch, base_folder=self.source)
                self.assertEqual(preview.changes, [])
                self.assertTrue(preview.warnings)
                self.assertEqual(base.read_bytes(), content)

    def test_diff_addition_does_not_replace_an_existing_file(self):
        base, _ = self.diff_fixture()
        patch = self.write("add.diff", "--- /dev/null\n+++ b/Languages/Japanese/DefInjected/ThingDef/Things.xml\n"
                           "@@ -0,0 +1 @@\n+<LanguageData><Gun.label>新しい銃</Gun.label></LanguageData>\n")
        original = base.read_bytes()
        preview = workflow.preview_import(self.project, patch, base_folder=self.source)
        self.assertEqual(preview.changes, [])
        self.assertTrue(preview.warnings)
        self.assertEqual(base.read_bytes(), original)

    def test_diff_file_deletion_is_verified_and_preserves_work_and_base_file(self):
        base, _ = self.diff_fixture()
        self.entries[0].japanese = "自分の銃"
        patch = self.write("delete.diff", "--- a/Languages/Japanese/DefInjected/ThingDef/Things.xml\n+++ /dev/null\n"
                           "@@ -1,3 +0,0 @@\n-<LanguageData>\n-  <Gun.label>前の銃</Gun.label>\n-</LanguageData>\n")
        original = base.read_bytes()
        preview = workflow.preview_import(self.project, patch, overwrite=True, base_folder=self.source)
        self.assertEqual(preview.changes, [])
        self.assertTrue(any("削除" in warning for warning in preview.warnings))
        self.assertEqual(self.entries[0].japanese, "自分の銃")
        self.assertEqual(base.read_bytes(), original)

    def test_diff_removed_keys_and_blank_translations_cannot_erase_current_work(self):
        base = self.write("source/Languages/Japanese/DefInjected/ThingDef/Things.xml",
                          "<LanguageData>\n  <Gun.label>銃</Gun.label>\n  <Gun.description>説明 {0}</Gun.description>\n</LanguageData>\n")
        self.entries[0].japanese = "自分の銃"
        self.entries[1].japanese = "自分の説明 {0}"
        patch = self.write("blank.patch", "--- Languages/Japanese/DefInjected/ThingDef/Things.xml\n"
                           "+++ Languages/Japanese/DefInjected/ThingDef/Things.xml\n@@ -1,4 +1,3 @@\n <LanguageData>\n"
                           "-  <Gun.label>銃</Gun.label>\n-  <Gun.description>説明 {0}</Gun.description>\n"
                           "+  <Gun.label> </Gun.label>\n </LanguageData>\n")
        original = base.read_bytes()
        preview = workflow.preview_import(self.project, patch, overwrite=True, base_folder=self.source)
        self.assertEqual(preview.changes, [])
        self.assertTrue(preview.warnings)
        self.assertEqual(self.entries[0].japanese, "自分の銃")
        self.assertEqual(self.entries[1].japanese, "自分の説明 {0}")
        self.assertEqual(base.read_bytes(), original)

    def test_diff_unsafe_and_non_xml_paths_are_rejected(self):
        for name in ("../outside.xml", "/absolute.xml", "C:/outside.xml", "//server/share.xml",
                     "Languages/Japanese/Keyed/../Main.xml", "Languages\\Japanese\\Keyed\\Main.xml",
                     "run.py", "Languages/Japanese/Keyed/Main.xml:stream"):
            with self.subTest(name=name):
                patch = self.write("unsafe.patch", f"--- /dev/null\n+++ {name}\n"
                                   "@@ -0,0 +1 @@\n+<LanguageData><Hello>こんにちは {name}</Hello></LanguageData>\n")
                preview = workflow.preview_import(self.project, patch, base_folder=self.source)
                self.assertEqual(preview.changes, [])
                self.assertTrue(preview.warnings)

    def test_diff_never_follows_a_base_folder_or_xml_symlink(self):
        base, patch = self.diff_fixture()
        folder_link = self.root / "source-link"
        try:
            folder_link.symlink_to(self.source, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "リンク|link"):
            workflow.preview_import(self.project, patch, base_folder=folder_link)
        original = base.read_bytes()
        original_path = base.with_suffix(".original")
        base.rename(original_path)
        base.symlink_to(original_path)
        preview = workflow.preview_import(self.project, patch, base_folder=self.source)
        self.assertEqual(preview.changes, [])
        self.assertTrue(preview.warnings)
        self.assertEqual(original_path.read_bytes(), original)

    def test_diff_malformed_or_unsupported_formats_have_no_import_candidates(self):
        _, valid = self.diff_fixture()
        normal = valid.read_text(encoding="utf-8")
        cases = {
            "binary": "diff --git a/Main.xml b/Main.xml\nGIT binary patch\nliteral 0\n",
            "rename": normal.replace("index 1111111..2222222 100644", "rename from Old.xml\nrename to New.xml"),
            "combined": normal.replace("@@ -1,3 +1,3 @@", "@@@ -1,3 -1,3 +1,3 @@@"),
            "wrong count": normal.replace("@@ -1,3 +1,3 @@", "@@ -1,4 +1,4 @@"),
            "wrong output position": normal.replace("@@ -1,3 +1,3 @@", "@@ -1,3 +2,3 @@"),
            "no hunks": "--- Main.xml\n+++ Main.xml\n",
            "repeated file": normal + normal,
            "quoted path": normal.replace("--- a/Languages/", '--- "a/Languages/'),
            "symlink mode": normal.replace("100644", "120000"),
            "path mismatch": normal.replace("+++ b/Languages/Japanese/DefInjected/ThingDef/Things.xml", "+++ b/Different.xml"),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                patch = self.write("unsupported.diff", text)
                preview = workflow.preview_import(self.project, patch, base_folder=self.source)
                self.assertEqual(preview.changes, [])
                self.assertTrue(preview.warnings)

    def test_diff_single_line_hunks_preserve_missing_final_newline(self):
        base = self.write("source/subset.xml", "<LanguageData><Gun.label>前の銃</Gun.label></LanguageData>")
        patch = self.write("no-newline.diff", "--- subset.xml\n+++ subset.xml\n@@ -1 +1 @@\n"
                           "-<LanguageData><Gun.label>前の銃</Gun.label></LanguageData>\n\\ No newline at end of file\n"
                           "+<LanguageData><Gun.label>新しい銃</Gun.label></LanguageData>\n\\ No newline at end of file\n")
        original = base.read_bytes()
        preview = workflow.preview_import(self.project, patch, base_folder=self.source)
        self.assertEqual([(change.id, change.after) for change in preview.changes], [(self.entries[0].id, "新しい銃")])
        self.assertEqual(base.read_bytes(), original)

    def test_diff_multiple_hunks_and_zero_length_insertions_use_declared_positions(self):
        self.write("source/Languages/Japanese/Keyed/Main.xml",
                   "<LanguageData>\n  <Hello>古い挨拶 {name}</Hello>\n  <!-- keep -->\n  <!-- more -->\n</LanguageData>\n")
        patch = self.write("multi.diff", "--- Languages/Japanese/Keyed/Main.xml\n+++ Languages/Japanese/Keyed/Main.xml\n"
                           "@@ -2 +2 @@\n-  <Hello>古い挨拶 {name}</Hello>\n+  <Hello>こんにちは {name}</Hello>\n"
                           "@@ -4,0 +5 @@\n+  <GunAgain>鉄砲</GunAgain>\n")
        preview = workflow.preview_import(self.project, patch, base_folder=self.source)
        self.assertEqual({(change.id, change.after) for change in preview.changes}, {
            (self.entries[2].id, "こんにちは {name}"), (self.entries[3].id, "鉄砲")})
        self.assertEqual(preview.warnings, [])

    def test_diff_canonical_french_definjected_path_does_not_use_active_language(self):
        patch = self.write("french.diff", "--- /dev/null\n+++ b/Languages/French/DefInjected/ThingDef/New.xml\n"
                           "@@ -0,0 +1 @@\n+<LanguageData><Gun.label>fusil</Gun.label></LanguageData>\n")
        preview = workflow.preview_import(self.project, patch, base_folder=self.source)
        self.assertEqual([(change.id, change.language, change.after) for change in preview.changes],
                         [(self.entries[0].id, "French", "fusil")])
        workflow.apply_changes(self.project, preview.changes)
        self.assertEqual(self.project.language, "Japanese")
        self.assertEqual(self.entries[0].japanese, "")

    def test_diff_only_accepts_translation_xml_without_dtd_or_entities(self):
        for content in ("<Defs><ThingDef><label>not a translation</label></ThingDef></Defs>",
                        '<?xml version="1.0" encoding="unsupported"?><LanguageData><Hello>hello</Hello></LanguageData>',
                        '<!DOCTYPE LanguageData [<!ENTITY text "expanded">]><LanguageData><Hello>&text;</Hello></LanguageData>'):
            with self.subTest(content=content):
                patch = self.write("invalid-xml.diff", f"--- /dev/null\n+++ New.xml\n@@ -0,0 +1 @@\n+{content}\n")
                preview = workflow.preview_import(self.project, patch, base_folder=self.source)
                self.assertEqual(preview.changes, [])
                self.assertTrue(preview.warnings)

    def test_diff_conflicting_incoming_xml_keys_and_unknown_keys_remain_visible(self):
        patch = self.write("duplicates.diff", "--- /dev/null\n+++ Languages/Japanese/Keyed/One.xml\n"
                           "@@ -0,0 +1 @@\n+<LanguageData><Hello>一つ目 {name}</Hello><Unknown>不明</Unknown></LanguageData>\n"
                           "--- /dev/null\n+++ Languages/Japanese/Keyed/Two.xml\n"
                           "@@ -0,0 +1 @@\n+<LanguageData><Hello>二つ目 {name}</Hello></LanguageData>\n")
        preview = workflow.preview_import(self.project, patch, overwrite=True, base_folder=self.source)
        self.assertEqual(preview.changes, [])
        self.assertEqual(len(preview.conflicts), 1)
        self.assertEqual(preview.unknown, ["Keyed:Keyed:Unknown"])

    def test_real_workshop_crlf_xml_diff_is_imported_without_modifying_installed_files(self):
        source = Path.home() / ".local/share/Steam/steamapps/workshop/content/294100/3781013698"
        catalog = source / "Languages/ChineseSimplified/Keyed/Keyed.xml"
        if not catalog.is_file():
            self.skipTest("Real Workshop translation sample 3781013698 is not installed")
        original = catalog.read_bytes()
        replacement = original.replace("<ImageOpt>图片加载优化</ImageOpt>".encode("utf-8"),
                                       "<ImageOpt>图片加载优化 [diff]</ImageOpt>".encode("utf-8"), 1)
        self.assertNotEqual(original, replacement)
        patch_data = b"".join(difflib.diff_bytes(difflib.unified_diff, original.splitlines(keepends=True),
                            replacement.splitlines(keepends=True),
                            fromfile=b"a/Languages/ChineseSimplified/Keyed/Keyed.xml",
                            tofile=b"b/Languages/ChineseSimplified/Keyed/Keyed.xml"))
        patch = self.root / "real.diff"
        patch.write_bytes(patch_data)
        project = Project.create(source, scan_mod(source), ["ChineseSimplified"])
        preview = workflow.preview_import(project, patch, base_folder=source)
        changes = {change.id: change.after for change in preview.changes}
        self.assertEqual(changes["Keyed:Keyed:ImageOpt"], "图片加载优化 [diff]")
        batch = workflow.apply_changes(project, preview.changes)
        batch.undo(project)
        self.assertEqual(project.get_translation("Keyed:Keyed:ImageOpt"), "")
        self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), hashlib.sha256(original).hexdigest())

    def test_mod_import_preserves_current_work_blanks_and_input_files(self):
        self.project.entries[0].japanese = "自分の銃"
        self.project.entries[1].japanese = "自分の説明 {0}"
        xml = self.write("translated/Languages/Japanese/DefInjected/ThingDef/Things.xml",
                         "<LanguageData><Gun.label>銃</Gun.label><Gun.description> </Gun.description><Unknown.label>不明</Unknown.label></LanguageData>")
        keyed = self.write("translated/Languages/Japanese/Keyed/Main.xml",
                           "<LanguageData><Hello>こんにちは {name}</Hello></LanguageData>")
        digest = hashlib.sha256(xml.read_bytes()).hexdigest()
        preview = workflow.preview_import(self.project, self.root / "translated")
        self.assertEqual([(change.id, change.after) for change in preview.changes], [("Keyed:Keyed:Hello", "こんにちは {name}")])
        self.assertEqual(len(preview.conflicts), 1)
        self.assertTrue(any("Unknown.label" in item for item in preview.unknown))
        self.assertEqual(self.project.entries[2].japanese, "")
        workflow.apply_changes(self.project, preview.changes)
        self.assertEqual(self.project.entries[0].japanese, "自分の銃")
        self.assertEqual(self.project.entries[1].japanese, "自分の説明 {0}")
        self.assertEqual(self.project.entries[2].japanese, "こんにちは {name}")
        self.assertEqual(hashlib.sha256(xml.read_bytes()).hexdigest(), digest)
        self.assertTrue(keyed.is_file())

    def test_explicit_overwrite_import_is_undoable_and_other_languages_survive(self):
        self.project.entries[0].japanese = "前の銃"
        self.project.translations["French"] = {self.entries[0].id: "fusil"}
        xml = self.write("subset.xml", "<LanguageData><Gun.label>新しい銃</Gun.label></LanguageData>")
        preview = workflow.preview_import(self.project, xml, overwrite=True)
        self.assertEqual(preview.conflicts, [])
        self.assertEqual(len(preview.changes), 1)
        batch = workflow.apply_changes(self.project, preview.changes)
        self.assertEqual(self.project.entries[0].japanese, "新しい銃")
        batch.undo(self.project)
        self.assertEqual(self.project.entries[0].japanese, "前の銃")
        batch.redo(self.project)
        self.assertEqual(self.project.entries[0].japanese, "新しい銃")
        self.assertEqual(self.project.translations["French"][self.entries[0].id], "fusil")

    def test_language_folder_import_uses_its_language_without_switching_active_language(self):
        xml = self.write("translated/Languages/French/DefInjected/ThingDef.xml", "<LanguageData><Gun.label>fusil</Gun.label></LanguageData>")
        preview = workflow.preview_import(self.project, xml.parent.parent)
        self.assertEqual([(change.language, change.after) for change in preview.changes], [("French", "fusil")])
        workflow.apply_changes(self.project, preview.changes)
        self.assertEqual(self.project.language, "Japanese")
        self.assertEqual(self.project.entries[0].japanese, "")
        self.assertEqual(self.project.translations["French"][self.entries[0].id], "fusil")

    def test_detached_language_folder_retains_its_language(self):
        path = self.write("French/Keyed/Main.xml", "<LanguageData><Hello>Bonjour {name}</Hello></LanguageData>")
        preview = workflow.preview_import(self.project, path.parent.parent)
        self.assertEqual([(change.language, change.after) for change in preview.changes], [("French", "Bonjour {name}")])

    def test_csv_import_flags_changed_english_and_unknown_ids(self):
        path = self.csv_path([
            {"id": self.entries[0].id, "english": "old gun", "translation": "銃", "language": "Japanese"},
            {"id": "Keyed:Keyed:Unknown", "translation": "不明", "language": "Japanese"},
        ])
        preview = workflow.preview_import(self.project, path)
        self.assertEqual(len(preview.changes), 1)
        self.assertTrue(preview.changes[0].review)
        self.assertTrue(any(self.entries[0].id in issue for issue in preview.warnings))
        self.assertEqual(preview.unknown, ["Keyed:Keyed:Unknown"])
        workflow.apply_changes(self.project, preview.changes)
        self.assertTrue(self.project.entries[0].review)

    def test_conflicting_duplicate_import_rows_cannot_select_one_implicitly(self):
        path = self.csv_path([
            {"id": self.entries[0].id, "translation": "銃", "language": "Japanese"},
            {"id": self.entries[0].id, "translation": "鉄砲", "language": "Japanese"},
        ])
        preview = workflow.preview_import(self.project, path, overwrite=True)
        self.assertEqual(preview.changes, [])
        self.assertEqual(len(preview.conflicts), 1)

    def test_csv_export_and_import_preserve_quotes_unicode_and_newlines(self):
        self.entries[0].japanese = '銃, "特製"\n二行目'
        self.project.translations["French"] = {self.entries[0].id: "fusil\nspécial"}
        path = self.root / "workspace/exchange.csv"
        workflow.export_csv(self.project, path)
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        fresh = Project.create(self.source, Scan(entries=[Entry(**{**vars(entry), "japanese": ""}) for entry in self.entries]), ["Japanese", "French"])
        preview = workflow.preview_import(fresh, path)
        workflow.apply_changes(fresh, preview.changes)
        self.assertEqual(fresh.entries[0].japanese, '銃, "特製"\n二行目')
        self.assertEqual(fresh.translations["French"][self.entries[0].id], "fusil\nspécial")

    def test_contextual_po_roundtrip_maps_equal_english_to_distinct_stable_ids(self):
        self.entries[0].japanese = "銃"
        self.entries[3].japanese = "鉄砲"
        path = self.root / "workspace/exchange.po"
        workflow.export_po(self.project, path)
        fresh = Project.create(self.source, Scan(entries=[Entry(**{**vars(entry), "japanese": ""}) for entry in self.entries]))
        preview = workflow.preview_import(fresh, path)
        workflow.apply_changes(fresh, preview.changes)
        self.assertEqual(fresh.entries[0].japanese, "銃")
        self.assertEqual(fresh.entries[3].japanese, "鉄砲")

    def test_fuzzy_po_import_requires_review_and_does_not_approve_an_equal_source(self):
        path = self.write("fuzzy.po", 'msgid ""\nmsgstr ""\n"Language: Japanese\\n"\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n#, fuzzy\nmsgctxt "DefInjected:ThingDef:Gun.label"\nmsgid "gun"\nmsgstr "銃"\n')
        preview = workflow.preview_import(self.project, path)
        self.assertTrue(preview.changes[0].review)
        workflow.apply_changes(self.project, preview.changes)
        self.assertTrue(self.entries[0].review)

    def test_gettext_locale_language_code_maps_to_a_selected_rimworld_language(self):
        path = self.write("locale.po", 'msgid ""\nmsgstr ""\n"Language: ja\\n"\n"Content-Type: text/plain; charset=UTF-8\\n"\n\nmsgctxt "DefInjected:ThingDef:Gun.label"\nmsgid "gun"\nmsgstr "銃"\n')
        preview = workflow.preview_import(self.project, path)
        self.assertEqual([(change.language, change.after) for change in preview.changes], [("Japanese", "銃")])

    def test_po_uses_declared_charset_for_non_utf8_external_catalogs(self):
        path = self.root / "latin.po"
        path.write_bytes(('msgid ""\nmsgstr ""\n"Language: fr\\n"\n"Content-Type: text/plain; charset=ISO-8859-1\\n"\n\nmsgctxt "DefInjected:ThingDef:Gun.label"\nmsgid "gun"\nmsgstr "fusil amélioré"\n').encode("latin-1"))
        preview = workflow.preview_import(self.project, path)
        self.assertEqual([(change.language, change.after) for change in preview.changes], [("French", "fusil amélioré")])

    def test_po_without_stable_context_does_not_guess_between_equal_english_keys(self):
        path = self.write("no-context.po", 'msgid ""\nmsgstr ""\n"Language: Japanese\\n"\n\nmsgid "gun"\nmsgstr "銃"\n')
        preview = workflow.preview_import(self.project, path)
        self.assertEqual(preview.changes, [])
        self.assertEqual(preview.unknown, ["gun"])
        self.assertTrue(preview.warnings)

    def test_old_editor_definjected_group_xml_is_supported(self):
        path = self.write("legacy/Languages/Japanese/DefInjected/ThingDef.xml", "<LanguageData><Gun.label>銃</Gun.label></LanguageData>")
        preview = workflow.preview_import(self.project, path)
        self.assertEqual([(change.id, change.after) for change in preview.changes], [(self.entries[0].id, "銃")])

    def test_xml_version_branch_collision_is_reported_without_selecting_a_branch(self):
        self.write("versioned/1.5/Languages/Japanese/Keyed/Main.xml", "<LanguageData><Hello>旧訳 {name}</Hello></LanguageData>")
        self.write("versioned/1.6/Languages/Japanese/Keyed/Main.xml", "<LanguageData><Hello>新訳 {name}</Hello></LanguageData>")
        preview = workflow.preview_import(self.project, self.root / "versioned", overwrite=True)
        self.assertEqual(preview.changes, [])
        self.assertEqual(len(preview.conflicts), 1)
        self.assertTrue(preview.warnings)

    def test_blank_import_never_erases_work_even_when_overwrite_is_selected(self):
        self.entries[0].japanese = "銃"
        path = self.csv_path([{"id": self.entries[0].id, "translation": "", "language": "Japanese"}])
        preview = workflow.preview_import(self.project, path, overwrite=True)
        self.assertEqual(preview.changes, [])
        self.assertEqual(self.entries[0].japanese, "銃")

    def test_apply_checks_all_preconditions_before_mutating_any_entry(self):
        changes = [workflow.TranslationChange(self.entries[0].id, "Japanese", "", "銃"),
                   workflow.TranslationChange(self.entries[1].id, "Japanese", "", "説明 {0}")]
        self.entries[1].japanese = "あとから編集 {0}"
        with self.assertRaisesRegex(ValueError, "プレビュー|変更|preview"):
            workflow.apply_changes(self.project, changes)
        self.assertEqual(self.entries[0].japanese, "")
        self.assertEqual(self.entries[1].japanese, "あとから編集 {0}")

    def test_undo_checks_all_preconditions_before_mutating_any_entry(self):
        changes = [workflow.TranslationChange(self.entries[0].id, "Japanese", "", "銃"),
                   workflow.TranslationChange(self.entries[1].id, "Japanese", "", "説明 {0}")]
        batch = workflow.apply_changes(self.project, changes)
        self.entries[1].japanese = "あとから編集 {0}"
        with self.assertRaises(ValueError):
            batch.undo(self.project)
        self.assertEqual(self.entries[0].japanese, "銃")

    def test_undo_restores_review_and_approval_for_the_edited_language(self):
        self.project.set_translation(self.entries[0].id, "前の銃")
        self.project.mark_reviewed(self.entries[0].id, approved=True)
        changes = [workflow.TranslationChange(self.entries[0].id, "Japanese", "前の銃", "新しい銃")]
        batch = workflow.apply_changes(self.project, changes)
        self.assertFalse(self.entries[0].reviewed)
        self.assertFalse(self.entries[0].approved)
        batch.undo(self.project)
        self.assertTrue(self.entries[0].reviewed)
        self.assertTrue(self.entries[0].approved)
        batch.redo(self.project)
        self.assertFalse(self.entries[0].reviewed)
        self.assertFalse(self.entries[0].approved)

    def test_source_mismatch_revokes_approval_even_when_translation_is_unchanged(self):
        self.project.set_translation(self.entries[0].id, "銃")
        self.project.mark_reviewed(self.entries[0].id, approved=True)
        path = self.csv_path([{"id": self.entries[0].id, "english": "old gun", "translation": "銃", "language": "Japanese"}])
        preview = workflow.preview_import(self.project, path)
        batch = workflow.apply_changes(self.project, preview.changes)
        self.assertTrue(self.entries[0].review)
        self.assertFalse(self.entries[0].approved)
        batch.undo(self.project)
        self.assertTrue(self.entries[0].approved)
        self.assertFalse(self.entries[0].review)

    def test_undo_after_switching_language_restores_only_the_original_language_state(self):
        self.project.set_translation(self.entries[0].id, "前の銃")
        self.project.mark_reviewed(self.entries[0].id, approved=True)
        batch = workflow.apply_changes(self.project, [workflow.TranslationChange(self.entries[0].id, "Japanese", "前の銃", "新しい銃", review=True)])
        self.project.switch_language("French")
        french_state = (self.entries[0].review, self.entries[0].changed, self.entries[0].reviewed, self.entries[0].approved)
        batch.undo(self.project)
        self.assertEqual((self.entries[0].review, self.entries[0].changed, self.entries[0].reviewed, self.entries[0].approved), french_state)
        self.project.switch_language("Japanese")
        self.assertEqual(self.entries[0].japanese, "前の銃")
        self.assertTrue(self.entries[0].approved)
        self.assertFalse(self.entries[0].review)

    def test_duplicate_targets_in_a_batch_are_rejected_before_any_change(self):
        changes = [workflow.TranslationChange(self.entries[0].id, "Japanese", "", "銃"),
                   workflow.TranslationChange(self.entries[0].id, "Japanese", "", "鉄砲")]
        with self.assertRaises(ValueError):
            workflow.apply_changes(self.project, changes)
        self.assertEqual(self.entries[0].japanese, "")

    def test_replace_preview_uses_current_language_only_and_skips_unchanged(self):
        self.entries[0].japanese = "小さい銃"
        self.entries[1].japanese = "銃の説明 {0}"
        self.project.translations["French"] = {self.entries[0].id: "gun"}
        preview = workflow.preview_replace(self.project, "銃", "鉄砲", entry_ids=[self.entries[0].id])
        self.assertEqual([(change.id, change.after) for change in preview.changes], [(self.entries[0].id, "小さい鉄砲")])
        workflow.apply_changes(self.project, preview.changes)
        self.assertEqual(self.entries[1].japanese, "銃の説明 {0}")
        self.assertEqual(self.project.translations["French"][self.entries[0].id], "gun")
        self.assertEqual(workflow.preview_replace(self.project, "missing", "test").changes, [])
        with self.assertRaisesRegex(ValueError, "正規表現|regular expression"):
            workflow.preview_replace(self.project, "[", "", regex=True)

    def test_translation_memory_returns_all_ambiguous_candidates_without_editing(self):
        self.entries[0].japanese = "銃"
        self.entries[3].japanese = "鉄砲"
        extra = Entry("Keyed:Keyed:GunThird", "Keyed", "Keyed", "GunThird", "gun", "(manual)")
        self.project.entries.append(extra)
        suggestions = workflow.translation_memory(self.project, extra.id)
        self.assertEqual({item.translation for item in suggestions}, {"銃", "鉄砲"})
        self.assertEqual(extra.japanese, "")

    def test_glossary_updates_case_insensitively_and_persists_in_project(self):
        workflow.set_glossary_term(self.project, " Gun ", " 銃 ")
        workflow.set_glossary_term(self.project, "gun", "鉄砲")
        self.assertEqual(len(self.project.glossary), 1)
        self.assertEqual(next(iter(self.project.glossary.values())), "鉄砲")
        path = self.root / "workspace/project.json"
        self.project.save(path)
        self.assertEqual(Project.load(path).glossary, self.project.glossary)
        self.assertTrue(workflow.remove_glossary_term(self.project, "GUN"))
        self.assertEqual(self.project.glossary, {})

    def test_real_workshop_keyed_catalog_import_preserves_mod_files(self):
        source = Path.home() / ".local/share/Steam/steamapps/workshop/content/294100/3781013698"
        catalog = source / "Languages/ChineseSimplified/Keyed/Keyed.xml"
        if not catalog.is_file():
            self.skipTest("Real Workshop translation sample 3781013698 is not installed")
        before = hashlib.sha256(catalog.read_bytes()).hexdigest()
        project = Project.create(source, scan_mod(source), ["ChineseSimplified"])
        preview = workflow.preview_import(project, source)
        self.assertGreater(len(preview.changes), 0)
        expected = {node.tag: node.text for node in ET.parse(catalog).getroot() if node.text and node.text.strip()}
        workflow.apply_changes(project, preview.changes)
        imported = [item for item in project.entries if item.kind == "Keyed" and item.key in expected]
        self.assertGreater(len(imported), 0)
        for item in imported:
            self.assertEqual(item.japanese, expected[item.key])
        self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()

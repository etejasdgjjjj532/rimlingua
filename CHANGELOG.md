# Changelog

Versions follow semantic versioning. Before 1.0, minor versions may add or change
features; project-format changes require compatibility tests and explicit notes.
`rimworld_translator/version.py` is the source for package and binary versions.

## 0.4.0 — Unreleased

First public release. Development moved to the public repository (MPL-2.0).

### Interface and settings

- The interface language now follows the OS by default. If the OS language list contains English, English is used; Japanese is used when only Japanese is listed; any other language falls back to English. Preferences offer "Follow OS language", Japanese and English, so the choice can still be pinned.
- A list or dictionary in `ui_language` or `theme_mode` (hand-edited or imported settings) no longer crashes settings import or startup; the value falls back to its default.

### Cross-platform

- Saved relative paths (entry source files, provenance, selected folders, warnings) use "/" on every OS, so a project saved on Windows matches one saved on Linux.
- Export reports a case-only file name clash as such on case-insensitive filesystems (Windows, macOS) instead of an unrelated "not owned" conflict.
- The test suite runs on Windows: it pins the OS language for tests on every platform, uses long temporary paths instead of 8.3 short names, and no longer assumes POSIX path strings.

### Project and documentation

- English is the primary written language (README, guides). The Japanese README and getting-started guide are kept as `README.ja.md` and `docs/GETTING_STARTED.ja.md`.
- Added the contributor guide, the confirmed design decisions, a roadmap with known limits, and the English audit reports. Game-derived dumps and lists of other people's mods are not distributed.
- Added the Ludeon "not official, not endorsed" notice to the README and the bundled third-party notices.
- Added edge-case tests for diagnostic text, output paths and settings export/import. The known failing GUI tests are listed in the roadmap.

## 0.3.0 — Local build only

Local implementation: 2026-10-13–14. This version was built locally but never published; 0.4.0 is the first public release.

### Extraction and compatibility

- Resolve the game version's LoadFolders, the matching enabled-MOD conditions, XML inheritance, and list index/handle keys. Supported patch operations are applied to the XML being read; unsupported operations and missing reference conditions are recorded in diagnostics.
- Read C# field and translation-attribute metadata without executing game or MOD DLLs. Existing translation catalogs, inferred candidates and the evidence for each extraction are recorded.
- The GUI can now specify the game version and enabled MODs, and import the game's MOD settings read-only. Changing the conditions rescans while keeping existing translations.
- Fix DefInjected output to the game-compatible `Languages/<language>/DefInjected/<DefType>/Translations.xml`. Translations from the earlier flat XML layout are still imported.
- List items such as disease stages, mood stages and weapon tools are now extracted under the same handle-based keys as the official Japanese translation (for example `stages.withdrawal.label`). RimWorld 1.6 was confirmed in a real game run to apply numeric keys (`stages.0.label`) as well, so the point of this change is to match the official key names, not to fix numeric keys failing to apply. It applies only to versions whose game type information could be checked for the same version; other versions keep the previous numeric keys. Because the output keys change, re-exporting changes the key names of the affected items. On rescan, existing projects carry translations, reviews and approvals from the old keys over to the new keys (if several items claim the same old key, nothing is carried over and a warning is shown).
- The official output of a multi-version project changed from per-version folders plus LoadFolders to a single shared set (the root `Languages/`) read by every version (`export_shared`). Translations of the versions that are ready are merged as a union of keys; when the same key has different translations, the newer version wins and a notice is shown. Versions on hold are not included. Some items end up with both a numeric key and a handle key, but on 1.6 the handle key is what the game uses in practice. In-game behavior on older versions is unconfirmed (the older games are not available). Exporting again to an output location with the old layout removes the old per-version folders. `export_versions` (per-version output) remains in the code.
- Old Japanese and multi-language projects with `schema: 1` can still be loaded. Rescanning keeps per-language translations, source changes, obsolete items and manual keys.

### Editing and interface

- Import of existing translation MODs, language folders, XML, CSV, gettext PO and unified diff (.diff/.patch) gained a change preview, protection of existing translations, and conflict diagnostics.
- Diff import checks against an explicitly chosen base XML folder in read-only mode and previews the non-empty translations of the reconstructed XML. Deletions and empty translations do not erase current work, and mismatches, unsupported formats and conflicts are reported explicitly.
- Added per-language reviewed/approved state, item exclusion and extraction classification, a glossary, translation candidates for identical source text, and undo/redo for bulk replace and bulk operations.
- Added QA for placeholders, matching tags and attributes, line breaks, whitespace, glossary terms, mismatched and extremely short translations. Diagnostics that identify an item can jump to its edit field.
- Saving, and autosave after 60 seconds, also update the game XML. If export fails, the saved work data is kept and the interface shows that a fix is needed.
- Added a first-run guide with skip, a Workshop list searchable by name, ID and author, favorites, recent projects, Japanese/English menus, and font sizes from 8 to 24 points.
- Reworked the sidebar truncation, scrollable edit fields, splitters and keyboard operation for small screens. Added filter refresh after finishing review, exclusion or save from the editor, and **Refresh filters (Ctrl+F5)**.
- Added background scan progress and cancellation, and a cache that reduces reprocessing of unchanged XML, saving and output.
- Small encouragements while translating: when overall progress passes 25/50/75/100%, and at the 1st, 10th, 50th and 100th item of the day, a one-line message appears in the status bar for 7 seconds (no click needed, disappears by itself). It does not appear on rescan or filtering. The sidebar progress bar animates briefly while the window is visible. The wording of "今日の件数" (today's count) in the Progress tab changes with the count. See `cheer.py` and `tests/test_cheer.py`. "View > Reduce motion" stops the animation. Progress is capped at 99% while even one untranslated item remains.

### History, game and metadata

- Added browsing and restoring of local history, with a record made before each restore. Environments without Git use a file-based history; browsing past Git history requires Git.
- Added installing, updating and restoring from backup of the generated translation MOD. The source MOD and the normal game MOD settings are not modified.
- Added read-only diagnostics for required MODs and load order, an isolated launch using a copy of the game and its dependency MODs, and retrieval of a dedicated log and report.
- Added editing of the translation MOD's name, translator, description and license text, and an option to generate a preview image instead of using the source preview image.

### Windows compatibility fixes

- Fixed a problem where Windows rejected valid `Languages/Japanese/...` managed output paths. Management information is validated in an OS-independent POSIX form.
- On small screens the source and translation fields are stacked vertically so that the translation field is reachable even at 200% scaling.
- Recorded the verification scope for Wine, Windows Server and Windows 10/11 client, so that a self-test alone cannot be counted as native GUI verification.
- Fixed the character-encoding exception and the wait on an error dialog when a windowed Windows EXE forwarded Japanese diagnostics to standard output. UTF-8 reports are kept, and the JSON on standard output is ASCII-escaped so that it can be forwarded safely.
- The reports of the bundled 100%/200% EXE are verified by SHA-256 before the archive is finalized. A Wine preview is not published as a native Windows release.

### Distribution and documentation

- Added OS-specific PyInstaller onedir build procedures for Windows and Linux. Python is bundled, so normal use needs no separate Python or Git setup. A Linux x86_64 build and a Windows x64 `wine-preview` built under Wine are stored locally.
- Added a Linux tar.gz / Windows ZIP, SHA-256 checksums, a manifest of the build environment and dependency versions, a bundled-runtime self-test, and collection of licenses/NOTICE files.
- Prepared workflows for the Ubuntu / Windows native build/test matrix, 100%/200% GUI captures, and verification of layout, accessible names, keyboard operation and the bundled executable.
- Added a manual stable-release update notice that is used only when a public repository is explicitly specified and enabled. It is disabled by default and performs no automatic download or installation.
- Wrote the Japanese and English READMEs and a beginner's guide covering installation, saving/exporting, importing, restoring, app updates and in-game checks, plus copyright and the limits of verification.
- Prepared a draft release workflow and Issue templates for bug reports and feature requests.

### Verification scope

The latest Linux automated tests (208) all pass. On Windows CPython/Wine, 204 of 208 pass; the 4 that require a Linux installation source are skipped. We checked the 100%/200% GUI of the extracted native Linux build and the Windows Wine build, and saving, export and history with a PATH that has neither Python nor Git. The physical screen is 1366×768; the larger layout images are programmatic captures that include off-screen areas. They are not verification on a real 4K display or real Windows hardware.

Scanning, independent XML output checks and source-file immutability were confirmed with 19 Workshop MODs and RimWorld Core (local verification record: 20 passing inputs, unchanged sources). Unified diff imports reconstruct translation XML against an explicit read-only base, retain existing work on blank/deleted text, and expose mismatches and conflicts. Evidence was saved that six Japanese `ThingDef.label` values from real MODs were injected into an isolated real game and shown in a diagnostic `Verse.Window`. This is not the result of verifying the normal equipment screen, the whole play screen, or display in every translation language. Automated tests, runtime loading, native editor behavior and visual game proof are tracked separately.

The Windows x64 EXE/ZIP was built under Wine and is kept separate from native Windows results. Building, startup and DPI on real Windows, actual GitHub CI runs and a public download page are unconfirmed because no Windows environment or remote repository is available. The existence of a workflow is not treated as evidence that it ran. This changelog does not claim that all requirements are complete. See the local verification artifacts for milestone evidence and remaining limitations.

## 0.2.0 — prior local version

- Standalone Qt Widgets editing screen, source MOD extraction, save/export, rescan and preview.
- Saving and selecting multiple languages in a translation project, and compatibility with existing Japanese projects.
- Generate working data and the translation MOD into a separate project without modifying the source MOD.

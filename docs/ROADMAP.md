# Roadmap and status

This document tells contributors what is implemented, what is only partly done, what is not done, and what has not been verified. It is a faithful translation and condensation of the project's internal status notes, which were last updated on 2026-11-20 (the earlier distribution and platform records date from 2026-10-14). It does not claim more than those notes did.

Status marks used below:

- **done**: implemented, with automated tests and/or a recorded manual check (see the verification limits further down)
- **partial**: implemented in part, or implemented but with a verification gap
- **not done**: not implemented
- **blocked**: needs something outside the codebase (for example, a native Windows desktop)

The backlog items are candidates agreed with the maintainer, not promises. Items marked "evidence-based" were added because a real problem was found during extraction audits or GUI tests.

## 1. Implemented

### 1.1 Settings and folders

| Item | Status | Notes |
| --- | --- | --- |
| Folder settings: Steam Workshop folder, game Mods folder, additional external MOD folders (several allowed) | done | An empty field means auto-detect (the detected value is shown greyed out). Folders you specify are read-only and are used to find prerequisite MODs and to choose the source MOD. |
| Per-project output folder | done | Stored in `project.json`. Default is `<project>/mod` (`mod-test` for multi-version test output). Locations that overlap the source MOD, Workshop, the game `Data` folder, or an added MOD folder are rejected. Resolution lives in one module (`output_paths.py`). |
| `ModsConfig.xml` location (evidence-based: it used to be hard-coded) | done | Configurable; when empty, the usual location and the Proton save location are searched. Read-only. |
| Default translator name, license, target language | done | "Output" tab. If the translator name is empty, no translator name is written to `About.xml`. |
| Cache location and a "clear cache" button | done | "Extraction" tab. Clearing only removes the `game-table` and `schema` folders the editor itself created. |
| Autosave interval | done | "General" tab, 10 to 3600 seconds, 0 disables. Default 60 seconds. |
| Settings export and import | done | "General" tab. |
| Settings dialog split into tabs (General / Folders / Extraction / Output) | done | |
| Scan-count limit (100,000 items) | by design | Deliberately not user-configurable, because it is a safety limit. |
| Prerequisite MODs are discovered from the user's MOD folders | done | No downloadable list file is maintained. |

### 1.2 Extraction accuracy

| Item | Status | Notes |
| --- | --- | --- |
| Treat installed DLCs and found prerequisite MODs as active when the enabled-MOD list is unknown | done | Previously, entries with `MayRequire` / `IfModActive` were dropped entirely. The assumption is reported in diagnostics. |
| Treat single-word values used only for comparison in C# as internal values | done | Judged by value shape and field-name evidence. Word lists count as tokens only when the game's name table is available. For IL, a field is classified as internal only if it is read and used solely in comparisons across all assemblies of that MOD. Unread fields, unresolvable references (for example generic base classes) and address-of operations are never used as evidence of an internal value. |
| Check the value shape even on fields marked `MayTranslate` | done | File paths, Def names, Keyed keys and similar are not offered as candidates. |
| Duplicate keys caused by English DefInjected folder names differing from the extraction group names | done | For catalogs without a namespace, entries are merged into one item per key. |
| Do not downgrade a Def's own name/description to "needs review" when the parent Def or prerequisite MOD is missing | done | |
| Exclude comma-separated grids (for example terrain/roof grids) by value shape | done | This used to produce thousands of false candidates in large content MODs. |
| Pick up text that has evidence but was missed (`helpText`, name-triple names, `endMessage`, `shortLabel`, and so on) | done | `LoadAlias` entries and `helpText` / `endMessage` / `shortLabel` on Defs of classes that cannot be read are collected as unverified candidates. Known text-field name variants on legacy-framework Def classes get the same treatment. Measured on a sample, not on all MODs. |
| Framework-specific judgement tables moved from code to a data file (`assets/field_contracts.json`) | done | |
| Per-row reasons why an item is or is not a target (official translation, attribute, other-language translation, Keyed) | done | Shown in each row's "Technical details"; each item carries machine-readable `reasons`. |
| Manual per-row include/exclude override, saved in the project | done | "Toggle exclusion for this item" and "Change extraction classification". Excluded rows show a marker in the list. |
| Policy: no blacklist by MOD name or framework name | policy | Decisions use general evidence so that unfamiliar MODs are handled the same way. |
| Core extraction from the earlier milestones: XML inheritance, `LoadFolders` version conditions, `PatchOperation` handling, `li` list paths and stable keys, nested-field and Def-type schema from the game's metadata, per-field confidence and evidence, manual classification, comparison against existing real translation files | done | Metadata is read without executing any code. Static candidates are not a claim of complete UI coverage. DLL-origin or dynamic text is surfaced as unextractable / needs manual review instead of being guessed. |

### 1.3 Translation workflow

| Item | Status | Notes |
| --- | --- | --- |
| Glossary: automatic term candidates and inconsistency warnings | done | Term candidates are collected from translated items and shown in the candidates tab; a "variations" tab in the glossary lists inconsistent renderings. |
| Translation memory across projects | done | On each save, error-free translations are remembered in `translation-memory.json` in the settings folder and offered as candidates in other projects. |
| Official translations as candidates | done | Translations from the game's bundled language pack appear as "official" candidates and in empty fields. Never applied automatically. |
| Apply one translation to all rows with the same source text | done | Rows that already have a different translation are left alone; the batch change can be undone. |
| Placeholder insertion helper (`{0}`, `[PAWN_nameDef]`, ...) | done | Buttons below the edit field insert the source's symbols; breakage is caught by QA. |
| Length hint for short fields (such as button labels) | done | Shows "width N / target M". |
| Preview of line breaks and color tags | done | "Preview" tab in the side panel. |
| Filtering | done | Status (including "has QA errors"), Def type, source file, note marker, and assignee (shown only once an assignee is set). |
| Keyboard-only navigation to the next untranslated item and confirm | done | Ctrl+J, Ctrl+Shift+J, Ctrl+Shift+Return, Ctrl+K. |
| Notes with markers ("review later", etc.) | done | "Notes" tab; four marker types; notes are never exported. |
| Progress display, including a names-and-descriptions-only completion rate | done | Shown in the sidebar. |
| Batch editing and find/replace with preview and undo; import of existing translation mods; CSV and gettext PO import/export | done | CSV has a detailed-columns export and imports Shift_JIS / semicolon / tab variants. PO supports notes, previous source text and fuzzy flags. |
| Per-language reviewed/approved state, retained after rescan | done | |
| Autosave and explicit save plus export workflow | done | |

### 1.4 Quality checks and export

| Item | Status | Notes |
| --- | --- | --- |
| Detect lines whose source text changed after a MOD update and mark the old translation | done | "Source changed" state and a QA tab. |
| Placeholder / tag / line-break count mismatch against the source | done | Placeholder and tag errors block export; line-break mismatches are warnings. |
| Mixed full-width/half-width characters, half-width katakana, inconsistent sentence endings and style | done | QA "notation and style" tab. This check is written for Japanese output. |
| List of empty or source-identical translations | done | |
| Run all checks together before export | done | QA (Ctrl+Shift+K) and an export review (Ctrl+E). Rows marked confirmed but still containing errors are caught, and "mark as confirmed" refuses rows that still have errors. |
| Export diff (files added, changed, removed) | done | Shown in the export review. |
| Number of backup generations | done | "Output" tab; oldest are removed first. The Git history is not rewritten. |
| History restore for multi-version projects | done | Evidence-based: restoring from history used to break the multi-version output; it now regenerates it. Restoring writes to the configured output folder. |
| Workshop publication text template | done | Saves title, BBCode description, change notes, pre-publish checks and tags. Publication itself is never done by the tool. |
| Safe install / update / backup / restore of the generated translation MOD into the game's Mods folder, without modifying source MODs | done | Regression-tested against disposable game folders. The GUI shows the exact plan before acting. |
| Load-order and missing-source-MOD diagnostics; unmet-dependency explanations | done | |

### 1.5 Multi-version support

| Item | Status | Notes |
| --- | --- | --- |
| Carry translations across versions (with preview) | done | Reviewed/approved states are not carried over. |
| Compare versions | done | "Compare versions". |
| Version status dialog | done | Explicitly shows "game not registered", "not extracted", and "load rules unverified" (for version 1.0, which is absent from the game library). |
| Test output to `mod-test/` | done | Available from the GUI. |

### 1.6 Prerequisite MODs and collaboration

| Item | Status | Notes |
| --- | --- | --- |
| Missing prerequisite MOD list (name, packageId, Workshop link) with copy | done | Project menu, "Prerequisite MODs". |
| Existing translations of prerequisite MODs shown as reference candidates | done | Matched by same key and same Def. |
| Per-prerequisite dependent-row counts | done | |
| Compare against another translation MOD | done | |
| Single-file project bundle (`.rwtbundle`) export/import | done | The receiver chooses their own source MOD. Import rejects everything under `mod/` except `About`, `Languages` and `LoadFolders.xml`, and never overwrites existing files. |
| Per-file assignee records and filter | done | |

### 1.7 Performance and safety

| Item | Status | Notes |
| --- | --- | --- |
| Scan runs in the background, with progress and cancel | done | |
| Filtering and display speed-ups | done | On a 50,000-row project, search takes roughly 0.6 to 1.3 s (previously 2.4 to 6.8 s). Measured on one machine; not a general guarantee. |
| Reuse of the previous result when nothing changed | partial | See section 2. |
| Write protection extended to folders added in settings | done | |
| Problem-report text includes a settings summary without paths or translation text | done | |
| Corrupted settings file: keep the broken file aside and start with defaults | done | Files other than `project.json` are never renamed even if they cannot be opened. |

### 1.8 English UI

| Item | Status | Notes |
| --- | --- | --- |
| English menus and the newer panels (tabs, filters, next-untranslated, names-and-descriptions rate, exclusion marker, reasons, variation tab, prerequisite MOD dialog) | done | Language switching redraws the UI. |
| UI language follows the OS language by default, preferring English when English is among the OS languages | done | |
| Some strings still in Japanese | partial | Some QA messages produced by the QA module are still Japanese. Some older dialogs were also recorded as Japanese in earlier notes; re-check before relying on this being fully English. |

### 1.9 Distribution and developer tooling

| Item | Status | Notes |
| --- | --- | --- |
| Auto-detect Steam paths on Linux and Windows; custom / non-Steam folders selectable | done | Windows discovery is covered by fixtures; it has not been run on a real Windows machine. |
| Linux portable build, no Python or Git required on the user's machine | done | Frozen self-test and GUI edit/save/export/history checks at 100% and 200% scaling on native Wayland, with Python and Git off `PATH`. |
| Windows x64 EXE and portable ZIP | partial | Built and checked locally, but only under Wine, which is supplementary evidence and not a native Windows run. |
| Automated multi-OS CI build/test matrix | blocked | A workflow is configured and passes a workflow linter, but it has never been executed on a hosted runner, and no native Windows GUI run has happened. |
| Downloadable release artifacts and release workflow | partial | Local artifacts and checksums exist; hosted release has not been run. |
| DPI scaling and high-resolution verification on both OSes | partial | Only 100% and 200% on a 1366x768 physical screen (Linux native, Windows under Wine). Larger requested geometries are not proof of a real 4K display. |
| Git-free file-based history; GUI browsing and restoring of snapshots | done | |
| Setup, workflow, migration and upgrade documentation, issue templates, semantic versioning, changelog, opt-in release-update check | done | Update publishing is disabled by default. |
| Developer audit tooling: key audit and recall/precision measurement, validation-corpus builder, dependency benchmark | done | These are developer tools and are not part of the product. See the measured figures in section 3. |
| First-run tutorial with a skip option, accessible tab order, adjustable fonts, compact layout, fast source picker, favorites/recent projects | done | |

## 2. Partial or not done

- **Lazy loading of rows for very large MODs: not done.** Rows are not loaded lazily. Instead, wasteful filtering and display work was reduced (see 1.7).
- **Incremental rescan of only changed items: partial.** If nothing changed since the last scan, the previous result is reused as-is, and the number of files and assemblies that did not need re-reading is recorded in the statistics. A rescan that re-extracts only the changed items is not implemented.
- **Native Windows verification: blocked.** Needs access to a licensed Windows 10/11 desktop or an approved hosted runner.
- **Hosted CI and release runs: blocked** for the same reason.
- **High-resolution display proof: partial** (see 1.9).
- **English UI completeness: partial** (see 1.8).
- **Known failing tests.** The latest full run (`python tools/run_tests.py`, offscreen Qt, interface language pinned to Japanese) executed 1,408 tests with 6 failures and 1 skip. Five of the failures are GUI layout or keyboard-flow tests (detail pane on a 1366x768 screen, a compact window on a small HiDPI screen, an elided long output path, English controls and font preferences, and closing/reopening the trial report); the sixth is a diagnostic-search keyboard test. They fail identically without the most recent changes, so they predate them, and their causes have not been investigated. Failures like these can depend on screen size, fonts and the offscreen Qt platform, so a failure on one machine is not proof of a regression; compare against the previous run.

## 3. Known limits and unverified areas

- **Static analysis is not in-game behaviour.** Extraction relies on reading XML and the game's and MODs' .NET metadata without executing any MOD code. A candidate being extracted does not prove the text appears to players; a candidate being skipped does not prove it never does. Text that cannot be shown to be player-visible stays "unverified" and is kept out of formal exports.
- **Priorities.** Extraction is deliberately focused on player-visible item names, descriptions and player-facing UI. Highly MOD-specific, complex dynamic text is only translated when reliable evidence shows it reaches the player and shows a safe translation and output route. The project does not try to extract every internal string.
- **Measured figures come from a sample, not the full corpus.** On a sample of 120 MODs, the audit tool measured a recall of 85.09% and a precision of 99.38% against official and other-language translations used as the reference answer. The remaining misses, 11 additional items newly judged to be internal values, and 3 missed official-pattern items were not examined key by key. This is not a result for all MODs, and the reference translations themselves are not guaranteed to be complete.
- **Catalog union is not a completeness claim.** Earlier comparisons against real installed inputs showed large gains in coverage (for example, core DefInjected entries 6,415 to 16,858 on one comparison, and a static-catalog exact coverage of 56.79% rising to 87.58% on one large MOD), but those were measured on a small set of installed inputs and do not mean 100% coverage.
- **In-game checks are small.** A check in an isolated copy of the game covered 5 MODs: no new items in the Translation Report, and 12 of 13 expected displays confirmed. The one that did not display was caused by an error in the game bridge used for testing, not necessarily by the translation. An earlier check rendered six MOD labels in a diagnostic window (six of six matched). Normal gameplay screens and other fields were not checked. No real Wayland screen run for the newest changes and no Windows run was done.
- **Automated tests do not cover real gameplay.** Test counts in older status records (for example 191, 204, 208) refer to the state at that time and are historical.
- **Performance figures are from one low-power machine** (an older Intel integrated GPU, 8 GiB RAM, with bounded-process tests of 30,000 entries across 3 languages). They are indications, not guarantees.
- **Version 1.0 load rules are unverified**, because that version is absent from the game library.
- **Windows is unproven natively** (see sections 1.9 and 2).
- **Source protection.** The editor treats source MODs, the game installation, Workshop content and saves as read-only. Nothing here implies that tests were run against those in a way that could modify them.

## 4. Ideas not yet decided

These came up in discussion and have no commitment or design yet. Items 1 to 3 are the concrete open work; the remainder are open for discussion.

1. Lazy row loading for very large MODs.
2. Incremental re-extraction of only changed items.
3. Native Windows build, test and DPI verification, plus a hosted CI run.
4. Key-by-key review of the remaining audit misses and the newly judged internal values, followed by further rule refinement backed by independent evidence.
5. Fully English UI, including QA messages and any dialogs still in Japanese.
6. Wider in-game verification of displayed text, across more MODs and normal gameplay screens.

Constraints to keep in mind for any of these: no blacklists by MOD or framework name, no execution of MOD code, and source folders stay read-only.

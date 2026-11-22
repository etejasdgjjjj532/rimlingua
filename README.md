# rimlingua

*A multilingual translation editor for RimWorld mods.*

[日本語](README.ja.md) · [Getting started](docs/GETTING_STARTED.md) · [Installation and builds](docs/DISTRIBUTION.md) · [Changelog](CHANGELOG.md)

A standalone desktop app for reading a source MOD, editing translations in your chosen languages, and generating a separate translation MOD. You enter translations or import existing work. The source MOD stays unchanged; project data and game files live in a separate folder.

**Portable builds do not require a separate Python, Git, or VS Code installation.** You still need RimWorld and the source MOD. Menus support Japanese and English; translation targets include 29 languages.

## Your first translation

1. Launch the app and choose **File → New translation**. Search installed Workshop MODs by name, ID or author, add favorites, or choose a local source folder.
2. Review target languages, extraction game version and active MODs, then choose a project folder separate from the app and source MOD. The usual suggested location is `Documents/RimWorldTranslations/`. The generated translation MOD is written to `mod/` inside the project folder unless you choose another output folder for that project with **Project → Set output folder**. The source MOD, the Steam Workshop folder, the game's `Data` folder and MOD folders added in Preferences are refused as output folders.
3. Select an entry and type in the lower translation editor. **Save and export (Ctrl+S)** saves project data and updates game XML. After a pause in editing, the app also attempts to save and export (60 seconds by default; set 10–3600 seconds, or 0 to turn it off, under **Help → Preferences and game paths → General**). To look at the result before anything is written, use **File → Export translation mod (Ctrl+E)**.
4. Review **Project → Quality check… (Ctrl+Shift+K)** and **Project → Extraction and QA**, then use **Game → Install or update translation MOD** to review the installation. In RimWorld, enable both the original and translation MOD and load the translation after its source.

If export fails after project data was saved, your saved work remains available. Fix the reported diagnostics and save again. Saving does not update a translation already installed in the game: run **Install or update** again.

The [getting-started guide](docs/GETTING_STARTED.md) covers choosing a source, testing in game, imports and recovery.

## Startup and distribution status

The current version is **0.4.0**, the first public release. Portable builds for Linux x86_64 and Windows x64 are produced by the release workflow and attached to GitHub Releases. Native Windows startup and DPI on real hardware have not been verified yet.

The local Linux bundle is `dist/linux-current/RimWorldTranslationEditor/`. Keep the whole folder and launch its executable:

```bash
./dist/linux-current/RimWorldTranslationEditor/RimWorldTranslationEditor
# Open an existing project
./dist/linux-current/RimWorldTranslationEditor/RimWorldTranslationEditor /path/to/project/project.json
# Check the portable version and bundled runtime
./dist/linux-current/RimWorldTranslationEditor/RimWorldTranslationEditor --version
./dist/linux-current/RimWorldTranslationEditor/RimWorldTranslationEditor --self-test
```

Keep `_internal/` alongside the executable. Linux also needs a compatible glibc and a graphical desktop. The actual build environment is recorded in `release-manifest.json`. See [installation and builds](docs/DISTRIBUTION.md) for extraction, Windows preparation and native build commands.

## Available tools

- **Multiple languages:** translations and reviewed/approved states are stored per language. Rescanning preserves matching keys and identifies changed source text and removed entries. **Mark reviewed** is refused for a row that still has a QA error (for example broken placeholders or tags), and such rows are not counted as reviewed in the progress figures.
- **Import and exchange:** preview imports from translation MODs, language folders, XML, CSV, gettext PO and unified diffs (.diff/.patch). Diffs require an explicitly chosen, read-only base folder containing the original XML. Different existing translations are protected by default. CSV import reads UTF-8 and Excel's Shift_JIS, with comma, semicolon or tab separators. **File → Export CSV** writes all selected languages, and **Add detail columns** adds source file, status, previous English and note. **Export PO** writes the current language and always carries notes, the previous English and fuzzy flags. **Match another translation MOD…** compares another person's translation MOD with yours and lets you review what to import.
- **Batch work and suggestions:** preview translation replacements and undo/redo imports or batch replacements. The **Suggestions** tab beside the editors lists earlier translations of the same source, official translations, existing translations from prerequisite MODs and glossary terms (insert with Ctrl+Shift+1 to 3). Under the editors, buttons insert the source's placeholders such as `{0}`, and short fields such as button labels show a width hint. **Edit → Glossary** has an **Inconsistent terms** tab that finds English terms translated more than one way. The **Notes** tab keeps a note and a flag (for example "Review later") per entry, and **Project → Assign files to translators…** records who handles which source file.
- **Filters and progress:** filter the table by state (including **Has QA error**), Def type, source file and note flag. Ctrl+J and Ctrl+Shift+J jump to the next untranslated row or next row needing review, Ctrl+Shift+Enter marks the row reviewed and moves on, and Ctrl+K toggles the "review later" flag. The sidebar shows overall progress and, separately, progress on item names and descriptions only.
- **Extraction context:** select the game version and active MODs for LoadFolders and conditional entries. Importing game MOD settings (`ModsConfig.xml`) is read-only; its location can be set in the **Folders** tab of Preferences, and Linux Proton prefixes are searched automatically. For a MOD that declares several game versions, **Project → Version states…**, **Carry translations to another version…** (with a preview; review and approval are never carried) and **Compare versions…** show how the versions differ. Trial output for several versions goes to `mod-test/`.
- **Diagnostics:** check placeholders, paired tags, line breaks, whitespace, glossary terms and inconsistent translations. Diagnostics are written in plain language with the original developer text folded under **Technical details**. Double-click diagnostics with an identifiable entry to navigate to it. The technical details of a row also say **why the row is a translation target**, and manually excluded rows carry a ⊘ mark in the table. **Project → Prerequisite MODs…** lists missing prerequisite MODs with name, packageId and Workshop link, and shows how many rows depend on each MOD that was found.
- **Quality check and export review:** **Project → Quality check… (Ctrl+Shift+K)** gathers errors, rows whose source changed, style problems (mixed full/half-width characters, half-width kana, text left as the source, inconsistent sentence endings or politeness), untranslated rows and rows reviewed despite errors. **Export translation mod (Ctrl+E)** shows the check results and the before/after file changes first, and does not write while errors remain.
- **Installation and testing:** install generated translations and back up previous packages before updates. Read dependency/load-order diagnostics and test a disposable game copy.
- **History:** save local snapshots and restore them through the GUI; the number of generations kept is set on the **Output** tab of Preferences. A file backend works without Git; reading older Git checkpoints still requires Git.
- **Display and preferences:** **Help → Preferences and game paths** has four tabs: **General** (language, theme, 8–24 point font, autosave interval, settings export/import), **Folders** (Workshop, game Mods and extra MOD folders, and the `ModsConfig.xml` location, all read-only), **Extraction** (game paths, game library, C# metadata inspection, cache location and clearing) and **Output** (default translator, license and target languages, backup generations). Compact windows hide the sidebar and use menus and scrolling. Qt's own buttons and file dialogs follow the interface language, as do the newer controls (the Suggestions and Notes tabs, the Technical details button, the Def type, file, flag and assignee filters and the Next untranslated / Next needs review jump buttons). A few diagnostic messages produced by the QA checks may still be Japanese.

## Project data and compatibility

```text
RimWorldTranslations/Example-JP/
  project.json
  .git/ or .history/                  Local history
  mod/                                Default output folder (can be changed; multi-version trial output is mod-test/)
    .rimworld-translator.json         Generated-file inventory
    About/About.xml
    About/Preview.png
    Languages/Japanese/
      DefInjected/ThingDef/Translations.xml
      Keyed/Keyed.xml
```

Existing Japanese and multilingual projects using `schema: 1` remain readable. Back up or move the **whole project folder**, including hidden history folders. The project records the original source path; rescanning needs that source MOD. To hand a project over as a single file, use **File → Export project bundle…** to create a `.rwtbundle` (translations, review states, glossary, notes, assignments and versions; the generated MOD is optional and the source MOD's location is never included). The receiver uses **Import project bundle…** and chooses their own copy of the same source MOD. History (`.git/`, `.history/`) is not included.

To upgrade, save and back up the project, then replace the application folder with the new version. Keep separately stored projects and retain the previous app while verifying that the new version can open, edit, save and export them.

Update checks are disabled by default. After you configure a real, published GitHub `owner/repository` and opt in, **Help → Check for updates** can notify you of a newer stable release. There is no periodic polling, automatic download or installation. An unconfigured repository causes no network request.

## Extraction and verification limits

Extraction uses version-specific LoadFolders, XML inheritance, supported patch operations, list keys, existing translation catalogs and C# field metadata. DLL metadata is read without executing DLLs. When information is missing, the app uses field-name heuristics and displays the evidence and warnings.

Dynamically generated text, strings embedded in DLLs, custom patches and content requiring other MODs' conditions or definitions are not fully reproduced. This is not a runtime text dump and does not guarantee complete extraction or compatibility with every MOD. Untranslated entries fall back to original text. Conflicting duplicates, removed entries and manually excluded entries are omitted. Review/approval is not a prerequisite for export. Placeholder or recognized-tag errors block export of the entire MOD, including all selected languages.

Verification has distinct scopes:

| Verification | Evidence and limits |
| --- | --- |
| Automated checks and real MOD inputs | 19 Workshop MODs plus Core passed scanning, independent XML output checks and source-integrity checks. This does not establish full extraction coverage or game-screen rendering. |
| Actual Linux RimWorld runtime | Generated Japanese `ThingDef.label` values from six real MODs loaded and appeared in a diagnostic `Verse.Window` inside isolated RimWorld. Normal equipment/building/gameplay screens and all target languages were not verified. |
| Native Linux editor | The latest archive was extracted outside the repository and tested with Python/Git off PATH on Wayland at 100%/200%: edit, save, export, file history, compact scrolling and Ctrl+S. The physical display is1366×768. |
| Windows Wine preview | The actual extracted x64 EXE passed the same100%/200% checks under Wine with Python/Git off PATH. This is not native Windows or Windows game-internal UI evidence. |
| Windows, CI and published release | Scripts/workflows are prepared. Native Windows and a remote repository are unavailable, so actual runs and published downloads remain outstanding. |

Latest extracted-binary reports are `artifacts/linux-portable-current-verification/archive-report.json` and `artifacts/windows-portable-verification/archive-report.json`. Real-MOD reports are `artifacts/installed-verification-final.json` and `artifacts/sol-runtime/runtime-ui-report.json`; the game screenshot is `artifacts/sol-runtime/isolated-run/game-translation-proof.png`. These game/MOD-derived artifacts are not bundled for distribution. Read the reports for actual final results.

## Run or develop from source

Source development needs Python 3.11+ and dependencies. See [development and isolated verification](docs/DEVELOPMENT.md). Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
./run.sh
# Existing project
./run.sh /path/to/project/project.json
# Equivalent entry points
.venv/bin/python -m rimworld_translator
.venv/bin/python run.py
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install '.[dev]'
.venv\Scripts\python.exe -m rimworld_translator
```

On Linux, `./install-launcher.sh` installs a user desktop launcher for the source environment at `~/.local/share/applications/rimworld-translator.desktop`. This is separate from portable installation.

```bash
.venv/bin/python tools/run_tests.py
.venv/bin/python tools/run_tests.py --script tools/smoke_gui.py
.venv/bin/python tools/verify_installed.py --report artifacts/installed-verification-final.json
.venv/bin/python tools/build_portable.py --dry-run
```

Real-input verification requires an installed game and Workshop MODs; use `verify_installed.py --game /path/to/RimWorld` for a custom location. Native GUI/DPI and portable build commands are in [installation and builds](docs/DISTRIBUTION.md).

## Copyright and reporting problems

Edit the exported MOD name, translator, description and translation-license text under **Project → Translation MOD metadata**. **File → Workshop material…** writes a title, a BBCode description, a changelog, a pre-publish checklist and tags as text files for you to edit. The editor never publishes anything; publishing is manual. Uncheck **Use source artwork** to generate an independent background with language flags instead of adapting the original preview.

Normally, distribute only the generated translation MOD folder (`mod/` by default). Source DLLs and English XML are not copied. Check the original author's terms before publishing project data/history containing source text or artwork derived from the original preview. Flags use the [flag-icons MIT license](rimworld_translator/assets/flags/LICENSE); bundled libraries are described in [third-party notices](packaging/THIRD_PARTY_NOTICES.md). The editor itself is released under the [MIT License](LICENSE). It is an unofficial fan tool, not affiliated with Ludeon Studios; RimWorld is their trademark. No game files are bundled: the class and field name table read from the installed game is created in the user's own cache and is not part of the distribution. The cache location can be changed on the **Extraction** tab of Preferences, and **Clear cache…** removes only the `game-table` and `schema` folders the editor created there.

Use **Help → Copy diagnostic information** and report reproduction steps, expected behavior and actual results to the author. No public Issues URL is configured yet. [Bug-report](.github/ISSUE_TEMPLATE/bug_report.yml) and [feature-request](.github/ISSUE_TEMPLATE/feature_request.yml) templates are ready for a future repository. See [troubleshooting](docs/GETTING_STARTED.md#troubleshooting) for recovery and reporting details.

## License

Mozilla Public License 2.0 (see `LICENSE`). Copyright (c) 2026 goma.

## Disclaimer

Portions of the materials used to create this content/mod are trademarks and/or copyrighted works of Ludeon Studios Inc. All rights reserved by Ludeon. This content/mod is not official and is not endorsed by Ludeon.

This is a community-made tool and is distributed free of charge.

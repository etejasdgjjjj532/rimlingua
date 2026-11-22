# Getting started

[English README](../README.md) · [日本語ガイド](GETTING_STARTED.ja.md) · [Installation and builds](DISTRIBUTION.md)

Read a source MOD, enter translations and create a separate translation MOD. This is a translation editor, not an automatic translation service. You do not need to edit XML or use Git.

## 1. Open the app

### Linux portable build

Extract or copy the **whole folder** from the tar.gz or local `dist/RimWorldTranslationEditor/` build. Open `RimWorldTranslationEditor` inside it. If your file manager prevents execution, enable executable permission in the file's properties.

From a terminal:

```bash
cd /path/to/RimWorldTranslationEditor
chmod +x RimWorldTranslationEditor
./RimWorldTranslationEditor
```

Keep `_internal/` beside the executable. Linux needs a compatible glibc, a graphical desktop and fonts. The actual build environment is in the included `release-manifest.json`.

### Preparing a Windows portable build

When a Windows ZIP is provided, right-click it, choose **Extract All**, then open `RimWorldTranslationEditor.exe`. Do not launch from inside the ZIP. Keep every file, including `_internal/`.

There is no public download page yet. A Windows x64 EXE is included in the local `wine-preview.zip` under `dist/windows-wine/`. It was built under Wine for supplementary checks; native Windows startup and DPI remain unverified. Treat it as a preview rather than a native-Windows-verified release.

### Source installation

See the [README](../README.md#run-or-develop-from-source) for source setup. Portable users do not install Python, Git or VS Code separately.

The interface starts in Japanese. Select **Help → Preferences and game paths**, set **Interface language** to **English**, then confirm. This changes the menus, independently of your MOD's target language. Qt's own buttons and file dialogs follow the interface language too. The newer controls (the **Suggestions** and **Notes** tabs, the **Technical details** button, the Def type, file, flag and assignee filters, and the **Next untranslated** / **Next needs review** buttons) switch with the language too. A few diagnostic messages produced by the QA checks may still be Japanese.

Use **Skip guide** to dismiss the welcome guide. **Help → Show getting-started guide** displays it again.

## 2. Choose a source and target languages

1. Choose **File → New translation** or **Start a translation**.
2. Choose **Choose from Steam Workshop** or **Choose a local folder**.
3. Search Workshop MODs by name, ID, author or packageId, and check the preview and author. Use **Toggle favorite** and **Favorites only** for frequently used sources.
4. Check at least one target language. A single language or multiple languages can be selected.
5. Review **Game version and active MODs**, then choose **Scan with these conditions**.
6. Review the proposed project location and select **Create here**. **Choose another folder** selects another empty folder.

Typical suggested folders are `Documents/RimWorldTranslations/<MOD-name>-JP/` for Japanese or `<MOD-name>-Translations/` for multiple languages. Keep projects outside the application, source MOD, game and Workshop folders.

```text
Application folder         Replace when upgrading the app
Translation project        Keep project.json, history and generated mod/
RimWorld Mods folder       Install the generated translation here
```

The app searches common Steam paths and additional libraries. If detection fails, choose a local source folder. You can also set the Steam Workshop folder, the game Mods folder and any number of extra MOD folders under **Help → Preferences and game paths → Folders**. Leave a field empty to auto-detect it; folders you set are read-only and are used to choose a source MOD and to look for prerequisite MODs. The app does not download MODs or change Workshop subscriptions.

Under **Help → Preferences and game paths → Extraction**, you can enter a game folder containing `Data/Core/` and the RimWorld executable, one path per line. Do not enter `Mods/` or a Workshop folder here. Finding the game also helps inspect C# field metadata. Preferences has four tabs: **General** (interface language, theme, font size, autosave interval, **Export settings…** / **Import settings…**), **Folders**, **Extraction** (game paths, game library, cache location and **Clear cache…**, which removes only the `game-table` and `schema` folders the editor created) and **Output** (default translator, license and target languages, and the number of backup generations).

Extraction settings select a RimWorld version, such as 1.6, and active MODs. Available game MOD settings are read as initial suggestions; **Read game MOD settings** lets you choose another `ModsConfig.xml`. The `ModsConfig.xml` location can also be set under Preferences → Folders; when it is empty, the usual location is used and, on Linux, Steam's Proton prefixes are searched too. This is read-only and does not enable MODs or change the game configuration. Choose **Active MODs unknown** if you do not know the conditions; conditional entries are then warned about and excluded.

Later, **Project → Game version and active MODs** changes these conditions and rescans while retaining translations by matching keys. Available active MOD definitions also provide context for inheritance and patch interpretation.

When the source MOD declares several game versions, you can switch the version being edited. **Project → Version states…** shows each version's state (Ready, No library game, Not scanned, Load rules unverified) and whether it is part of the formal export. **Carry translations to another version…** lists what would be copied before anything is written; you choose whether to include rows whose English differs or to replace existing translations, and review and approval are never carried. **Compare versions…** lists the row, English and translation differences between two versions. The test output made by **Versions → Export declared versions for testing** goes to `mod-test/` in the project, and **Project → Last trial output result** reopens the latest result.

While scanning, the status bar shows file and candidate counts. **Cancel scan** stops the scan and preserves the currently open project's translations.

## 3. Translate and save

Select an entry to show its English source and lower translation editor. The source is read-only. Type your translation below or edit its table cell.

**Target language** switches the language being edited and preserves other languages' work. **Manage languages** controls which languages are exported. Deselecting a language keeps its project data but removes its previously generated XML at the next export.

Search matches source text, translations, keys and source files. Combine it with the state filter (which includes **Has QA error**), the Def type filter, the source-file filter, the note-flag filter or **Find untranslated**. There is no filter by assigned translator on screen. Use **Edit → Refresh filters (Ctrl+F5)** to refresh the displayed results.

The **Next untranslated** (Ctrl+J) and **Next needs review** (Ctrl+Shift+J) buttons in the filter row jump to the next matching row without changing the filters. Once files are assigned to translators (**Project → Assign files to translators…**), an **All assignees** drop-down appears in the filter row to show only one translator's files. **Ctrl+Shift+Enter** marks the row reviewed and moves on, and **Ctrl+K** toggles the "Review later" flag. The **Suggestions** tab beside the editors lists earlier translations of the same source, official translations, existing translations from prerequisite MODs and glossary terms; insert one with Ctrl+Shift+1 to 3. The **Notes** tab keeps a note and a flag (Review later, Question, Check in game, Done for now) for each entry; notes are never exported. Under the editors, buttons insert the source's placeholders and short fields show a width hint.

The sidebar shows overall progress and, separately, **Names and descriptions**: progress on item names and descriptions only, which is what players read first. **Project → Assign files to translators…** records a translator name per source file.

### Saving and exporting

- **File → Save and export (Ctrl+S)** saves `project.json`, updates the project's `mod/` folder and records local history if content changed.
- Autosave attempts the same operation after a pause in editing. The default is 60 seconds; under **Help → Preferences and game paths → General**, **Autosave interval** can be set to 10–3600 seconds or to 0 (**Autosave off**). Before closing, use Ctrl+S and check the result.
- **Export translation mod (Ctrl+E)** first opens **Review before export**. It shows the check results and the file changes (added, changed, removed), and **Export** stays disabled while errors remain; **Open quality check** takes you to the problem rows. After you confirm, it regenerates game files and saves project data.
- **Open output folder** opens the folder of the generated translation MOD: `mod/` in the project by default, `mod-test/` for a project with trial output of several versions, or the folder you chose with **Project → Set output folder**.

Output folders are chosen per project. The source MOD, the Steam Workshop folder, the game's `Data` folder, MOD folders added in Preferences, and the project folder itself (or a folder containing it) are refused. Inside the game's `Mods/`, only a separate folder directly in it (for example `Mods/MyTranslation`) can be chosen. **Use default** restores the original location.

If project saving succeeds but export fails, the saved work remains. A message such as **Project saved. Fix diagnostics before updating game XML** means the current `mod/` must not be treated as the latest translation. Fix the diagnostics and save again. Switch to the language named in the error if it is not the current target. **Project → Quality check… (Ctrl+Shift+K)** groups errors, rows whose source changed, style findings, untranslated rows and rows reviewed despite errors into tabs; click a row to jump to it.

Untranslated entries are omitted so the game falls back to its original text. Partial translations can be installed. Conflicting duplicates, removed entries and manually excluded entries are also omitted.

## 4. Review states and diagnostics

| State | Meaning |
| --- | --- |
| Untranslated / Translated | Indicates whether a translation is present. |
| New | Filters entries added by rescanning, among other new candidates. |
| Source changed | The source changed; the earlier translation is preserved for review. |
| Needs review | Extraction uncertainty or a translation issue needs attention. |
| Reviewed / Approved | Records your review for the current language. Changing the translation or source clears review/approval. A row that still has a QA error cannot be marked reviewed and is not counted as reviewed in the progress figures. |
| Removed | No longer present in the source. Work is retained but not exported. |
| Excluded | Manually omitted from exports. Exclusion applies to the whole entry, across languages. |

After reviewing the source and translation, choose **Edit → Mark reviewed** or **Mark approved**. If a QA error (for example broken placeholders or tags) remains, the reason is shown and the row is not marked reviewed; fix it and try again. These states do not verify game rendering or grant permission to publish. Neither review nor approval is required for normal export.

Open **Project → Extraction and QA**. Diagnostics are written in plain language, saying what happened and what to do; the original developer text is folded under **Technical details**. Double-click a diagnostic that identifies an entry to navigate to it; select a diagnostic to read its suggested fix.

In the editor, the technical details of a row (the **Technical details** button) also say **why the row is a translation target**, for example that an official translation covers the same Def type and field, that the field carries a translation attribute, or that the English Keyed catalog lists it. In the table's last column, a manually excluded row shows ⊘, a row with a flag shows ⚑ and a row with only a note shows ✎; the tooltip shows the details.

- Preserve the types and counts of placeholders such as `{0}` and `{PAWN_nameDef}`.
- Preserve paired tags and attributes such as `<color=red>...</color>`. Placeholder or recognized-tag errors block export.
- Line breaks, whitespace, very short translations, glossary mismatches and inconsistent translations are advisory warnings. Check whether the difference is intentional in context.
- The **Style** tab of the quality check lists mixed full-width and half-width characters, half-width kana, translations left identical to the source, and inconsistent sentence endings or politeness style. These are advisory too.
- The **Inconsistent terms** tab under **Edit → Glossary** lists English terms the project translates in more than one way. Click a wording to visit the rows that use it, and use **Register the selected wording in the glossary** to adopt it.

The detail panel's `schema` confidence uses C# field information, `catalog` uses existing translation catalogs, and `heuristic` uses a best-effort inference. Evidence type is not a correctness guarantee. Custom C# behavior, patches and other-MOD conditions may leave text unextracted.

Use **Edit → Toggle entry exclusion** or **Classify candidate** for a false positive. **Add manual key** is an advanced aid when you know an exact RimWorld key; you do not need to guess missing keys.

## 5. Install in RimWorld

1. Close RimWorld, save your work and review diagnostics.
2. Choose **Game → Install or update translation MOD**.
3. Select the detected game, or choose the game root if it was not found.
4. Review the destination, file count and install/update actions, then confirm.
5. Start RimWorld and enable the original MOD, required dependencies and translation MOD. Load the translation after its source.
6. Select the translated language in the game and inspect the actual screen containing the translated entry.

Only generated translation files are copied to the game's local `Mods/`. The source MOD and normal `ModsConfig.xml` stay unchanged; `ModsConfig.xml` is only read, from the location set in Preferences or from a Proton prefix. Enable MODs yourself inside RimWorld. For manual installation, copy the whole generated `mod/` folder.

**Game → Dependencies and load order** reads available MODs and the normal configuration to diagnose missing dependencies and ordering. It does not automatically fix the configuration.

**Project → Prerequisite MODs…** looks up the MODs the source needs. Missing ones are listed with name, packageId and Workshop link, with **Copy missing list** and **Open selected in browser** (subscribing is not done by the app; if only a packageId is known, search the Workshop by name). Found MODs show their location, shipped languages and how many rows depend on each (parent Defs, types, conditional). You can translate without a prerequisite, but rows that depend on it may not be extracted correctly.

### Update or restore an installed translation

Saving edited translations does not change the copy already installed in the game. Run **Install or update translation MOD** again. Updates target editor-generated content with the same translation packageId.

Before replacement, the old translation is saved under `Mods/.rimworld-translator-backups/`; the completion dialog shows its path. To restore it, choose **Game → Restore installed translation** and select the backup folder containing `backup.json` and `mod/`, rather than the inner `mod/` folder. The current installed translation is backed up before restoration too.

Folders containing unrelated MODs or unmanaged files are not overwritten. If an operation is refused, inspect the destination and diagnostic, and preserve existing files rather than deleting them.

### Test a disposable game copy

**Game → Test a disposable game copy** copies the game, source MOD, dependencies and generated translation into the project. It uses separate saves/settings, requests the current target language and stops after about two minutes. Allow enough free disk space; the status-bar cancel button also stops it.

Reports are under the project's `game-tests/<identifier>/`: `runtime-report.json`, `Player.log` and `runtime-stdout.log`. Successful startup/log checks are separate from visual proof. This GUI action does not automatically verify translation screenshots; open the relevant game screen and inspect it yourself.

Development evidence includes translated values from six real MODs displayed in a diagnostic `Verse.Window` inside isolated RimWorld. It is not a normal equipment screen or a general gameplay verification. See the [README verification limits](../README.md#extraction-and-verification-limits).

## 6. Import existing translations and make batch changes

### Import

Choose **File → Import translations (Ctrl+I)**, then select either:

- An XML, CSV, PO or unified diff (.diff/.patch) file.
- A translation MOD or language folder.

Add necessary targets under **Manage languages** before importing. Folder names and CSV/PO language metadata identify the target; XML without language information uses the current target.

The preview shows before/after values, conflicts and unknown keys. Different existing translations are protected by default, and blank incoming translations are ignored. The overwrite-preview prompt defaults to **No**. Include overwrite candidates only when needed, inspect them and choose **Apply changes**. Conflicting duplicates in the incoming data are not selected automatically. Unknown keys are not silently added.

**File → Export CSV** writes all selected languages; with **Add detail columns** it also writes `source_file`, `status`, `previous_english` and `note`. **Export PO** writes the current language and always carries notes, the previous English and fuzzy flags. When editing externally, keep CSV `id/kind/group/key/english/language` and PO `msgctxt/msgid` intact, and edit the `translation` column (`msgstr` in PO) for a reliable round trip. CSV import reads UTF-8 and Excel's Shift_JIS and detects comma, semicolon or tab separators. Rows whose `status` marks them for review, and PO entries flagged fuzzy, stay marked for review after import.

To compare someone else's translation MOD, use **File → Match another translation MOD…**: it shows differing translations, rows only you have translated, rows they lack and keys not in this MOD before you choose what to import.

### Import a diff or patch file

Import translation XML changes from ordinary unified diff files. Choose the diff under **Import translations**, then explicitly choose the **base folder containing the original XML**. The base is read-only: the app does not apply the patch to files or rewrite the original XML.

Align the diff header's relative path with the base folder. For these headers, choose the translation MOD root containing `Languages/`:

```diff
--- a/Languages/Japanese/DefInjected/ThingDef/Things.xml
+++ b/Languages/Japanese/DefInjected/ThingDef/Things.xml
```

The base file must be the **pre-change contents** at `<base-folder>/Languages/Japanese/DefInjected/ThingDef/Things.xml`. Choosing `Languages/Japanese/` itself would not match the path. Normal Git `a/` and `b/` prefixes are handled; arbitrary prefixes are not guessed or stripped.

The entire affected XML is reconstructed in memory and offered for import. Nonempty translations unchanged by the diff may therefore become new candidates or conflict with existing project translations. Review the before/after preview. Removed keys and blank translations do not erase current work.

Mismatched base text, line positions or line endings, unsafe paths, non-XML paths and unsupported binary/other diff formats produce warnings. The app does not guess how to apply them; provide the correct original base and an ordinary unified diff. Existing translations retain the usual conflict protection, and overwrite candidates still require explicit review.

### Glossary, suggestions and replacements

- **Edit → Glossary** stores source terms and target terms. The glossary is shared across the project; QA checks it for the current target. Check its suitability when editing multiple languages. Terms the project already translates the same way several times can appear as **Term candidate** entries in the Suggestions tab; **To glossary** registers one.
- Select an entry and open **Translation memory (Ctrl+M)** to choose an existing translation of exactly identical source text in the same project and language. Different existing translations are grouped by wording. On every save, error-free translations are also remembered in `translation-memory.json` in the settings folder and offered as suggestions for the same source text in other projects. **Apply to all identical** in the Suggestions tab puts the translation into the other untranslated rows with the same source (rows that already differ are left alone, and the change can be undone as a batch). No external service or automatic translation is involved.
- **Batch replace (Ctrl+H)** changes translations in the current language. **Only visible entries** is checked by default, so filters limit its scope. Regular expressions are supported; review the preview before applying.
- Undo/redo imports and replacements with **Undo batch (Ctrl+Alt+Z)** and **Redo batch (Ctrl+Alt+Y)**. These differ from the text editor's Ctrl+Z. Batch history is not retained after closing the app, loading another project or rescanning.

## 7. Source updates, recovery and moving projects

After a source MOD update, use **Project → Rescan source MOD (Ctrl+R)**. Matching keys keep their translations per language; changed source text, new entries and removed entries are distinguished. Changed source text clears review/approval and shows the previous English in the detail panel. Review diagnostics, save, and update the installed translation if necessary. To bring versions of a multi-version project into line, use **Carry translations to another version…** and **Compare versions…** rather than a rescan.

**Project → History and restore** lists saved checkpoints. Choose one and select **Restore selected snapshot** to restore project data and regenerate `mod/`. The current saved state is checkpointed first. The source MOD stays unchanged.

New history works without Git using `.history/`. Reading older `.git/` checkpoints requires Git. External backups should copy the **whole project**, including hidden history folders.

The source MOD path is recorded in `project.json`. Moving only the project works if the source remains at the same path.

To hand a project to another PC as one file, use **File → Export project bundle…** to create a `.rwtbundle`. It holds translations, review states, glossary, notes, assignments and versions; you choose whether to include the generated translation MOD, and the source MOD's files and location are never included. The receiver chooses **File → Import project bundle…**, confirms the description, then selects their own copy of the source MOD (it must have the same packageId) and a folder for the project. An existing `project.json` in that folder is not overwritten. History (`.git/`, `.history/`) is not included.

Without a bundle, if the source path changes on another PC, keep the older project, create a new project from the new source and import translations from the saved old `mod/`; that route does not transfer old review states or history. Changing game-path preferences does not relink an existing project's source MOD.

### Upgrade the application

1. Save and back up the whole translation project.
2. Extract the new app into a separate folder. Keep project data outside it.
3. Open `project.json` using **Open project** or **File → Recent projects**.
4. Verify opening, editing, saving and exporting before replacing the old application folder. Preserve the separate translation projects.

The current app reads existing Japanese and multilingual `schema: 1` projects. To move a project to another environment you can copy the whole folder or use a `.rwtbundle`. Application upgrades and source-MOD rescans are separate operations.

For update notifications, configure a real public GitHub `owner/repository`, enable **Check public GitHub releases** in Preferences and run **Help → Check for updates**. Checks are disabled and unconfigured by default. There is no periodic polling or automatic replacement of the app or projects, and no translation text or project upload.

## Keyboard and display controls

| Action | Shortcut |
| --- | --- |
| New translation | Ctrl+N |
| Open project | Ctrl+O |
| Save and export | Ctrl+S |
| Export translation mod | Ctrl+E |
| Import translations | Ctrl+I |
| Rescan source MOD | Ctrl+R |
| Batch replace | Ctrl+H |
| Translation memory | Ctrl+M |
| Mark reviewed | Ctrl+Enter |
| Mark reviewed and go to the next row needing work | Ctrl+Shift+Enter |
| Next untranslated / next needing review | Ctrl+J / Ctrl+Shift+J |
| Toggle the "Review later" flag | Ctrl+K |
| Insert a suggestion | Ctrl+Shift+1 to 3 |
| Quality check | Ctrl+Shift+K |
| Undo / redo batch | Ctrl+Alt+Z / Ctrl+Alt+Y |
| Refresh filters | Ctrl+F5 |

F1 lists the keyboard shortcuts. Tab moves through search, state filter, source-file filter, table and translation editor. Drag the splitter to adjust table/editor space. Choose an 8–24 point font under **Help → Preferences and game paths → General**. Small windows hide the sidebar; menus retain save, diagnostics and installation actions. Translation and diagnostic panels scroll.

## Before distributing your translation

Use **Project → Translation MOD metadata** for the name, translator, description and translation-license text, then save/export. The usual distribution target is the generated translation MOD folder (`mod/` by default, or your chosen output folder).

**File → Workshop material…** prepares text for a Workshop page: a title, a BBCode description, a changelog (optionally listing the output file changes), a pre-publish checklist and tags, saved as `title.txt`, `description.bbcode.txt`, `changelog.txt` and `checklist.txt` in a separate folder you choose. These are drafts to edit. The editor never publishes to the Workshop; publishing is up to you.

Uncheck **Use source artwork** to generate an independent background and flags instead of adapting the original image. Check the original author's terms before publishing derived artwork or project data/history containing source text, as well as the translation itself.

Flags use MIT-licensed flag-icons. See [third-party notices](../packaging/THIRD_PARTY_NOTICES.md) for bundled libraries. The app distribution contains no game or source-MOD content. The editor's own public-distribution license has not been selected yet.

## Troubleshooting

| Problem | Check |
| --- | --- |
| App does not start | Extract the entire archive and keep `_internal/`. On Linux, check executable permission and the manifest's glibc requirement. Terminal startup exposes error messages. |
| Workshop or game is missing | Choose a local source folder or register the game root under Preferences → Extraction. Set the Workshop, Mods and extra MOD folders and the `ModsConfig.xml` location under Preferences → Folders. |
| Zero candidates | Image-only/DLL-only MODs or patches affecting another MOD may have no extractable entries. Read diagnostics. |
| Export fails | Fix the named language/key's placeholders or tags. Check whether the output folder belongs to another MOD or lacks an editor ownership marker. To change it, use **Project → Set output folder** (or **Use default**); folders that overlap the source MOD, Workshop, the game `Data` folder or a MOD folder added in Preferences are refused. |
| Game still shows English | Save and reinstall the latest translation; check game language, enabled source/translation MODs, load order and diagnostics. |
| Source update changes behavior | Check extraction game version/active MODs, rescan, review changed text, save and reinstall. Heuristic extraction still needs game inspection. |
| Wrong batch change | Undo the batch. After reopening the app, restore history or an external backup. |
| Moved source cannot be rescanned | Restore its path or keep the old project and import saved translations into a new project. |

For reports, use **Help → Copy diagnostic information** and include reproduction steps, expected behavior and actual results. The copied summary omits translation text and source paths. Separate logs/screenshots may contain paths or text; inspect attachments before sharing.

There is no public Issues URL yet. Contact the author, or use the bug-report/feature-request templates once a public repository is available.
